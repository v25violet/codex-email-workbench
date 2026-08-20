#!/usr/bin/env python3
"""Mock-only behavioral tests for the local Outlook helper."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import base64
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import outlook_workbench as ow  # noqa: E402


class FakeKeychain:
    def __init__(self, usable: bool = True) -> None:
        self.usable = usable
        self.values: dict[str, str] = {}

    def available(self) -> bool:
        return self.usable

    def load(self, account_key: str) -> str | None:
        return self.values.get(account_key)

    def save(self, account_key: str, serialized_cache: str) -> None:
        if not self.usable:
            raise ow.WorkbenchError("keychain unavailable")
        self.values[account_key] = serialized_cache

    def delete(self, account_key: str) -> None:
        self.values.pop(account_key, None)

    def reference(self, account_key: str) -> str:
        return f"fake-keychain:{account_key}"


class FakeAuth:
    def access_token(self, account_key: str) -> str:
        return f"fixture-credential-{account_key}"


class FakeGraph:
    def __init__(self, account_key: str) -> None:
        self.account_key = account_key
        self.sent: list[str] = []
        self.messages: dict[str, dict[str, object]] = {}
        self.inbox: list[dict[str, object]] = []

    def get_me(self) -> dict[str, str]:
        return {"id": f"id-{self.account_key}", "mail": self.account_key, "userPrincipalName": self.account_key}

    def get_message(self, message_id: str) -> dict[str, object]:
        return self.messages[message_id]

    def send_draft(self, message_id: str) -> None:
        self.sent.append(message_id)

    def list_messages(self, since: str | None = None, top: int = 50) -> list[dict[str, object]]:
        return self.inbox[:top]


class FakeMsalCache:
    def __init__(self) -> None:
        self.has_state_changed = True

    def serialize(self) -> str:
        return json.dumps({"cache": "memory-only"})

    def deserialize(self, value: str) -> None:
        if "access_token" in value or "refresh_token" in value:
            raise AssertionError("test cache must not receive token-shaped data")


class FakeMsalApp:
    def __init__(self, client_id: str, authority: str, token_cache: FakeMsalCache) -> None:
        self.cache = token_cache

    def acquire_token_interactive(self, scopes: list[str], prompt: str) -> dict[str, str]:
        return {"access_token": "fixture-credential"}

    def get_accounts(self) -> list[dict[str, str]]:
        return [{"username": "one@example.test"}]

    def acquire_token_silent(self, scopes: list[str], account: dict[str, str]) -> dict[str, str]:
        return {"access_token": "fixture-credential"}


class FakeMsal:
    SerializableTokenCache = FakeMsalCache
    PublicClientApplication = FakeMsalApp


class FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self.payload


class QueueOpener:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.requests: list[object] = []

    def __call__(self, request: object, timeout: int) -> FakeHttpResponse:
        self.requests.append(request)
        return FakeHttpResponse(self.responses.pop(0))


def raw_message_payload(to: str, subject: str, body: str, sender: str = "sender@example.test") -> str:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = "<message-1@example.test>"
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")


class OutlookWorkbenchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state = ow.LocalState(Path(self.temp.name) / "state")
        self.state.save_client_id("public-client-id")
        self.accounts = ("one@example.test", "two@example.test")
        for account in self.accounts:
            self.state.save_account({
                "account_key": account,
                "mail": account,
                "graph_id": f"id-{account}",
                "keychain_ref": f"fake-keychain:{account}",
            })
        self.graphs = {account: FakeGraph(account) for account in self.accounts}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def workbench(self) -> ow.Workbench:
        return ow.Workbench(
            self.state,
            auth=FakeAuth(),
            graph_factory=lambda account: self.graphs[account],
        )

    def test_each_operation_routes_to_explicit_account(self) -> None:
        workbench = self.workbench()
        try:
            self.assertEqual(workbench.graph("one@example.test").get_me()["mail"], "one@example.test")
            self.assertEqual(workbench.graph("two@example.test").get_me()["mail"], "two@example.test")
            with self.assertRaises(ow.WorkbenchError):
                workbench.graph("missing@example.test")
        finally:
            workbench.close()

    def test_authorization_verifies_me_and_rejects_duplicate(self) -> None:
        keychain = FakeKeychain()
        auth = ow.MsalAuth(self.state, keychain=keychain, msal_module=FakeMsal)
        with patch.object(ow.GraphClient, "get_me", return_value={"id": "id-one", "mail": "one@example.test"}):
            with self.assertRaises(ow.WorkbenchError):
                auth.authorize("one@example.test")
        self.state.remove_account("one@example.test")
        with patch.object(ow.GraphClient, "get_me", return_value={"id": "id-one", "mail": "one@example.test"}):
            record = auth.authorize("one@example.test")
        self.assertEqual(record["mail"], "one@example.test")
        self.assertIn("one@example.test", keychain.values)
        with self.assertRaises(ow.WorkbenchError):
            auth.authorize("one@example.test")

    def test_wrong_me_is_never_saved(self) -> None:
        keychain = FakeKeychain()
        auth = ow.MsalAuth(self.state, keychain=keychain, msal_module=FakeMsal)
        with patch.object(ow.GraphClient, "get_me", return_value={"id": "id-two", "mail": "two@example.test"}):
            with self.assertRaises(ow.AccountMismatchError):
                auth.authorize("new@example.test")
        self.assertNotIn("new@example.test", keychain.values)

    def test_keychain_unavailable_stops_authorization(self) -> None:
        auth = ow.MsalAuth(self.state, keychain=FakeKeychain(usable=False), msal_module=FakeMsal)
        with self.assertRaises(ow.WorkbenchError):
            auth.authorize("new@example.test")

    def test_approval_change_and_unapproved_send_are_blocked(self) -> None:
        workbench = self.workbench()
        try:
            item = {
                "idempotency_key": "camp-1:contact-1:0",
                "draft_id": "draft-1",
                "contact_id": "contact-1",
                "to": ["recipient@example.test"],
                "subject": "Subject",
                "body": "Body",
            }
            workbench.ledger.upsert_contact({
                "contact_id": "contact-1",
                "campaign_id": "camp-1",
                "step": "0",
                "email": "recipient@example.test",
                "name": "Recipient",
                "account_key": "one@example.test",
                "status": "approved",
                "do_not_contact": "false",
            })
            self.graphs["one@example.test"].messages["draft-1"] = {
                "subject": "Subject",
                "body": {"contentType": "Text", "content": "Body"},
                "toRecipients": [{"emailAddress": {"address": "recipient@example.test"}}],
            }
            preview = ow.Preview("one@example.test", "batch-1", (item,), "one every 30 seconds")
            with self.assertRaises(ow.ApprovalError):
                workbench.send_plan(preview, "not-approved", confirm=True)
            digest = workbench.approve_plan(preview)
            changed = ow.Preview("one@example.test", "batch-1", (dict(item, body="Changed"),), preview.cadence)
            with self.assertRaises(ow.ApprovalError):
                workbench.send_plan(changed, digest, confirm=True)
            with self.assertRaises(ow.ApprovalError):
                workbench.send_plan(preview, digest, confirm=False)
            self.assertEqual(workbench.send_plan(preview, digest, confirm=True), [{
                "idempotency_key": "camp-1:contact-1:0",
                "status": "sent",
            }])
            self.assertEqual(self.graphs["one@example.test"].sent, ["draft-1"])
            self.assertEqual(workbench.send_plan(preview, digest, confirm=True), [{
                "idempotency_key": "camp-1:contact-1:0",
                "status": "already_sent",
            }])
        finally:
            workbench.close()

    def test_sent_item_is_not_sent_twice_and_in_flight_blocks(self) -> None:
        ledger = ow.Ledger(self.state.ledger_path)
        try:
            ledger.begin_send("key-1", "one@example.test", "contact-1")
            with self.assertRaises(ow.DuplicateSendError):
                ledger.begin_send("key-1", "one@example.test", "contact-1")
            ledger.mark_sent("key-1", "draft-1")
            with self.assertRaises(ow.DuplicateSendError):
                ledger.begin_send("key-1", "one@example.test", "contact-1")
        finally:
            ledger.close()

    def test_reply_detection_removes_followup_candidate(self) -> None:
        workbench = self.workbench()
        try:
            workbench.ledger.upsert_contact({
                "contact_id": "contact-1",
                "campaign_id": "camp-1",
                "step": "1",
                "email": "recipient@example.test",
                "name": "Recipient",
                "account_key": "one@example.test",
                "status": "sent",
                "last_sent_at": "2026-08-18T00:00:00+00:00",
                "next_followup_at": "2026-08-19T00:00:00+00:00",
                "do_not_contact": "false",
            })
            self.graphs["one@example.test"].inbox.append({
                "id": "reply-1",
                "conversationId": "thread-1",
                "subject": "Re: Subject",
                "receivedDateTime": "2026-08-19T00:00:00+00:00",
                "from": {"emailAddress": {"address": "recipient@example.test"}},
                "isRead": False,
            })
            messages = workbench.check_replies("one@example.test", since="2026-08-18T00:00:00+00:00")
            self.assertEqual(messages[0]["matched_contacts"], 1)
            self.assertEqual(workbench.ledger.followup_candidates("one@example.test", "2026-08-20T00:00:00+00:00"), [])
        finally:
            workbench.close()

    def test_runtime_state_does_not_contain_token_value(self) -> None:
        workbench = self.workbench()
        try:
            workbench.ledger.save_approval("digest", "one@example.test", "batch", 1)
        finally:
            workbench.close()
        for path in Path(self.temp.name).rglob("*"):
            if path.is_file():
            self.assertNotIn(b"fixture-credential", path.read_bytes())

    def test_gmail_client_uses_profile_drafts_and_reply_thread_without_network(self) -> None:
        profile_opener = QueueOpener([{"emailAddress": "gmail-one@example.test"}])
        gmail = ow.GmailClient("fixture-gmail-credential", opener=profile_opener)
        self.assertEqual(gmail.get_me()["mail"], "gmail-one@example.test")

        draft_opener = QueueOpener([{"id": "draft-1", "message": {"id": "message-1"}}])
        gmail = ow.GmailClient("fixture-gmail-credential", opener=draft_opener)
        draft = gmail.create_draft(["recipient@example.test"], "Subject", "Body")
        self.assertEqual(draft["id"], "draft-1")
        sent_request = draft_opener.requests[0]
        sent_body = json.loads(sent_request.data.decode("utf-8"))  # type: ignore[attr-defined]
        encoded = sent_body["message"]["raw"]
        padding = "=" * (-len(encoded) % 4)
        self.assertIn("recipient@example.test", base64.urlsafe_b64decode((encoded + padding).encode("ascii")).decode("utf-8"))

        reply_opener = QueueOpener([
            {"id": "message-1", "threadId": "thread-1", "payload": {"body": {"data": raw_message_payload("gmail-one@example.test", "Subject", "Original")}}},
            {"id": "draft-reply", "message": {"id": "message-reply"}},
        ])
        gmail = ow.GmailClient("fixture-gmail-credential", opener=reply_opener)
        reply = gmail.create_reply_draft("message-1", "Reply body")
        self.assertEqual(reply["id"], "draft-reply")
        reply_body = json.loads(reply_opener.requests[1].data.decode("utf-8"))  # type: ignore[attr-defined]
        self.assertEqual(reply_body["message"]["threadId"], "thread-1")

    def test_multiple_gmail_accounts_are_explicitly_isolated(self) -> None:
        first = "gmail-one@example.test"
        second = "gmail-two@example.test"
        self.state.save_account({"provider": "gmail", "account_key": first, "mail": first})
        self.state.save_account({"provider": "gmail", "account_key": second, "mail": second})
        clients = {
            first: FakeGraph(first),
            second: FakeGraph(second),
        }
        workbench = ow.Workbench(
            self.state,
            client_factory=lambda provider, account: clients[account],
        )
        try:
            self.assertEqual(workbench.client("gmail", first).get_me()["mail"], first)
            self.assertEqual(workbench.client("gmail", second).get_me()["mail"], second)
            with self.assertRaises(ow.WorkbenchError):
                workbench.client("gmail", "missing@example.test")
        finally:
            workbench.close()

    def test_contact_ledger_isolated_by_provider(self) -> None:
        ledger = ow.Ledger(Path(self.temp.name) / "provider-ledger.sqlite3")
        try:
            common = {
                "contact_id": "same-contact",
                "campaign_id": "same-campaign",
                "step": "0",
                "email": "recipient@example.test",
                "name": "Recipient",
                "status": "approved",
                "do_not_contact": "false",
                "next_followup_at": "2026-08-20T00:00:00+00:00",
            }
            ledger.upsert_contact(dict(common, provider="outlook", account_key="outlook@example.test"))
            ledger.upsert_contact(dict(common, provider="gmail", account_key="gmail@example.test"))
            self.assertEqual(ledger.contact_status("outlook@example.test", "same-contact", "outlook"), "approved")
            self.assertEqual(ledger.contact_status("gmail@example.test", "same-contact", "gmail"), "approved")
            self.assertEqual(len(ledger.followup_candidates("outlook@example.test", "2026-08-21T00:00:00+00:00", "outlook")), 1)
            self.assertEqual(len(ledger.followup_candidates("gmail@example.test", "2026-08-21T00:00:00+00:00", "gmail")), 1)
        finally:
            ledger.close()

    def test_google_authorization_verifies_me_and_uses_separate_keychain(self) -> None:
        credentials_file = Path(self.temp.name) / "google-desktop-client.json"
        credentials_file.write_text("{}", encoding="utf-8")
        self.state.save_google_credentials_path(credentials_file)

        class FakeGoogleCredentials:
            token = "fixture-gmail-credential"

            def to_json(self) -> str:
                return json.dumps({"token": "fixture-gmail-cache"})

        class FakeFlow:
            @classmethod
            def from_client_secrets_file(cls, path: str, scopes: list[str]) -> "FakeFlow":
                return cls()

            def run_local_server(self, port: int, open_browser: bool) -> FakeGoogleCredentials:
                return FakeGoogleCredentials()

        keychain = FakeKeychain()
        auth = ow.GoogleAuth(
            self.state,
            keychain=keychain,
            google_modules={"InstalledAppFlow": FakeFlow, "Credentials": object, "Request": object},
        )
        with patch.object(ow.GmailClient, "get_me", return_value={"mail": "gmail-one@example.test"}):
            record = auth.authorize("gmail-one@example.test")
        self.assertEqual(record["provider"], "gmail")
        self.assertIn("gmail-one@example.test", keychain.values)


if __name__ == "__main__":
    unittest.main()
