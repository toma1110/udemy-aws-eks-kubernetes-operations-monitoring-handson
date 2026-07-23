import json
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

import analyze


class AnalyzeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = analyze.load_logs()

    def test_fixture_inventory(self):
        self.assertEqual(10, len(self.events))

    def test_namespace_pod_time_filter_is_inclusive(self):
        result = analyze.filter_logs(
            self.events,
            namespace="training",
            pod="checkout-7d9f",
            start="2026-07-24T10:00:00Z",
            end="2026-07-24T10:06:00Z",
        )
        self.assertEqual(5, result["count"])
        self.assertEqual("2026-07-24T10:00:00Z", result["events"][0]["timestamp"])
        self.assertEqual("2026-07-24T10:06:00Z", result["events"][-1]["timestamp"])

    def test_error_timeline_is_ordered_and_namespace_scoped(self):
        result = analyze.filter_logs(
            self.events,
            namespace="training",
            start="2026-07-24T10:00:00Z",
            end="2026-07-24T10:06:00Z",
            errors_only=True,
        )
        self.assertEqual(3, result["count"])
        self.assertEqual(
            ["2026-07-24T10:02:00Z", "2026-07-24T10:03:00Z", "2026-07-24T10:04:00Z"],
            [event["timestamp"] for event in result["events"]],
        )
        self.assertTrue(all(event["namespace"] == "training" for event in result["events"]))

    def test_pod_filter_excludes_other_replica(self):
        result = analyze.filter_logs(
            self.events,
            namespace="training",
            pod="checkout-7d9f",
            errors_only=True,
        )
        self.assertTrue(all(event["pod"] == "checkout-7d9f" for event in result["events"]))
        self.assertNotIn("inventory lookup failed", [event["message"] for event in result["events"]])

    def test_start_after_end_fails_closed(self):
        with self.assertRaisesRegex(analyze.LogDataError, "start must not be after end"):
            analyze.filter_logs(
                self.events,
                start="2026-07-24T10:06:00Z",
                end="2026-07-24T10:00:00Z",
            )

    def test_timezone_is_required(self):
        with self.assertRaisesRegex(analyze.LogDataError, "include a timezone"):
            analyze.filter_logs(self.events, start="2026-07-24T10:00:00")

    def test_invalid_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "bad.jsonl"
            fixture.write_text(json.dumps({"timestamp": "2026-07-24T10:00:00Z"}) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(analyze.LogDataError, "must contain exactly"):
                analyze.load_logs(fixture)

    def test_expected_results_match(self):
        self.assertTrue(analyze.check_expected())


if __name__ == "__main__":
    unittest.main()
