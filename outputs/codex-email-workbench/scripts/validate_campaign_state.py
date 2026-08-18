#!/usr/bin/env python3
"""Validate campaign state and follow-up invariants in a CSV."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path


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
TERMINAL_STATUSES = {
    "replied_positive",
    "replied_neutral",
    "replied_negative",
    "bounced",
    "unsubscribed",
    "paused",
    "completed",
}
REQUIRED_COLUMNS = (
    "contact_id",
    "campaign_id",
    "step",
    "status",
    "last_sent_at",
    "last_reply_at",
    "next_followup_at",
    "do_not_contact",
    "stop_reason",
)


def _normal(value: object) -> str:
    return str(value or "").strip()


def _parse_datetime(value: str) -> datetime | date | None:
    if not value:
        return None
    candidate = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            return None


def _comparable(value: datetime | date) -> datetime:
    """Return a naive UTC-ish value so date/datetime comparisons are safe."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    return datetime.combine(value, datetime.min.time())


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
        "terminal_with_followup_count": 0,
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

    key_rows: defaultdict[tuple[str, str, str], list[int]] = defaultdict(list)
    for row_number, row in enumerate(rows, start=2):
        key = (_normal(row.get("contact_id")), _normal(row.get("campaign_id")), _normal(row.get("step")))
        if all(key):
            key_rows[key].append(row_number)
    duplicate_keys = {key: row_numbers for key, row_numbers in key_rows.items() if len(row_numbers) > 1}

    invalid_row_numbers: set[int] = set()
    for row_number, row in enumerate(rows, start=2):
        row_errors: list[str] = []
        # Timestamp and stop-reason cells are intentionally blank for many active states.
        value_required = {"contact_id", "campaign_id", "step", "status", "do_not_contact"}
        missing = [column for column in value_required if not _normal(row.get(column))]
        if missing:
            row_errors.append("missing_required")

        key = (_normal(row.get("contact_id")), _normal(row.get("campaign_id")), _normal(row.get("step")))
        if all(key) and key in duplicate_keys:
            row_errors.append("duplicate_unique_key")

        status = _normal(row.get("status"))
        if status not in ALLOWED_STATUSES:
            row_errors.append("invalid_status")

        step_value = _normal(row.get("step"))
        if step_value:
            try:
                step = int(step_value)
                if step < 0 or step > 3:
                    row_errors.append("step_out_of_range")
            except ValueError:
                row_errors.append("invalid_step")

        parsed_dates: dict[str, datetime | date] = {}
        for field in ("last_sent_at", "last_reply_at", "next_followup_at"):
            value = _normal(row.get(field))
            if value:
                parsed = _parse_datetime(value)
                if parsed is None:
                    row_errors.append(f"invalid_{field}")
                else:
                    parsed_dates[field] = parsed

        next_followup = _normal(row.get("next_followup_at"))
        if status in TERMINAL_STATUSES and next_followup:
            row_errors.append("terminal_with_followup")
            result["terminal_with_followup_count"] = int(result["terminal_with_followup_count"]) + 1
        dnc = _normal(row.get("do_not_contact")).casefold()
        if dnc in {"1", "true", "yes", "y", "是"} and next_followup:
            row_errors.append("suppressed_with_followup")
        if status == "sent" and not _normal(row.get("last_sent_at")):
            row_errors.append("sent_without_last_sent_at")
        if status in {"draft", "approved"} and _normal(row.get("last_sent_at")):
            row_errors.append("unsent_status_with_last_sent_at")
        if "last_sent_at" in parsed_dates and "next_followup_at" in parsed_dates:
            if _comparable(parsed_dates["next_followup_at"]) < _comparable(parsed_dates["last_sent_at"]):
                row_errors.append("followup_before_last_sent")
        if "last_reply_at" in parsed_dates and "next_followup_at" in parsed_dates:
            if _comparable(parsed_dates["next_followup_at"]) < _comparable(parsed_dates["last_reply_at"]):
                row_errors.append("followup_before_last_reply")

        if row_errors:
            invalid_row_numbers.add(row_number)
            for code in sorted(set(row_errors)):
                errors.append({"row": row_number, "code": code})

    result["valid_rows"] = len(rows) - len(invalid_row_numbers)
    result["invalid_rows"] = len(invalid_row_numbers)
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
