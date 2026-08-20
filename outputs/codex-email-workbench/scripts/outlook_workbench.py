#!/usr/bin/env python3
"""Local multi-account Outlook/Hotmail and Gmail workbench.

The helper deliberately keeps OAuth tokens out of files. On macOS the MSAL
cache is stored as a generic password in Keychain. All mailbox operations
require an explicit account key; there is no "first account" fallback.
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import email.policy
import email.utils
from email.message import EmailMessage
from email.parser import BytesParser
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


SCOPES = ("User.Read", "Mail.ReadWrite", "Mail.Send")
GMAIL_SCOPES = ("https://www.googleapis.com/auth/gmail.modify",)
AUTHORITY = "https://login.microsoftonline.com/common"
GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
GMAIL_ROOT = "https://gmail.googleapis.com/gmail/v1"
KEYCHAIN_SERVICE = "codex-email-workbench.msal"
GMAIL_KEYCHAIN_SERVICE = "codex-email-workbench.google"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "password",
    "secret",
    "cookie",
    "authorization",
    "mfa",
    "recovery_code",
}
TERMINAL_STATUSES = {
    "replied_positive",
    "replied_neutral",
    "replied_negative",
    "bounced",
    "unsubscribed",
    "paused",
    "completed",
}


class WorkbenchError(RuntimeError):
    """Expected, user-actionable failure without secret material."""


class AccountMismatchError(WorkbenchError):
    pass


class ApprovalError(WorkbenchError):
    pass


class DuplicateSendError(WorkbenchError):
    pass


def normalize_email(value: object) -> str:
    email = str(value or "").strip().casefold()
    if not EMAIL_RE.fullmatch(email):
        raise WorkbenchError("账号必须是有效的邮箱地址")
    return email


def normalize_provider(value: object) -> str:
    provider = str(value or "").strip().casefold()
    if provider not in {"outlook", "gmail"}:
        raise WorkbenchError("provider 必须是 outlook 或 gmail")
    return provider


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _reject_sensitive_keys(value: object, path: str = "plan") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_normal = str(key).casefold()
            if key_normal in SENSITIVE_KEYS or any(part in key_normal for part in ("password", "token", "cookie", "secret")):
                raise WorkbenchError(f"{path}.{key} 是敏感字段，已拒绝读取")
            _reject_sensitive_keys(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_sensitive_keys(nested, f"{path}[{index}]")


class KeychainStore:
    """Small macOS Keychain adapter; there is intentionally no file fallback."""

    def __init__(self, service: str = KEYCHAIN_SERVICE, runner: Callable[..., Any] | None = None) -> None:
        self.service = service
        self.runner = runner or subprocess.run

    def available(self) -> bool:
        return sys.platform == "darwin" and shutil.which("security") is not None

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        if not self.available():
            raise WorkbenchError("macOS Keychain 不可用；为避免明文降级，已安全停止")
        return self.runner(["security", *args], capture_output=True, text=True, check=False)

    def load(self, account_key: str) -> str | None:
        result = self._run([
            "find-generic-password",
            "-a",
            account_key,
            "-s",
            self.service,
            "-w",
        ])
        if result.returncode != 0:
            return None
        return result.stdout

    def save(self, account_key: str, serialized_cache: str) -> None:
        result = self._run([
            "add-generic-password",
            "-a",
            account_key,
            "-s",
            self.service,
            "-w",
            serialized_cache,
            "-U",
        ])
        if result.returncode != 0:
            raise WorkbenchError("写入 macOS Keychain 失败；未保存 OAuth 缓存")

    def delete(self, account_key: str) -> None:
        result = self._run([
            "delete-generic-password",
            "-a",
            account_key,
            "-s",
            self.service,
        ])
        if result.returncode not in (0, 44):
            raise WorkbenchError("从 macOS Keychain 移除账号失败")

    def reference(self, account_key: str) -> str:
        return f"keychain:{self.service}:{account_key}"


class LocalState:
    """Non-secret configuration and account metadata outside the Skill package."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or "~/.codex-email-workbench").expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.config_path = self.root / "config.json"
        self.accounts_path = self.root / "accounts.json"
        self.ledger_path = self.root / "ledger.sqlite3"

    def load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WorkbenchError("本地配置无法读取") from exc
        _reject_sensitive_keys(payload, "config")
        return payload

    def save_client_id(self, client_id: str) -> None:
        client_id = str(client_id).strip()
        if not client_id or any(char.isspace() for char in client_id):
            raise WorkbenchError("client_id 不能为空或包含空白字符")
        payload = self.load_config()
        payload["client_id"] = client_id
        _write_json(self.config_path, payload)

    def client_id(self) -> str:
        client_id = str(self.load_config().get("client_id", "")).strip()
        if not client_id:
            raise WorkbenchError("尚未配置 client_id，请先运行 set-client-id")
        return client_id

    def save_google_credentials_path(self, credentials_path: Path | str) -> None:
        path = Path(credentials_path).expanduser()
        if not path.is_file():
            raise WorkbenchError("Google Desktop OAuth credentials JSON 不存在")
        payload = self.load_config()
        payload["google_credentials_path"] = str(path)
        _write_json(self.config_path, payload)

    def google_credentials_path(self) -> Path:
        value = str(self.load_config().get("google_credentials_path", "")).strip()
        if not value:
            raise WorkbenchError("尚未配置 Google Desktop OAuth credentials JSON")
        path = Path(value).expanduser()
        if not path.is_file():
            raise WorkbenchError("Google Desktop OAuth credentials JSON 不存在")
        return path

    def accounts(self) -> list[dict[str, Any]]:
        if not self.accounts_path.exists():
            return []
        try:
            payload = json.loads(self.accounts_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WorkbenchError("本地账号清单无法读取") from exc
        if not isinstance(payload, list):
            raise WorkbenchError("本地账号清单格式无效")
        _reject_sensitive_keys(payload, "accounts")
        return payload

    def save_account(self, account: dict[str, Any]) -> None:
        account_key = normalize_email(account.get("account_key"))
        provider = normalize_provider(account.get("provider", "outlook"))
        records = [
            item
            for item in self.accounts()
            if not (
                str(item.get("account_key", "")).casefold() == account_key
                and str(item.get("provider", "outlook")).casefold() == provider
            )
        ]
        clean = {
            "provider": provider,
            "account_key": account_key,
            "graph_id": str(account.get("graph_id", "")),
            "display_name": str(account.get("display_name", "")),
            "mail": normalize_email(account.get("mail") or account_key),
            "keychain_ref": str(account.get("keychain_ref", "")),
            "authorized_at": str(account.get("authorized_at", utc_now())),
            "status": str(account.get("status", "authorized")),
        }
        records.append(clean)
        _write_json(self.accounts_path, sorted(records, key=lambda item: item["account_key"]))

    def get_account(self, account_key: str, provider: str = "outlook") -> dict[str, Any]:
        normalized = normalize_email(account_key)
        provider = normalize_provider(provider)
        for account in self.accounts():
            if (
                str(account.get("account_key", "")).casefold() == normalized
                and str(account.get("provider", "outlook")).casefold() == provider
            ):
                return account
        raise WorkbenchError(f"账号未授权或不存在：{provider}:{normalized}")

    def remove_account(self, account_key: str, provider: str = "outlook") -> None:
        normalized = normalize_email(account_key)
        provider = normalize_provider(provider)
        records = [
            item
            for item in self.accounts()
            if not (
                str(item.get("account_key", "")).casefold() == normalized
                and str(item.get("provider", "outlook")).casefold() == provider
            )
        ]
        _write_json(self.accounts_path, records)


class Ledger:
    """SQLite ledger containing only routing, status, progress and safe references."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS contacts (
                contact_id TEXT NOT NULL,
                campaign_id TEXT NOT NULL,
                step INTEGER NOT NULL,
                email TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT 'outlook',
                account_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                last_sent_at TEXT,
                last_reply_at TEXT,
                next_followup_at TEXT,
                stop_reason TEXT,
                do_not_contact INTEGER NOT NULL DEFAULT 0,
                thread_hint TEXT,
                notes TEXT,
                PRIMARY KEY (provider, contact_id, campaign_id, step)
            );
            CREATE TABLE IF NOT EXISTS send_operations (
                idempotency_key TEXT PRIMARY KEY,
                provider TEXT NOT NULL DEFAULT 'outlook',
                account_key TEXT NOT NULL,
                contact_id TEXT NOT NULL,
                status TEXT NOT NULL,
                graph_message_id TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approvals (
                digest TEXT PRIMARY KEY,
                provider TEXT NOT NULL DEFAULT 'outlook',
                account_key TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                item_count INTEGER NOT NULL,
                approved_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scan_state (
                account_key TEXT PRIMARY KEY,
                last_inbox_scan_at TEXT NOT NULL
            );
            """
        )
        self._ensure_column("contacts", "provider", "TEXT NOT NULL DEFAULT 'outlook'")
        self._ensure_column("send_operations", "provider", "TEXT NOT NULL DEFAULT 'outlook'")
        self._ensure_column("approvals", "provider", "TEXT NOT NULL DEFAULT 'outlook'")
        self._migrate_contacts_primary_key()
        self.connection.commit()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def close(self) -> None:
        self.connection.close()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {str(row[1]) for row in self.connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _migrate_contacts_primary_key(self) -> None:
        primary_key = [
            str(row[1])
            for row in self.connection.execute("PRAGMA table_info(contacts)")
            if int(row[5]) > 0
        ]
        if primary_key == ["provider", "contact_id", "campaign_id", "step"]:
            return
        self.connection.executescript(
            """
            CREATE TABLE contacts_new (
                contact_id TEXT NOT NULL,
                campaign_id TEXT NOT NULL,
                step INTEGER NOT NULL,
                email TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT 'outlook',
                account_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                last_sent_at TEXT,
                last_reply_at TEXT,
                next_followup_at TEXT,
                stop_reason TEXT,
                do_not_contact INTEGER NOT NULL DEFAULT 0,
                thread_hint TEXT,
                notes TEXT,
                PRIMARY KEY (provider, contact_id, campaign_id, step)
            );
            INSERT INTO contacts_new(
                contact_id, campaign_id, step, email, name, provider, account_key, status,
                last_sent_at, last_reply_at, next_followup_at, stop_reason,
                do_not_contact, thread_hint, notes
            )
            SELECT contact_id, campaign_id, step, email, name, provider, account_key, status,
                   last_sent_at, last_reply_at, next_followup_at, stop_reason,
                   do_not_contact, thread_hint, notes
            FROM contacts;
            DROP TABLE contacts;
            ALTER TABLE contacts_new RENAME TO contacts;
            """
        )

    def upsert_contact(self, row: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT INTO contacts
              (contact_id, campaign_id, step, email, name, provider, account_key, status,
              last_sent_at, last_reply_at, next_followup_at, stop_reason,
              do_not_contact, thread_hint, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, contact_id, campaign_id, step) DO UPDATE SET
              email=excluded.email, name=excluded.name, provider=excluded.provider,
              account_key=excluded.account_key,
              status=excluded.status, last_sent_at=excluded.last_sent_at,
              last_reply_at=excluded.last_reply_at, next_followup_at=excluded.next_followup_at,
              stop_reason=excluded.stop_reason, do_not_contact=excluded.do_not_contact,
              thread_hint=excluded.thread_hint, notes=excluded.notes
            """,
            (
                str(row.get("contact_id", "")).strip(),
                str(row.get("campaign_id", "")).strip(),
                int(str(row.get("step", "0")).strip() or 0),
                normalize_email(row.get("email")),
                str(row.get("name", "")).strip(),
                normalize_provider(row.get("provider", "outlook")),
                normalize_email(row.get("account_key")),
                str(row.get("status", "draft")).strip() or "draft",
                str(row.get("last_sent_at", "")).strip() or None,
                str(row.get("last_reply_at", "")).strip() or None,
                str(row.get("next_followup_at", "")).strip() or None,
                str(row.get("stop_reason", "")).strip() or None,
                1 if str(row.get("do_not_contact", "")).strip().casefold() in {"1", "true", "yes", "y", "是"} else 0,
                str(row.get("thread_hint", "")).strip() or None,
                str(row.get("notes", "")).strip() or None,
            ),
        )
        self.connection.commit()

    def followup_candidates(self, account_key: str, as_of: str | None = None, provider: str = "outlook") -> list[dict[str, Any]]:
        normalized = normalize_email(account_key)
        provider = normalize_provider(provider)
        cutoff = as_of or utc_now()
        rows = self.connection.execute(
            """
            SELECT contact_id, campaign_id, step, email, name, provider, account_key, status,
                   last_sent_at, last_reply_at, next_followup_at, stop_reason, thread_hint
            FROM contacts
            WHERE provider = ? AND account_key = ?
              AND next_followup_at IS NOT NULL
              AND next_followup_at <= ?
              AND do_not_contact = 0
              AND last_reply_at IS NULL
              AND status NOT IN ('replied_positive', 'replied_neutral', 'replied_negative',
                                 'bounced', 'unsubscribed', 'paused', 'completed')
            ORDER BY next_followup_at, contact_id
            """,
            (provider, normalized, cutoff),
        ).fetchall()
        return [dict(row) for row in rows]

    def contact_status(self, account_key: str, contact_id: str, provider: str = "outlook") -> str | None:
        row = self.connection.execute(
            "SELECT status FROM contacts WHERE provider = ? AND account_key = ? AND contact_id = ? "
            "ORDER BY campaign_id, step LIMIT 1",
            (normalize_provider(provider), normalize_email(account_key), str(contact_id)),
        ).fetchone()
        return str(row[0]) if row else None

    def contact_stop_reason(self, account_key: str, contact_id: str, provider: str = "outlook") -> str | None:
        row = self.connection.execute(
            "SELECT status, do_not_contact, last_reply_at FROM contacts "
            "WHERE provider = ? AND account_key = ? AND contact_id = ? ORDER BY campaign_id, step LIMIT 1",
            (normalize_provider(provider), normalize_email(account_key), str(contact_id)),
        ).fetchone()
        if row is None:
            return "missing_contact"
        if bool(row[1]):
            return "do_not_contact"
        if row[2]:
            return "reply_detected"
        if str(row[0]) in TERMINAL_STATUSES:
            return str(row[0])
        return None

    def record_reply(self, account_key: str, sender_address: str, received_at: str, thread_id: str = "", provider: str = "outlook") -> int:
        normalized = normalize_email(account_key)
        sender = normalize_email(sender_address)
        provider = normalize_provider(provider)
        cursor = self.connection.execute(
            """
            UPDATE contacts
            SET status = 'replied_neutral', last_reply_at = ?, next_followup_at = NULL,
                stop_reason = 'reply_detected', thread_hint = COALESCE(NULLIF(?, ''), thread_hint)
            WHERE provider = ? AND account_key = ? AND lower(email) = ?
              AND status NOT IN ('bounced', 'unsubscribed')
            """,
            (received_at, thread_id, provider, normalized, sender),
        )
        self.connection.commit()
        return cursor.rowcount

    def last_scan(self, account_key: str, provider: str = "outlook") -> str | None:
        normalized = normalize_email(account_key)
        scan_key = f"{normalize_provider(provider)}:{normalized}"
        row = self.connection.execute(
            "SELECT last_inbox_scan_at FROM scan_state WHERE account_key = ?", (scan_key,)
        ).fetchone()
        return str(row[0]) if row else None

    def set_last_scan(self, account_key: str, timestamp: str, provider: str = "outlook") -> None:
        normalized = normalize_email(account_key)
        scan_key = f"{normalize_provider(provider)}:{normalized}"
        self.connection.execute(
            "INSERT INTO scan_state(account_key, last_inbox_scan_at) VALUES (?, ?) "
            "ON CONFLICT(account_key) DO UPDATE SET last_inbox_scan_at=excluded.last_inbox_scan_at",
            (scan_key, timestamp),
        )
        self.connection.commit()

    def operation_status(self, idempotency_key: str) -> str | None:
        row = self.connection.execute(
            "SELECT status FROM send_operations WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        return str(row[0]) if row else None

    def begin_send(self, idempotency_key: str, account_key: str, contact_id: str, provider: str = "outlook") -> None:
        existing = self.operation_status(idempotency_key)
        if existing == "sent":
            raise DuplicateSendError(f"已发送，拒绝重复发送：{idempotency_key}")
        if existing == "in_flight":
            raise DuplicateSendError(f"上次发送结果未知，需人工核对后再继续：{idempotency_key}")
        self.connection.execute(
            "INSERT INTO send_operations(idempotency_key, provider, account_key, contact_id, status, updated_at) "
            "VALUES (?, ?, ?, ?, 'in_flight', ?) "
            "ON CONFLICT(idempotency_key) DO UPDATE SET provider=excluded.provider, account_key=excluded.account_key, "
            "contact_id=excluded.contact_id, status='in_flight', updated_at=excluded.updated_at",
            (idempotency_key, normalize_provider(provider), normalize_email(account_key), contact_id, utc_now()),
        )
        self.connection.commit()

    def mark_sent(self, idempotency_key: str, graph_message_id: str) -> None:
        self.connection.execute(
            "UPDATE send_operations SET status='sent', graph_message_id=?, updated_at=? WHERE idempotency_key=?",
            (graph_message_id, utc_now(), idempotency_key),
        )
        self.connection.commit()

    def mark_failed(self, idempotency_key: str, error_category: str) -> None:
        self.connection.execute(
            "UPDATE send_operations SET status=?, updated_at=? WHERE idempotency_key=?",
            (f"failed:{error_category}"[:120], utc_now(), idempotency_key),
        )
        self.connection.commit()

    def resolve_in_flight(self, idempotency_key: str, status: str) -> None:
        if status not in {"sent", "failed:manual_review"}:
            raise WorkbenchError("只能将未知结果标记为 sent 或 failed:manual_review")
        self.connection.execute(
            "UPDATE send_operations SET status=?, updated_at=? WHERE idempotency_key=?",
            (status, utc_now(), idempotency_key),
        )
        self.connection.commit()

    def save_approval(self, digest: str, account_key: str, batch_id: str, item_count: int, provider: str = "outlook") -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO approvals(digest, provider, account_key, batch_id, item_count, approved_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (digest, normalize_provider(provider), normalize_email(account_key), batch_id, item_count, utc_now()),
        )
        self.connection.commit()

    def has_approval(self, digest: str, account_key: str, batch_id: str, item_count: int, provider: str = "outlook") -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM approvals WHERE digest=? AND provider=? AND account_key=? AND batch_id=? AND item_count=?",
            (digest, normalize_provider(provider), normalize_email(account_key), batch_id, item_count),
        ).fetchone()
        return row is not None


class GraphClient:
    def __init__(self, access_token: str, opener: Callable[..., Any] | None = None) -> None:
        if not access_token:
            raise WorkbenchError("Graph access token 缺失")
        self.access_token = access_token
        self.opener = opener or urllib.request.urlopen

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{GRAPH_ROOT}{path}"
        encoded = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url,
            data=encoded,
            method=method,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            response = self.opener(request, timeout=30)
            raw = response.read()
        except urllib.error.HTTPError as exc:
            category = "rate_limited" if exc.code == 429 else f"http_{exc.code}"
            raise WorkbenchError(f"Microsoft Graph 请求失败：{category}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise WorkbenchError(f"Microsoft Graph 网络失败：{type(exc).__name__}") from None
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WorkbenchError("Microsoft Graph 返回格式无效") from exc
        if not isinstance(payload, dict):
            raise WorkbenchError("Microsoft Graph 返回结构无效")
        if "error" in payload:
            error_code = str(payload.get("error", {}).get("code", "graph_error"))
            raise WorkbenchError(f"Microsoft Graph 请求失败：{error_code}")
        return payload

    def get_me(self) -> dict[str, Any]:
        return self.request("GET", "/me?$select=id,mail,userPrincipalName,displayName")

    def list_messages(self, since: str | None = None, top: int = 50) -> list[dict[str, Any]]:
        if top < 1 or top > 100:
            raise WorkbenchError("top 必须在 1 到 100 之间")
        params = {
            "$top": str(top),
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,subject,receivedDateTime,from",
        }
        if since:
            params["$filter"] = f"receivedDateTime ge {since}"
        path = "/me/mailFolders/Inbox/messages?" + urllib.parse.urlencode(params, safe="$,()")
        payload = self.request("GET", path)
        return [item for item in payload.get("value", []) if isinstance(item, dict)]

    def get_message(self, message_id: str) -> dict[str, Any]:
        safe_id = urllib.parse.quote(str(message_id), safe="")
        return self.request("GET", f"/me/messages/{safe_id}?$select=id,subject,body,toRecipients,conversationId")

    def create_draft(self, recipients: Iterable[str], subject: str, body: str) -> dict[str, Any]:
        to_recipients = [{"emailAddress": {"address": normalize_email(item)}} for item in recipients]
        if not to_recipients:
            raise WorkbenchError("草稿至少需要一个收件人")
        return self.request(
            "POST",
            "/me/messages",
            {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": to_recipients,
            },
        )

    def create_reply_draft(self, message_id: str, body: str) -> dict[str, Any]:
        safe_id = urllib.parse.quote(str(message_id), safe="")
        return self.request("POST", f"/me/messages/{safe_id}/createReply", {"comment": body})

    def send_draft(self, message_id: str) -> None:
        safe_id = urllib.parse.quote(str(message_id), safe="")
        self.request("POST", f"/me/messages/{safe_id}/send", {})


class GmailClient:
    """Small REST adapter for Gmail; it mirrors the Graph client surface."""

    def __init__(self, access_token: str, opener: Callable[..., Any] | None = None) -> None:
        if not access_token:
            raise WorkbenchError("Gmail access token 缺失")
        self.access_token = access_token
        self.opener = opener or urllib.request.urlopen

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{GMAIL_ROOT}{path}"
        encoded = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url,
            data=encoded,
            method=method,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            response = self.opener(request, timeout=30)
            raw = response.read()
        except urllib.error.HTTPError as exc:
            category = "rate_limited" if exc.code == 429 else f"http_{exc.code}"
            raise WorkbenchError(f"Gmail API 请求失败：{category}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise WorkbenchError(f"Gmail API 网络失败：{type(exc).__name__}") from None
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WorkbenchError("Gmail API 返回格式无效") from exc
        if not isinstance(payload, dict):
            raise WorkbenchError("Gmail API 返回结构无效")
        if "error" in payload:
            error_code = str(payload.get("error", {}).get("code", "gmail_error"))
            raise WorkbenchError(f"Gmail API 请求失败：{error_code}")
        return payload

    def get_me(self) -> dict[str, Any]:
        profile = self.request("GET", "/users/me/profile")
        address = normalize_email(profile.get("emailAddress"))
        return {"id": address, "mail": address, "userPrincipalName": address, "displayName": ""}

    def list_messages(self, since: str | None = None, top: int = 50) -> list[dict[str, Any]]:
        if top < 1 or top > 100:
            raise WorkbenchError("top 必须在 1 到 100 之间")
        query = "in:inbox"
        if since:
            try:
                date_value = dt.datetime.fromisoformat(since.replace("Z", "+00:00")).date()
            except ValueError as exc:
                raise WorkbenchError("since 必须是 ISO 时间") from exc
            query += f" after:{date_value.strftime('%Y/%m/%d')}"
        params = urllib.parse.urlencode({"maxResults": top, "q": query})
        payload = self.request("GET", f"/users/me/messages?{params}")
        messages: list[dict[str, Any]] = []
        for item in payload.get("messages", [])[:top]:
            if isinstance(item, dict) and item.get("id"):
                messages.append(self.get_message(str(item["id"])))
        return messages

    def _raw_message(self, message_id: str) -> dict[str, Any]:
        safe_id = urllib.parse.quote(str(message_id), safe="")
        return self.request("GET", f"/users/me/messages/{safe_id}?format=raw")

    @staticmethod
    def _decode_raw(raw_value: str) -> email.message.EmailMessage:
        padding = "=" * (-len(raw_value) % 4)
        try:
            raw_bytes = base64.urlsafe_b64decode((raw_value + padding).encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise WorkbenchError("Gmail MIME 内容无效") from exc
        return BytesParser(policy=email.policy.default).parsebytes(raw_bytes)

    @staticmethod
    def _message_fields(payload: dict[str, Any], message: email.message.EmailMessage) -> dict[str, Any]:
        sender = email.utils.parseaddr(message.get("From", ""))[1]
        to_addresses = [email.utils.parseaddr(value)[1] for value in message.get_all("To", [])]
        to_recipients = [
            {"emailAddress": {"address": normalize_email(address)}}
            for address in to_addresses
            if address
        ]
        try:
            body = message.get_body(preferencelist=("plain", "html"))
            content = body.get_content() if body else message.get_content()
        except (AttributeError, TypeError, UnicodeDecodeError):
            content = ""
        return {
            "id": str(payload.get("id", "")),
            "conversationId": str(payload.get("threadId", "")),
            "subject": str(message.get("Subject", "")),
            "receivedDateTime": str(message.get("Date", "")),
            "from": {"emailAddress": {"address": normalize_email(sender)}} if sender else {"emailAddress": {"address": ""}},
            "body": {"contentType": "Text", "content": content},
            "toRecipients": to_recipients,
            "message_id_header": str(message.get("Message-ID", "")),
            "references": str(message.get("References", "")),
        }

    def get_message(self, message_id: str) -> dict[str, Any]:
        payload = self._raw_message(message_id)
        raw_value = str(((payload.get("payload") or {}).get("body") or {}).get("data", ""))
        if not raw_value:
            raw_value = str(payload.get("raw", ""))
        return self._message_fields(payload, self._decode_raw(raw_value))

    @staticmethod
    def _encode_message(recipients: Iterable[str], subject: str, body: str, headers: dict[str, str] | None = None) -> str:
        message = EmailMessage()
        message["To"] = ", ".join(normalize_email(item) for item in recipients)
        message["Subject"] = subject
        for key, value in (headers or {}).items():
            if value:
                message[key] = value
        message.set_content(body)
        return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")

    def create_draft(self, recipients: Iterable[str], subject: str, body: str) -> dict[str, Any]:
        to_list = list(recipients)
        if not to_list:
            raise WorkbenchError("草稿至少需要一个收件人")
        return self.request(
            "POST",
            "/users/me/drafts",
            {"message": {"raw": self._encode_message(to_list, subject, body)}},
        )

    def create_reply_draft(self, message_id: str, body: str) -> dict[str, Any]:
        original = self.get_message(message_id)
        sender = (((original.get("from") or {}).get("emailAddress") or {}).get("address"))
        if not sender:
            raise WorkbenchError("原邮件缺少可用发件人，无法创建回复草稿")
        subject = str(original.get("subject", ""))
        if not subject.casefold().startswith("re:"):
            subject = f"Re: {subject}"
        message_id_header = str(original.get("message_id_header", ""))
        references = " ".join(part for part in (str(original.get("references", "")), message_id_header) if part).strip()
        raw = self._encode_message(
            [sender],
            subject,
            body,
            {"In-Reply-To": message_id_header, "References": references},
        )
        return self.request(
            "POST",
            "/users/me/drafts",
            {"message": {"raw": raw, "threadId": str(original.get("conversationId", ""))}},
        )

    def send_draft(self, message_id: str) -> None:
        self.request("POST", "/users/me/drafts/send", {"id": str(message_id)})


class GoogleAuth:
    def __init__(self, state: LocalState, keychain: KeychainStore | None = None, google_modules: dict[str, Any] | None = None) -> None:
        self.state = state
        self.keychain = keychain or KeychainStore(GMAIL_KEYCHAIN_SERVICE)
        self.google_modules = google_modules

    def _modules(self) -> dict[str, Any]:
        if self.google_modules is not None:
            return self.google_modules
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise WorkbenchError("缺少 Gmail OAuth 依赖，请按 INSTALL.md 安装；未连接邮箱") from exc
        return {"Request": Request, "Credentials": Credentials, "InstalledAppFlow": InstalledAppFlow}

    def authorize(self, account_key: str) -> dict[str, Any]:
        normalized = normalize_email(account_key)
        if any(
            str(item.get("account_key", "")).casefold() == normalized
            and str(item.get("provider", "outlook")).casefold() == "gmail"
            for item in self.state.accounts()
        ):
            raise WorkbenchError(f"账号已授权，跳过重复授权：gmail:{normalized}")
        if not self.keychain.available():
            raise WorkbenchError("macOS Keychain 不可用；为避免明文保存 Gmail OAuth token，已安全停止")
        modules = self._modules()
        flow = modules["InstalledAppFlow"].from_client_secrets_file(
            str(self.state.google_credentials_path()), list(GMAIL_SCOPES)
        )
        credentials = flow.run_local_server(port=0, open_browser=True)
        if not credentials or not getattr(credentials, "token", None):
            raise WorkbenchError("Gmail OAuth 授权未完成")
        profile = GmailClient(str(credentials.token)).get_me()
        actual = normalize_email(profile.get("mail") or profile.get("userPrincipalName"))
        if actual != normalized:
            raise AccountMismatchError(f"Gmail 授权账号不匹配：计划 {normalized}，API 返回 {actual}")
        self.keychain.save(normalized, credentials.to_json())
        record = {
            "provider": "gmail",
            "account_key": normalized,
            "graph_id": actual,
            "display_name": "",
            "mail": actual,
            "keychain_ref": self.keychain.reference(normalized),
            "authorized_at": utc_now(),
            "status": "authorized",
        }
        self.state.save_account(record)
        return record

    def access_token(self, account_key: str) -> str:
        normalized = normalize_email(account_key)
        self.state.get_account(normalized, "gmail")
        if not self.keychain.available():
            raise WorkbenchError("macOS Keychain 不可用；未尝试明文降级")
        serialized = self.keychain.load(normalized)
        if not serialized:
            raise WorkbenchError("Gmail 账号缺少 Keychain OAuth 缓存，请重新授权")
        modules = self._modules()
        try:
            credentials = modules["Credentials"].from_authorized_user_info(json.loads(serialized), GMAIL_SCOPES)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise WorkbenchError("Gmail Keychain OAuth 缓存无效，请重新授权") from exc
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(modules["Request"]())
            self.keychain.save(normalized, credentials.to_json())
        if not credentials.valid or not credentials.token:
            raise WorkbenchError("Gmail OAuth 会话已过期，请重新授权")
        return str(credentials.token)


class MsalAuth:
    def __init__(self, state: LocalState, keychain: KeychainStore | None = None, msal_module: Any | None = None) -> None:
        self.state = state
        self.keychain = keychain or KeychainStore()
        self.msal_module = msal_module

    def _msal(self) -> Any:
        if self.msal_module is not None:
            return self.msal_module
        try:
            import msal  # type: ignore
        except ImportError as exc:
            raise WorkbenchError("缺少 msal 依赖，请按 INSTALL.md 安装；未连接邮箱") from exc
        return msal

    def _app(self, cache: Any | None = None) -> tuple[Any, Any]:
        msal = self._msal()
        if cache is None:
            cache = msal.SerializableTokenCache()
        app = msal.PublicClientApplication(self.state.client_id(), authority=AUTHORITY, token_cache=cache)
        return app, cache

    def authorize(self, account_key: str) -> dict[str, Any]:
        normalized = normalize_email(account_key)
        if any(
            str(item.get("account_key", "")).casefold() == normalized
            and str(item.get("provider", "outlook")).casefold() == "outlook"
            for item in self.state.accounts()
        ):
            raise WorkbenchError(f"账号已授权，跳过重复授权：{normalized}")
        if not self.keychain.available():
            raise WorkbenchError("macOS Keychain 不可用；为避免明文保存 OAuth token，已安全停止")
        app, cache = self._app()
        result = app.acquire_token_interactive(scopes=list(SCOPES), prompt="select_account")
        if not isinstance(result, dict) or not result.get("access_token"):
            error = str(result.get("error", "authorization_failed")) if isinstance(result, dict) else "authorization_failed"
            raise WorkbenchError(f"OAuth 授权未完成：{error}")
        profile = GraphClient(str(result["access_token"])).get_me()
        actual = normalize_email(profile.get("mail") or profile.get("userPrincipalName"))
        if actual != normalized:
            raise AccountMismatchError(f"授权账号不匹配：计划 {normalized}，Graph 返回 {actual}")
        serialized = cache.serialize() if cache.has_state_changed else ""
        if not serialized:
            serialized = cache.serialize()
        self.keychain.save(normalized, serialized)
        record = {
            "provider": "outlook",
            "account_key": normalized,
            "graph_id": str(profile.get("id", "")),
            "display_name": str(profile.get("displayName", "")),
            "mail": actual,
            "keychain_ref": self.keychain.reference(normalized),
            "authorized_at": utc_now(),
            "status": "authorized",
        }
        self.state.save_account(record)
        return record

    def access_token(self, account_key: str) -> str:
        normalized = normalize_email(account_key)
        self.state.get_account(normalized, "outlook")
        if not self.keychain.available():
            raise WorkbenchError("macOS Keychain 不可用；未尝试明文降级")
        serialized = self.keychain.load(normalized)
        if not serialized:
            raise WorkbenchError("账号缺少 Keychain OAuth 缓存，请重新授权")
        msal = self._msal()
        cache = msal.SerializableTokenCache()
        cache.deserialize(serialized)
        app, cache = self._app(cache)
        accounts = app.get_accounts()
        matching_accounts = [
            account
            for account in accounts
            if str(account.get("username", "")).strip().casefold() == normalized
        ]
        if len(matching_accounts) != 1:
            raise WorkbenchError("Keychain 缓存中没有唯一匹配的账号，请重新授权")
        result = app.acquire_token_silent(list(SCOPES), account=matching_accounts[0])
        if not isinstance(result, dict) or not result.get("access_token"):
            raise WorkbenchError("OAuth 会话已过期，请在微软官方页面重新授权")
        if cache.has_state_changed:
            self.keychain.save(normalized, cache.serialize())
        return str(result["access_token"])


@dataclass(frozen=True)
class Preview:
    account_key: str
    batch_id: str
    items: tuple[dict[str, Any], ...]
    cadence: str
    interval_seconds: float = 0.0
    provider: str = "outlook"

    def canonical(self) -> dict[str, Any]:
        return {
            "provider": normalize_provider(self.provider),
            "account_key": normalize_email(self.account_key),
            "batch_id": self.batch_id,
            "cadence": self.cadence,
            "interval_seconds": self.interval_seconds,
            "items": [
                {
                    "idempotency_key": str(item["idempotency_key"]),
                    "draft_id": str(item["draft_id"]),
                    "contact_id": str(item["contact_id"]),
                    "to": [normalize_email(address) for address in item["to"]],
                    "subject": str(item["subject"]),
                    "body": str(item["body"]),
                }
                for item in self.items
            ],
        }

    def digest(self) -> str:
        encoded = json.dumps(self.canonical(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def load_plan(path: Path) -> dict[str, Any]:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkbenchError("发送计划无法读取") from exc
    _reject_sensitive_keys(plan)
    if not isinstance(plan, dict):
        raise WorkbenchError("发送计划必须是 JSON 对象")
    return plan


def preview_from_plan(plan: dict[str, Any]) -> Preview:
    provider = normalize_provider(plan.get("provider", "outlook"))
    account_key = normalize_email(plan.get("account_key"))
    batch_id = str(plan.get("batch_id", "")).strip()
    cadence = str(plan.get("cadence", "")).strip()
    try:
        interval_seconds = float(plan.get("interval_seconds", 0))
    except (TypeError, ValueError) as exc:
        raise WorkbenchError("interval_seconds 必须是非负数字") from exc
    if interval_seconds < 0 or interval_seconds > 86400:
        raise WorkbenchError("interval_seconds 必须在 0 到 86400 之间")
    raw_items = plan.get("items")
    if not batch_id or not cadence or not isinstance(raw_items, list) or not raw_items:
        raise WorkbenchError("发送计划必须包含 batch_id、cadence 和非空 items")
    items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise WorkbenchError("发送计划 items 格式无效")
        recipients = item.get("to")
        if isinstance(recipients, str):
            recipients = [recipients]
        if not isinstance(recipients, list) or not recipients:
            raise WorkbenchError("每封邮件必须有收件人")
        items.append({
            "idempotency_key": str(item.get("idempotency_key", "")).strip(),
            "draft_id": str(item.get("draft_id", "")).strip(),
            "contact_id": str(item.get("contact_id", "")).strip(),
            "to": [normalize_email(address) for address in recipients],
            "subject": str(item.get("subject", "")),
            "body": str(item.get("body", "")),
        })
    if any(not item["idempotency_key"] or not item["draft_id"] or not item["contact_id"] or not item["subject"] for item in items):
        raise WorkbenchError("每个发送项必须有 idempotency_key、draft_id、contact_id 和 subject")
    return Preview(
        account_key=account_key,
        batch_id=batch_id,
        items=tuple(items),
        cadence=cadence,
        interval_seconds=interval_seconds,
        provider=provider,
    )


class Workbench:
    def __init__(
        self,
        state: LocalState,
        auth: MsalAuth | None = None,
        graph_factory: Callable[[str], GraphClient] | None = None,
        gmail_auth: GoogleAuth | None = None,
        client_factory: Callable[[str, str], Any] | None = None,
    ) -> None:
        self.state = state
        self.auth = auth or MsalAuth(state)
        self.gmail_auth = gmail_auth or GoogleAuth(state)
        self.ledger = Ledger(state.ledger_path)
        self.graph_factory = graph_factory
        self.client_factory = client_factory

    def close(self) -> None:
        self.ledger.close()

    def client(self, provider: str, account_key: str) -> Any:
        provider = normalize_provider(provider)
        normalized = normalize_email(account_key)
        self.state.get_account(normalized, provider)
        if self.client_factory:
            client = self.client_factory(provider, normalized)
        elif provider == "outlook":
            if self.graph_factory:
                client = self.graph_factory(normalized)
            else:
                token = self.auth.access_token(normalized)
                client = GraphClient(token)
        else:
            token = self.gmail_auth.access_token(normalized)
            client = GmailClient(token)
        profile = client.get_me()
        actual = normalize_email(profile.get("mail") or profile.get("userPrincipalName"))
        if actual != normalized:
            raise AccountMismatchError(f"{provider} 当前账号与指定账号不一致：{normalized} != {actual}")
        return client

    def graph(self, account_key: str) -> GraphClient:
        return self.client("outlook", account_key)

    def approve_plan(self, preview: Preview) -> str:
        digest = preview.digest()
        self.ledger.save_approval(digest, preview.account_key, preview.batch_id, len(preview.items), preview.provider)
        return digest

    def send_plan(self, preview: Preview, approval_digest: str, confirm: bool) -> list[dict[str, Any]]:
        if not confirm:
            raise ApprovalError("未提供明确批准，发送已阻止")
        digest = preview.digest()
        if digest != approval_digest or not self.ledger.has_approval(
            digest, preview.account_key, preview.batch_id, len(preview.items), preview.provider
        ):
            raise ApprovalError("预览已变化或批准不存在，必须重新预览并批准")
        client = self.client(preview.provider, preview.account_key)
        pending: list[dict[str, Any]] = []
        for item in preview.items:
            stop_reason = self.ledger.contact_stop_reason(preview.account_key, item["contact_id"], preview.provider)
            if stop_reason:
                raise WorkbenchError(f"联系人不可发送（{stop_reason}）：{item['contact_id']}")
            status = self.ledger.operation_status(item["idempotency_key"])
            if status == "sent":
                pending.append({"idempotency_key": item["idempotency_key"], "status": "already_sent"})
                continue
            if status == "in_flight":
                raise DuplicateSendError(f"上次发送结果未知，需人工核对：{item['idempotency_key']}")
            current = client.get_message(item["draft_id"])
            if not _draft_matches(current, item):
                raise ApprovalError(f"草稿已变化，批准失效：{item['draft_id']}")
            pending.append({"idempotency_key": item["idempotency_key"], "status": "pending", "item": item})
        results: list[dict[str, Any]] = []
        sent_count = 0
        for entry in pending:
            if entry["status"] == "already_sent":
                results.append(entry)
                continue
            item = entry["item"]
            self.ledger.begin_send(item["idempotency_key"], preview.account_key, item["contact_id"], preview.provider)
            try:
                client.send_draft(item["draft_id"])
            except WorkbenchError as exc:
                self.ledger.mark_failed(item["idempotency_key"], _error_category(str(exc)))
                raise
            self.ledger.mark_sent(item["idempotency_key"], item["draft_id"])
            results.append({"idempotency_key": item["idempotency_key"], "status": "sent"})
            sent_count += 1
            if preview.interval_seconds and sent_count < len(pending):
                time.sleep(preview.interval_seconds)
        return results

    def create_draft(
        self,
        account_key: str,
        recipients: Iterable[str],
        subject: str,
        body: str,
        provider: str = "outlook",
    ) -> dict[str, Any]:
        return self.client(provider, account_key).create_draft(recipients, subject, body)

    def create_reply_draft(self, account_key: str, message_id: str, body: str, provider: str = "outlook") -> dict[str, Any]:
        return self.client(provider, account_key).create_reply_draft(message_id, body)

    def check_replies(
        self,
        account_key: str,
        since: str | None = None,
        top: int = 50,
        provider: str = "outlook",
    ) -> list[dict[str, Any]]:
        normalized = normalize_email(account_key)
        since = since or self.ledger.last_scan(normalized, provider)
        messages = self.client(provider, normalized).list_messages(since=since, top=top)
        results: list[dict[str, Any]] = []
        for message in messages:
            sender = (((message.get("from") or {}).get("emailAddress") or {}).get("address"))
            if sender:
                try:
                    matched = self.ledger.record_reply(
                        normalized,
                        sender,
                        str(message.get("receivedDateTime", utc_now())),
                        str(message.get("conversationId", "")),
                        provider,
                    )
                except WorkbenchError:
                    matched = 0
            else:
                matched = 0
            results.append({
                "id": str(message.get("id", "")),
                "conversation_id": str(message.get("conversationId", "")),
                "from": str(sender or ""),
                "subject": str(message.get("subject", "")),
                "received_at": str(message.get("receivedDateTime", "")),
                "matched_contacts": matched,
            })
        self.ledger.set_last_scan(normalized, utc_now(), provider)
        return results


def _draft_matches(current: dict[str, Any], item: dict[str, Any]) -> bool:
    if str(current.get("subject", "")) != str(item["subject"]):
        return False
    current_to = {
        normalize_email(((recipient.get("emailAddress") or {}).get("address")))
        for recipient in current.get("toRecipients", [])
        if isinstance(recipient, dict) and ((recipient.get("emailAddress") or {}).get("address"))
    }
    if current_to != {normalize_email(address) for address in item["to"]}:
        return False
    body = current.get("body") or {}
    return body.get("contentType") == "Text" and str(body.get("content", "")) == str(item["body"])


def _error_category(message: str) -> str:
    lowered = message.casefold()
    if "429" in lowered or "rate" in lowered or "limit" in lowered:
        return "rate_limited"
    if "auth" in lowered or "token" in lowered or "permission" in lowered:
        return "authorization"
    return "graph_error"


def _read_body(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkbenchError("正文文件无法读取") from exc


def _json_output(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path("~/.codex-email-workbench").expanduser())
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("env", help="检查 Python、MSAL、Google OAuth 和 macOS Keychain")
    client = sub.add_parser("set-client-id", help="保存非敏感 Entra public client_id")
    client.add_argument("client_id")
    google_client = sub.add_parser("set-google-credentials", help="保存 Google Desktop OAuth credentials 文件路径")
    google_client.add_argument("credentials_json", type=Path)
    sub.add_parser("accounts", help="列出本地已授权账号")
    auth = sub.add_parser("authorize", help="启动一个账号的官方 OAuth 授权")
    auth.add_argument("--provider", required=True, choices=("outlook", "gmail"))
    auth.add_argument("--account-key", required=True)
    verify = sub.add_parser("verify", help="调用 Graph /me 验证指定账号")
    verify.add_argument("--provider", required=True, choices=("outlook", "gmail"))
    verify.add_argument("--account-key", required=True)
    remove = sub.add_parser("remove", help="移除指定账号的 Keychain 缓存和本地记录")
    remove.add_argument("--provider", required=True, choices=("outlook", "gmail"))
    remove.add_argument("--account-key", required=True)
    inbox = sub.add_parser("inbox", help="读取指定账号的新邮件摘要")
    inbox.add_argument("--provider", required=True, choices=("outlook", "gmail"))
    inbox.add_argument("--account-key", required=True)
    inbox.add_argument("--since")
    inbox.add_argument("--top", type=int, default=50)
    draft = sub.add_parser("draft", help="在指定账号创建新邮件草稿")
    draft.add_argument("--provider", required=True, choices=("outlook", "gmail"))
    draft.add_argument("--account-key", required=True)
    draft.add_argument("--to", required=True, nargs="+")
    draft.add_argument("--subject", required=True)
    draft.add_argument("--body-file", required=True, type=Path)
    reply = sub.add_parser("reply-draft", help="在指定账号创建线程回复草稿")
    reply.add_argument("--provider", required=True, choices=("outlook", "gmail"))
    reply.add_argument("--account-key", required=True)
    reply.add_argument("--message-id", required=True)
    reply.add_argument("--body-file", required=True, type=Path)
    replies = sub.add_parser("check-replies", help="检查指定账号的回信并更新台账")
    replies.add_argument("--provider", required=True, choices=("outlook", "gmail"))
    replies.add_argument("--account-key", required=True)
    replies.add_argument("--since")
    replies.add_argument("--top", type=int, default=50)
    import_cmd = sub.add_parser("import-contacts", help="导入非敏感联系人台账字段")
    import_cmd.add_argument("csv_file", type=Path)
    followups = sub.add_parser("followups", help="生成指定账号的到期 follow-up 候选")
    followups.add_argument("--provider", required=True, choices=("outlook", "gmail"))
    followups.add_argument("--account-key", required=True)
    followups.add_argument("--as-of")
    approve = sub.add_parser("approve-plan", help="记录当前预览摘要的人工批准")
    approve.add_argument("plan_file", type=Path)
    send = sub.add_parser("send-plan", help="发送已批准且未变化的草稿计划")
    send.add_argument("plan_file", type=Path)
    send.add_argument("--approval-digest", required=True)
    send.add_argument("--confirm", action="store_true")
    resolve = sub.add_parser("resolve-operation", help="人工核对后解除中断状态")
    resolve.add_argument("idempotency_key")
    resolve.add_argument("--status", required=True, choices=("sent", "failed:manual_review"))
    return parser


def _run_cli(args: argparse.Namespace) -> int:
    state = LocalState(args.state_dir)
    if args.command == "env":
        try:
            import msal  # type: ignore  # noqa: F401
            msal_status = "available"
        except ImportError:
            msal_status = "missing"
        try:
            from google.auth.transport.requests import Request  # noqa: F401
            from google.oauth2.credentials import Credentials  # noqa: F401
            from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
            google_status = "available"
        except ImportError:
            google_status = "missing"
        _json_output({
            "python": sys.version.split()[0],
            "msal": msal_status,
            "google_oauth": google_status,
            "google_credentials_configured": bool(state.load_config().get("google_credentials_path")),
            "keychain": "available" if KeychainStore().available() else "unavailable",
            "state_dir": str(state.root),
        })
        return 0 if msal_status == "available" and google_status == "available" and KeychainStore().available() else 1
    if args.command == "set-client-id":
        state.save_client_id(args.client_id)
        _json_output({"ok": True, "client_id_saved": True})
        return 0
    if args.command == "set-google-credentials":
        state.save_google_credentials_path(args.credentials_json)
        _json_output({"ok": True, "google_credentials_saved": True})
        return 0
    if args.command == "accounts":
        _json_output(state.accounts())
        return 0
    if args.command == "authorize":
        auth = MsalAuth(state) if args.provider == "outlook" else GoogleAuth(state)
        record = auth.authorize(args.account_key)
        _json_output({"ok": True, "account": record})
        return 0
    if args.command == "remove":
        normalized = normalize_email(args.account_key)
        service = KEYCHAIN_SERVICE if args.provider == "outlook" else GMAIL_KEYCHAIN_SERVICE
        KeychainStore(service).delete(normalized)
        state.remove_account(normalized, args.provider)
        _json_output({"ok": True, "provider": args.provider, "removed": normalized})
        return 0

    workbench = Workbench(state)
    try:
        if args.command == "verify":
            _json_output(workbench.client(args.provider, args.account_key).get_me())
        elif args.command == "inbox":
            _json_output(workbench.client(args.provider, args.account_key).list_messages(args.since, args.top))
        elif args.command == "draft":
            _json_output(workbench.create_draft(args.account_key, args.to, args.subject, _read_body(args.body_file), args.provider))
        elif args.command == "reply-draft":
            _json_output(workbench.create_reply_draft(args.account_key, args.message_id, _read_body(args.body_file), args.provider))
        elif args.command == "check-replies":
            _json_output(workbench.check_replies(args.account_key, args.since, args.top, args.provider))
        elif args.command == "followups":
            _json_output(workbench.ledger.followup_candidates(args.account_key, args.as_of, args.provider))
        elif args.command == "import-contacts":
            with args.csv_file.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    workbench.ledger.upsert_contact(row)
            _json_output({"ok": True, "imported": True})
        elif args.command == "approve-plan":
            preview = preview_from_plan(load_plan(args.plan_file))
            _json_output({"ok": True, "digest": workbench.approve_plan(preview), "account_key": preview.account_key, "item_count": len(preview.items)})
        elif args.command == "send-plan":
            preview = preview_from_plan(load_plan(args.plan_file))
            _json_output(workbench.send_plan(preview, args.approval_digest, args.confirm))
        elif args.command == "resolve-operation":
            workbench.ledger.resolve_in_flight(args.idempotency_key, args.status)
            _json_output({"ok": True, "idempotency_key": args.idempotency_key, "status": args.status})
        else:
            raise WorkbenchError("未知命令")
    finally:
        workbench.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _run_cli(_make_parser().parse_args(argv))
    except WorkbenchError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
