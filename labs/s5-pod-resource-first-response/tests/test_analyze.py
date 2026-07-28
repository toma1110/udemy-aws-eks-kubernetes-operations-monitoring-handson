import hashlib
import json
import shutil
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

    def copied_fixtures(self, target: Path) -> None:
        shutil.copytree(analyze.DEFAULT_FIXTURES, target, dirs_exist_ok=True)

    def repin(self, target: Path, name: str) -> None:
        manifest_path = target / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][name] = hashlib.sha256((target / name).read_bytes()).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_complete_result_matches_expected(self):
        expected = json.loads(analyze.EXPECTED.read_text(encoding="utf-8"))
        self.assertEqual(self.result, expected)

    def test_pending_signals_are_distinct(self):
        pending = [
            item["signal"] for item in self.result["findings"]
            if item["category"] == "Pending"
        ]
        self.assertEqual(
            pending,
            ["capacity", "taint/toleration", "nodeSelector/affinity"],
        )

    def test_crashloop_signals_are_distinct(self):
        crash = [
            item["signal"] for item in self.result["findings"]
            if item["category"] == "CrashLoopBackOff"
        ]
        self.assertEqual(crash, ["application failure", "OOMKilled", "liveness probe"])

    def test_every_finding_has_evidence_hypothesis_and_next_check(self):
        for finding in self.result["findings"]:
            with self.subTest(pod=finding["pod"]):
                self.assertGreaterEqual(len(finding["evidence"]), 2)
                self.assertTrue(finding["initial_hypothesis"])
                self.assertTrue(finding["next_check"])

    def test_unsupported_causes_are_not_findings(self):
        signals = {item["signal"] for item in self.result["findings"]}
        self.assertNotIn("PVC", signals)
        self.assertNotIn("image pull", signals)
        self.assertEqual(len(self.result["unsupported_causes"]), 2)

    def test_fixture_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.copied_fixtures(target)
            with (target / "events.json").open("a", encoding="utf-8") as stream:
                stream.write(" ")
            with self.assertRaisesRegex(analyze.EvidenceError, "hash mismatch"):
                analyze.analyze(target)

    def test_unmanifested_fixture_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.copied_fixtures(target)
            (target / "extra.txt").write_text("unexpected\n", encoding="utf-8")
            with self.assertRaisesRegex(analyze.EvidenceError, "population mismatch"):
                analyze.analyze(target)

    def test_cross_namespace_event_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.copied_fixtures(target)
            name = "events.json"
            document = json.loads((target / name).read_text(encoding="utf-8"))
            document["items"][0]["involvedObject"]["namespace"] = "other"
            (target / name).write_text(
                json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            self.repin(target, name)
            with self.assertRaisesRegex(analyze.EvidenceError, "FailedScheduling Pod event"):
                analyze.analyze(target)

    def test_cross_resource_event_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.copied_fixtures(target)
            name = "events.json"
            document = json.loads((target / name).read_text(encoding="utf-8"))
            document["items"][3]["involvedObject"]["kind"] = "Deployment"
            (target / name).write_text(
                json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            self.repin(target, name)
            with self.assertRaisesRegex(analyze.EvidenceError, "BackOff Pod event"):
                analyze.analyze(target)

    def test_unknown_assigned_node_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.copied_fixtures(target)
            name = "get-pods.json"
            document = json.loads((target / name).read_text(encoding="utf-8"))
            document["items"][0]["status"]["node"] = "missing-node"
            (target / name).write_text(
                json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            self.repin(target, name)
            with self.assertRaisesRegex(analyze.EvidenceError, "unknown assigned Node"):
                analyze.analyze(target)

    def test_pending_capacity_memory_request_is_required(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.copied_fixtures(target)
            name = "describe-pending-capacity.json"
            document = json.loads((target / name).read_text(encoding="utf-8"))
            document["spec"]["resources"]["requests"]["memory"] = "4Gi"
            (target / name).write_text(
                json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            self.repin(target, name)
            with self.assertRaisesRegex(analyze.EvidenceError, "memory request mismatch"):
                analyze.analyze(target)

    def test_restart_count_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.copied_fixtures(target)
            name = "describe-crashloop-oom.json"
            document = json.loads((target / name).read_text(encoding="utf-8"))
            document["status"]["restartCount"] = 99
            (target / name).write_text(
                json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            self.repin(target, name)
            with self.assertRaisesRegex(analyze.EvidenceError, "restart count mismatch"):
                analyze.analyze(target)

    def test_oom_reason_and_exit_code_are_required(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.copied_fixtures(target)
            name = "describe-crashloop-oom.json"
            document = json.loads((target / name).read_text(encoding="utf-8"))
            document["status"]["lastState"]["exitCode"] = 1
            (target / name).write_text(
                json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            self.repin(target, name)
            with self.assertRaisesRegex(analyze.EvidenceError, "termination evidence"):
                analyze.analyze(target)

    def test_probe_event_is_required(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.copied_fixtures(target)
            name = "events.json"
            document = json.loads((target / name).read_text(encoding="utf-8"))
            document["items"][5]["message"] = "Liveness probe failed."
            (target / name).write_text(
                json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            self.repin(target, name)
            with self.assertRaisesRegex(analyze.EvidenceError, "probe evidence"):
                analyze.analyze(target)

    def test_all_fixture_json_is_parseable(self):
        for path in analyze.DEFAULT_FIXTURES.glob("*.json"):
            with self.subTest(path=path.name):
                json.loads(path.read_text(encoding="utf-8"))

    def test_readme_has_one_cloudshell_learning_route(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        self.assertIn("コース共通のCloudFormationテンプレートで作成したEKSクラスタ", readme)
        self.assertIn("AWS Management Console", readme)
        self.assertIn("AWS CloudShell", readme)
        self.assertNotIn("Route A", readme)
        self.assertNotIn("Route B", readme)

    def test_investigation_steps_use_exact_read_only_commands(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        required = [
            "kubectl get pods -n udemy4-c010-s5-20260724 -o wide",
            "kubectl describe pod udemy4-c010-s5-20260724-pending-capacity",
            "kubectl logs udemy4-c010-s5-20260724-crashloop-app",
            "kubectl get events -n udemy4-c010-s5-20260724",
        ]
        for command in required:
            with self.subTest(command=command):
                self.assertIn(command, readme)

        prohibited_commands = [
            "kubectl apply ",
            "kubectl create ",
            "kubectl edit ",
            "kubectl patch ",
            "kubectl set ",
            "kubectl scale ",
            "kubectl rollout restart ",
            "kubectl delete ",
        ]
        for command in prohibited_commands:
            with self.subTest(command=command):
                self.assertNotIn(command, readme)

    def test_official_sources_and_permission_boundary_are_present(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "https://docs.aws.amazon.com/eks/latest/userguide/view-kubernetes-resources.html",
            readme,
        )
        self.assertIn(
            "https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-metrics-EKS.html",
            readme,
        )
        self.assertIn("IAM", readme)
        self.assertIn("権限を変更せず", readme)

    def test_cost_and_cleanup_cover_the_shared_environment(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        self.assertIn("約USD 0.97/6時間", readme)
        self.assertIn("実請求", readme)
        self.assertIn('"$S5_DIR/scripts/cleanup-section.sh"', readme)
        self.assertIn('"$COMMON_EKS_DIR/scripts/delete.sh"', readme)


if __name__ == "__main__":
    unittest.main()
