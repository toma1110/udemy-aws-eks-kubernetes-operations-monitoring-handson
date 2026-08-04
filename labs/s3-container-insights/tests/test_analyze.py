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

    def copied_fixture(self, target: Path) -> Path:
        fixture_dir = target / "fixtures"
        shutil.copytree(PACKAGE / "fixtures", fixture_dir)
        return fixture_dir / "scenarios.json"

    def repin(self, fixture: Path) -> None:
        manifest_path = fixture.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][fixture.name] = hashlib.sha256(fixture.read_bytes()).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def mutate(self, fixture: Path, callback) -> None:
        document = json.loads(fixture.read_text(encoding="utf-8"))
        callback(document)
        fixture.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self.repin(fixture)

    def test_result_matches_expected(self):
        self.assertEqual(self.result, json.loads(analyze.DEFAULT_EXPECTED.read_text(encoding="utf-8")))

    def test_cases_distinguish_collection_gap_and_resource_anomaly(self):
        classes = {item["id"]: item["classification"] for item in self.result["results"]}
        self.assertEqual(
            classes,
            {"collection-gap": "collection_gap", "resource-anomaly": "resource_anomaly"},
        )

    def test_fixture_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = self.copied_fixture(Path(temp))
            fixture.write_text(fixture.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(analyze.ObservationError, "hash mismatch"):
                analyze.analyze(fixture)

    def test_cloudwatch_pod_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = self.copied_fixture(Path(temp))
            self.mutate(
                fixture,
                lambda doc: doc["cases"][0]["cloudwatch"]["target"].update({"pod": "other-pod"}),
            )
            with self.assertRaisesRegex(analyze.ObservationError, "CloudWatch target does not match"):
                analyze.analyze(fixture)

    def test_cloudwatch_window_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = self.copied_fixture(Path(temp))
            self.mutate(
                fixture,
                lambda doc: doc["cases"][0]["cloudwatch"]["window"].update(
                    {"end": "2026-08-05T00:11:00Z"}
                ),
            )
            with self.assertRaisesRegex(analyze.ObservationError, "time window does not match"):
                analyze.analyze(fixture)

    def test_cloudwatch_node_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = self.copied_fixture(Path(temp))
            self.mutate(
                fixture,
                lambda doc: doc["cases"][0]["cloudwatch"]["target"].update(
                    {"node": "other-node"}
                ),
            )
            with self.assertRaisesRegex(analyze.ObservationError, "CloudWatch target does not match"):
                analyze.analyze(fixture)

    def test_kubectl_observation_outside_window_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = self.copied_fixture(Path(temp))
            self.mutate(
                fixture,
                lambda doc: doc["cases"][1]["kubectl"].update(
                    {"observed_at": "2026-08-05T01:11:00Z"}
                ),
            )
            with self.assertRaisesRegex(analyze.ObservationError, "outside the time window"):
                analyze.analyze(fixture)

    def test_missing_data_with_healthy_collection_is_not_called_a_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = self.copied_fixture(Path(temp))
            self.mutate(
                fixture,
                lambda doc: doc["cases"][0]["collection"].update({"ready": 2}),
            )
            result = analyze.analyze(fixture)
            self.assertEqual(result["results"][0]["classification"], "inconclusive")

    def test_high_cpu_without_kubectl_confirmation_is_inconclusive(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = self.copied_fixture(Path(temp))
            self.mutate(
                fixture,
                lambda doc: doc["cases"][1]["kubectl"].update({"signal": "normal"}),
            )
            result = analyze.analyze(fixture)
            self.assertEqual(result["results"][1]["classification"], "inconclusive")

    def test_controller_current_count_is_part_of_collection_health(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = self.copied_fixture(Path(temp))
            self.mutate(
                fixture,
                lambda doc: doc["cases"][1]["collection"].update(
                    {"current": 1, "ready": 1}
                ),
            )
            result = analyze.analyze(fixture)
            self.assertFalse(result["results"][1]["collection_healthy"])
            self.assertEqual(result["results"][1]["classification"], "inconclusive")

    def test_unknown_controller_kind_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = self.copied_fixture(Path(temp))
            self.mutate(
                fixture,
                lambda doc: doc["cases"][0]["collection"].update(
                    {"controller_kind": "UnknownController"}
                ),
            )
            with self.assertRaisesRegex(analyze.ObservationError, "controller kind is unsupported"):
                analyze.analyze(fixture)

    def test_readme_live_commands_are_read_only(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        required = [
            "aws eks describe-addon",
            "kubectl get daemonsets,deployments -n amazon-cloudwatch",
            "kubectl get daemonset <agent-daemonset-name>",
            "kubectl get deployment <agent-deployment-name>",
            "kubectl get pods -n amazon-cloudwatch",
            "kubectl get pods -n \"$NAMESPACE\"",
            "kubectl get pod \"$POD_NAME\"",
            "kubectl top pod \"$POD_NAME\"",
            "kubectl top node \"$NODE_NAME\"",
        ]
        for command in required:
            with self.subTest(command=command):
                self.assertIn(command, readme)
        prohibited = [
            "aws eks update-addon",
            "aws eks create-addon",
            "kubectl apply",
            "kubectl create",
            "kubectl edit",
            "kubectl patch",
            "kubectl delete",
            "kubectl rollout restart",
        ]
        for command in prohibited:
            with self.subTest(command=command):
                self.assertNotIn(command, readme)

    def test_readme_covers_target_time_collection_and_cleanup(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        for term in (
            "Region",
            "Cluster",
            "Namespace",
            "workload",
            "Pod",
            "UTC時間範囲",
            "add-on",
            "Agent Pod",
            ".spec.nodeName",
            "NODE_NAME",
            "必要数／現在数／準備完了数",
            "推測で名前や種類を補いません",
            "フィルターを解除",
            "observation-result.json",
            "このSection自体が作るAWSリソースはありません",
            "../common-eks/README.md",
        ):
            with self.subTest(term=term):
                self.assertIn(term, readme)

    def test_package_inventory(self):
        inventory = json.loads((PACKAGE / "package-inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(inventory["schema"], "s3-package-inventory-v1")
        listed = inventory["files"]
        actual = {
            path.relative_to(PACKAGE).as_posix()
            for path in PACKAGE.rglob("*")
            if path.is_file()
            and path.name != "package-inventory.json"
            and "__pycache__" not in path.parts
        }
        self.assertEqual(set(listed), actual)
        for relative, expected in listed.items():
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256((PACKAGE / relative).read_bytes()).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
