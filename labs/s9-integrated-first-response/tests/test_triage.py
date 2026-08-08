from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("s9_triage", ROOT / "triage.py")
assert SPEC and SPEC.loader
TRIAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRIAGE)


class IntegratedFirstResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads((ROOT / "fixtures" / "scenarios.json").read_text(encoding="utf-8"))
        cls.expected = json.loads((ROOT / "expected-results.json").read_text(encoding="utf-8"))
        cls.report = TRIAGE.analyze(cls.fixture)

    def test_population_order_and_diagnoses(self) -> None:
        self.assertEqual(self.expected["scenario_order"], [item["id"] for item in self.report["results"]])
        self.assertEqual(
            self.expected["diagnoses"],
            {item["id"]: item["diagnosis"] for item in self.report["results"]},
        )
        self.assertEqual(5, self.report["scenario_count"])

    def test_each_scenario_has_one_difference_and_restoration(self) -> None:
        for scenario in self.fixture["scenarios"]:
            self.assertEqual(1, scenario["known_difference_count"], scenario["id"])
            self.assertEqual(
                self.expected["restoration_required_fields"][scenario["id"]],
                list(TRIAGE.RESTORATION_KEYS[scenario["id"]]),
            )
            self.assertTrue(scenario["baseline"], scenario["id"])
            self.assertTrue(scenario["post_restoration"], scenario["id"])
            self.assertTrue(scenario["escalation_if"], scenario["id"])
        self.assertTrue(self.report["restoration_complete"])

    def test_every_missing_or_failed_postcondition_prevents_complete_restoration(self) -> None:
        for index, scenario in enumerate(self.fixture["scenarios"]):
            scenario_id = scenario["id"]
            for key in TRIAGE.RESTORATION_KEYS[scenario_id]:
                missing = copy.deepcopy(self.fixture)
                del missing["scenarios"][index]["post_restoration"][key]
                self.assertFalse(TRIAGE.analyze(missing)["restoration_complete"], f"missing {scenario_id}.{key}")

                failed = copy.deepcopy(self.fixture)
                baseline_value = failed["scenarios"][index]["baseline"][key]
                if isinstance(baseline_value, bool):
                    failed_value = not baseline_value
                elif isinstance(baseline_value, int):
                    failed_value = baseline_value + 1
                else:
                    failed_value = f"failed-{baseline_value}"
                failed["scenarios"][index]["post_restoration"][key] = failed_value
                self.assertFalse(TRIAGE.analyze(failed)["restoration_complete"], f"failed {scenario_id}.{key}")

    def _correct_answers(self) -> dict:
        return {
            "schema_version": 1,
            "answers": [
                {
                    "id": scenario_id,
                    "diagnosis": self.expected["diagnoses"][scenario_id],
                    "correction": self.expected["corrections"][scenario_id],
                    "normalization_fields": self.expected["restoration_required_fields"][scenario_id],
                    "escalation": self.expected["escalations"][scenario_id],
                }
                for scenario_id in self.expected["scenario_order"]
            ],
        }

    def test_learner_answers_require_all_four_decisions_for_every_scenario(self) -> None:
        correct = self._correct_answers()
        result = TRIAGE.validate_learner_answers(self.report, correct)
        self.assertTrue(result["passed"])
        for index, scenario_id in enumerate(self.expected["scenario_order"]):
            for field in ("diagnosis", "correction", "normalization_fields", "escalation"):
                wrong = copy.deepcopy(correct)
                wrong["answers"][index][field] = [] if field == "normalization_fields" else "wrong-choice"
                checked = TRIAGE.validate_learner_answers(self.report, wrong)
                self.assertFalse(checked["passed"], f"{scenario_id}.{field}")

    def test_learner_template_contains_no_prepopulated_pass_or_restoration_flag(self) -> None:
        template = json.loads((ROOT / "templates" / "learner-decisions.json").read_text(encoding="utf-8"))
        for answer in template["answers"]:
            self.assertEqual("", answer["diagnosis"])
            self.assertEqual("", answer["correction"])
            self.assertEqual([], answer["normalization_fields"])
            self.assertEqual("", answer["escalation"])
            self.assertNotIn("restored_to_baseline", answer)

    def test_cli_accepts_complete_learner_file_and_rejects_wrong_choice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            answer_path = Path(directory) / "learner-decisions.json"
            answer_path.write_text(json.dumps(self._correct_answers(), ensure_ascii=False), encoding="utf-8")
            command = [
                sys.executable,
                str(ROOT / "triage.py"),
                str(ROOT / "fixtures" / "scenarios.json"),
                "--answers",
                str(answer_path),
                "--format",
                "json",
            ]
            accepted = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            self.assertTrue(json.loads(accepted.stdout)["learner_result"]["passed"])

            wrong = self._correct_answers()
            wrong["answers"][0]["diagnosis"] = "wrong-choice"
            answer_path.write_text(json.dumps(wrong, ensure_ascii=False), encoding="utf-8")
            rejected = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
            self.assertEqual(1, rejected.returncode)
            self.assertFalse(json.loads(rejected.stdout)["learner_result"]["passed"])

    def test_cli_requires_answers_before_revealing_diagnosis(self) -> None:
        command = [
            sys.executable,
            str(ROOT / "triage.py"),
            str(ROOT / "fixtures" / "scenarios.json"),
            "--format",
            "json",
        ]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertNotIn("fargate-profile-selector-mismatch", result.stderr)

    def test_documented_pre_answer_workflow_does_not_expose_answers(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        pre_answer = readme.split("## 3. 自分の診断と対応を入力する", 1)[0]
        self.assertNotIn("python triage.py", pre_answer)
        self.assertNotIn("fargate-profile-selector-mismatch", pre_answer)
        analyzer_lines = [line for line in readme.splitlines() if line.startswith("python triage.py")]
        self.assertTrue(analyzer_lines)
        self.assertIn("--answers learner-decisions.json", analyzer_lines[0])

    def test_aws_and_kubernetes_permission_paths_are_distinct(self) -> None:
        by_id = {item["id"]: item for item in self.fixture["scenarios"]}
        self.assertEqual("AWS API", by_id["access-denied-irsa"]["evidence"]["access_target"])
        self.assertEqual("Kubernetes API", by_id["forbidden-rbac"]["evidence"]["access_target"])
        self.assertFalse(by_id["access-denied-irsa"]["evidence"]["pod_execution_role_used_by_application"])

    def test_cloudwatch_record_is_bound_to_same_workload(self) -> None:
        scenario = self.fixture["scenarios"][-1]
        evidence = scenario["evidence"]
        self.assertEqual(evidence["container_request_id"], evidence["cloudwatch_request_id"])
        self.assertEqual(evidence["container_error_code"], evidence["cloudwatch_error_code"])
        self.assertEqual(evidence["namespace"], evidence["cloudwatch_namespace"])
        self.assertEqual(evidence["pod"], evidence["cloudwatch_pod"])
        self.assertEqual(evidence["container"], evidence["cloudwatch_container"])
        self.assertNotEqual(evidence["application_endpoint"], scenario["baseline"]["application_endpoint"])

    def test_cloudwatch_diagnosis_rejects_endpoint_equal_to_safe_baseline(self) -> None:
        matching = copy.deepcopy(self.fixture)
        scenario = matching["scenarios"][-1]
        scenario["evidence"]["application_endpoint"] = scenario["baseline"]["application_endpoint"]
        with self.assertRaisesRegex(ValueError, "does not differ from the safe baseline"):
            TRIAGE.analyze(matching)

    def test_readme_has_safety_cost_cleanup_and_not_run_boundary(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for value in (
            "料金と時間上限",
            "固定データルートはAWSを使わない",
            "教材用の固定データ",
            "--answers learner-decisions.json",
            "learner_answers_passed: true",
            "自己申告fieldは回答として受理されません",
            "--answers`を省略した起動は受理されません",
            "s10-l1-cleanup",
            "変更せず停止",
            "account ID、credential、Secret値",
            "[s10-l1-cleanup](../s10-cleanup/README.md)",
        ):
            self.assertIn(value, readme)
        for internal_wording in ("このrevision", "制作時未実行", "backout", "IAM owner", "exact role", "exact値", "期待after"):
            self.assertNotIn(internal_wording, readme)

    def test_fixture_contains_no_account_id_or_local_user_path(self) -> None:
        text = (ROOT / "fixtures" / "scenarios.json").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\b\d{12}\b", text))
        self.assertNotIn("C:\\Users\\", text)
        self.assertNotIn("/Users/", text)

    def test_inventory_matches_current_bytes(self) -> None:
        inventory = ROOT / "artifact-inventory.sha256"
        self.assertTrue(inventory.exists())
        for line in inventory.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            expected_hash, relative = line.split("  ", 1)
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(expected_hash, actual, relative)


if __name__ == "__main__":
    unittest.main()
