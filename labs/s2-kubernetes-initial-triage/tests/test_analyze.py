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
        cls.result = analyze.analyze()

    def test_expected_result_matches(self):
        self.assertEqual(self.result, analyze.load_json(analyze.EXPECTED))

    def test_all_nodes_ready(self):
        self.assertEqual(self.result["cluster_overview"]["not_ready_nodes"], [])

    def test_abnormal_candidates_are_deterministically_sorted(self):
        self.assertEqual(
            self.result["cluster_overview"]["abnormal_candidates"],
            ["training/crashloop-worker", "training/oom-reporter", "training/pending-api"],
        )

    def test_pending_uses_scheduling_event(self):
        finding = self.result["findings"][0]
        self.assertEqual(finding["category"], "Pending")
        self.assertIn("FailedScheduling", finding["evidence"][2])

    def test_crashloop_uses_previous_log(self):
        finding = self.result["findings"][1]
        self.assertEqual(finding["category"], "CrashLoopBackOff")
        self.assertIn("starting worker", finding["evidence"][1])
        self.assertIn("APP_MODE", finding["evidence"][2])

    def test_oom_uses_last_termination_reason(self):
        finding = self.result["findings"][2]
        self.assertEqual(finding["category"], "OOMKilled")
        self.assertIn("OOMKilled", finding["evidence"][1])
        self.assertIn("memory pressure", finding["evidence"][3])

    @staticmethod
    def copied_fixtures(target: Path) -> None:
        for source in analyze.DEFAULT_FIXTURES.iterdir():
            (target / source.name).write_bytes(source.read_bytes())

    @staticmethod
    def repin_manifest(target: Path, changed_name: str) -> None:
        manifest_path = target / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][changed_name] = analyze.sha256_file(target / changed_name)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_cross_namespace_describe_substitution_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.copied_fixtures(target)
            name = "describe-pending-api.json"
            document = json.loads((target / name).read_text(encoding="utf-8"))
            document["metadata"]["namespace"] = "default"
            (target / name).write_text(
                json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            self.repin_manifest(target, name)
            with self.assertRaisesRegex(analyze.EvidenceError, "absent from get-pods"):
                analyze.analyze(target)

    def test_cross_resource_event_substitution_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.copied_fixtures(target)
            name = "events.json"
            document = json.loads((target / name).read_text(encoding="utf-8"))
            document["items"][0]["involvedObject"]["kind"] = "Deployment"
            (target / name).write_text(
                json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            self.repin_manifest(target, name)
            with self.assertRaisesRegex(analyze.EvidenceError, "Pod event"):
                analyze.analyze(target)

    def test_each_finding_has_next_check(self):
        self.assertTrue(all(item["next_check"] for item in self.result["findings"]))

    def test_fixture_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.copied_fixtures(target)
            with (target / "get-nodes.json").open("a", encoding="utf-8") as stream:
                stream.write(" ")
            with self.assertRaisesRegex(analyze.EvidenceError, "hash mismatch"):
                analyze.analyze(target)

    def test_fixture_json_is_parseable(self):
        for path in analyze.DEFAULT_FIXTURES.glob("*.json"):
            with self.subTest(path=path.name):
                json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
