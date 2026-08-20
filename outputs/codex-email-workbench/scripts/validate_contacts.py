#!/usr/bin/env python3
"""Validate an outreach contacts CSV without modifying it."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


REQUIRED_COLUMNS = (
    "contact_id",
    "email",
    "name",
    "company",
    "owner",
    "provider",
    "account_key",
    "campaign_id",
    "step",
    "status",
    "do_not_contact",
)
ALLOWED_STATUSES = {
    "draft",
    "approved",
    "sent",
    "replied_positive",
    "replied_neutral",
    "replied_negative",
    "bounced",
    "unsubscribed",
    "paused",
    "failed",
    "completed",
}
TRUE_VALUES = {"1", "true", "yes", "y", "是"}
FALSE_VALUES = {"0", "false", "no", "n", "否", ""}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normal(value: object) -> str:
    return str(value or "").strip()


def _normalized_email(value: object) -> str:
    return _normal(value).casefold()


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]], list[dict[str, object]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows: list[dict[str, str]] = []
        errors: list[dict[str, object]] = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                errors.append({"row": row_number, "code": "extra_columns"})
                row = {key: value for key, value in row.items() if key is not None}
            rows.append({key: _normal(value) for key, value in row.items() if key is not None})
    return columns, rows, errors


def validate(path: Path) -> tuple[dict[str, object], int]:
    result: dict[str, object] = {
        "file": str(path),
        "rows": 0,
        "valid_rows": 0,
        "invalid_rows": 0,
        "duplicate_email_count": 0,
        "duplicate_unique_key_count": 0,
        "owner_conflict_count": 0,
        "suppressed_count": 0,
        "status_counts": {},
        "errors": [],
    }
    if not path.is_file():
        result["errors"] = [{"code": "file_not_found"}]
        result["ok"] = False
        return result, 2

    try:
        columns, rows, read_errors = _read_rows(path)
    except (OSError, UnicodeError, csv.Error) as exc:
        result["errors"] = [{"code": "read_error", "detail": type(exc).__name__}]
        result["ok"] = False
        return result, 2

    result["rows"] = len(rows)
    errors: list[dict[str, object]] = list(read_errors)
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in columns]
    if missing_columns:
        errors.append({"code": "missing_columns", "columns": missing_columns})
        result["errors"] = errors
        result["invalid_rows"] = len(rows)
        result["ok"] = False
        return result, 2

    email_rows: defaultdict[str, list[int]] = defaultdict(list)
    key_rows: defaultdict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    owner_rows: defaultdict[tuple[str, str, str], dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    status_counts: Counter[str] = Counter()

    for row_number, row in enumerate(rows, start=2):
        email = _normalized_email(row.get("email"))
        if email:
            email_rows[email].append(row_number)
        provider = _normal(row.get("provider")).casefold()
        key = (provider, _normal(row.get("contact_id")), _normal(row.get("campaign_id")), _normal(row.get("step")))
        if all(key):
            key_rows[key].append(row_number)
        owner_key = (provider, _normal(row.get("contact_id")), _normal(row.get("campaign_id")))
        owner = _normal(row.get("owner"))
        if all(owner_key) and owner:
            owner_rows[owner_key][owner].add(row_number)
        status_counts[_normal(row.get("status"))] += 1

    duplicate_emails = {value: row_numbers for value, row_numbers in email_rows.items() if len(row_numbers) > 1}
    duplicate_keys = {key: row_numbers for key, row_numbers in key_rows.items() if len(row_numbers) > 1}
    owner_conflicts = {
        key: owners for key, owners in owner_rows.items() if len(owners) > 1
    }
    result["duplicate_email_count"] = sum(len(rows_for_value) for rows_for_value in duplicate_emails.values())
    result["duplicate_unique_key_count"] = sum(len(rows_for_value) for rows_for_value in duplicate_keys.values())
    result["owner_conflict_count"] = sum(
        len(row_number)
        for owners in owner_conflicts.values()
        for row_number in owners.values()
    )

    invalid_row_numbers: set[int] = set()
    for row_number, row in enumerate(rows, start=2):
        row_errors: list[str] = []
        missing = [column for column in REQUIRED_COLUMNS if not _normal(row.get(column))]
        if missing:
            row_errors.append("missing_required")
        email = _normalized_email(row.get("email"))
        if email and not EMAIL_RE.fullmatch(email):
            row_errors.append("invalid_email")
        account_key = _normalized_email(row.get("account_key"))
        if account_key and not EMAIL_RE.fullmatch(account_key):
            row_errors.append("invalid_account_key")
        provider = _normal(row.get("provider")).casefold()
        if provider and provider not in {"outlook", "gmail"}:
            row_errors.append("invalid_provider")
        status = _normal(row.get("status"))
        if status:
            if status not in ALLOWED_STATUSES:
                row_errors.append("invalid_status")
        if _normal(row.get("step")):
            try:
                step = int(_normal(row.get("step")))
                if step < 0 or step > 3:
                    row_errors.append("step_out_of_range")
            except ValueError:
                row_errors.append("invalid_step")
        dnc = _normal(row.get("do_not_contact")).casefold()
        if dnc not in TRUE_VALUES | FALSE_VALUES:
            row_errors.append("invalid_do_not_contact")
        if email in duplicate_emails:
            row_errors.append("duplicate_email")
        provider = _normal(row.get("provider")).casefold()
        key = (provider, _normal(row.get("contact_id")), _normal(row.get("campaign_id")), _normal(row.get("step")))
        if all(key) and key in duplicate_keys:
            row_errors.append("duplicate_unique_key")
        owner_key = (provider, _normal(row.get("contact_id")), _normal(row.get("campaign_id")))
        if all(owner_key) and owner_key in owner_conflicts:
            row_errors.append("owner_conflict")

        if dnc in TRUE_VALUES:
            result["suppressed_count"] = int(result["suppressed_count"]) + 1
        if row_errors:
            invalid_row_numbers.add(row_number)
            for code in sorted(set(row_errors)):
                errors.append({"row": row_number, "code": code})

    result["valid_rows"] = len(rows) - len(invalid_row_numbers)
    result["invalid_rows"] = len(invalid_row_numbers)
    result["status_counts"] = dict(sorted(status_counts.items()))
    result["errors"] = errors
    result["ok"] = not errors
    return result, 0 if result["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path)
    args = parser.parse_args()
    result, code = validate(args.csv_file)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
