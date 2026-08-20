#!/usr/bin/env python3
"""Behavioral tests for the two standard-library validators."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SCRIPTS = ROOT / "scripts"


def run_validator(script_name: str, fixture_name: str) -> tuple[int, dict[str, object]]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / script_name), str(FIXTURES / fixture_name)],
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - clearer failure message
        raise AssertionError(f"validator did not emit JSON: {completed.stdout!r}\n{completed.stderr}") from exc
    return completed.returncode, payload


class ValidatorTests(unittest.TestCase):
    def test_normal_contacts_pass(self) -> None:
        code, payload = run_validator("validate_contacts.py", "normal_contacts.csv")
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["rows"], 2)
        self.assertEqual(payload["valid_rows"], 2)
        self.assertEqual(payload["suppressed_count"], 0)

    def test_invalid_contacts_are_reported_without_mutation(self) -> None:
        path = FIXTURES / "invalid_contacts.csv"
        before = path.read_bytes()
        code, payload = run_validator("validate_contacts.py", path.name)
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["suppressed_count"], 1)
        self.assertGreaterEqual(payload["duplicate_email_count"], 2)
        error_codes = {item["code"] for item in payload["errors"] if "code" in item}
        self.assertTrue({"invalid_email", "duplicate_unique_key", "invalid_provider", "invalid_status"} <= error_codes)
        self.assertEqual(before, path.read_bytes())

    def test_normal_campaign_state_passes(self) -> None:
        code, payload = run_validator("validate_campaign_state.py", "normal_campaign_state.csv")
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["valid_rows"], 2)

    def test_invalid_campaign_state_stops_followup(self) -> None:
        code, payload = run_validator("validate_campaign_state.py", "invalid_campaign_state.csv")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertGreaterEqual(payload["terminal_with_followup_count"], 1)
        error_codes = {item["code"] for item in payload["errors"] if "code" in item}
        self.assertTrue(
            {
                "terminal_with_followup",
                "sent_without_last_sent_at",
                "step_out_of_range",
                "followup_before_last_sent",
            }
            <= error_codes
        )


if __name__ == "__main__":
    unittest.main()
