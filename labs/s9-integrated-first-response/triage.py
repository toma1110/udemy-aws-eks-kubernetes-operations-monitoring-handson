from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCENARIO_ORDER = [
    "pending-profile-selector",
    "crashloop-application-config",
    "access-denied-irsa",
    "forbidden-rbac",
    "cloudwatch-application-error",
]

RESTORATION_KEYS = {
    "pending-profile-selector": ("pod_compute_label", "pod_phase", "ready"),
    "crashloop-application-config": ("app_mode", "ready", "restart_increasing", "expected_log"),
    "access-denied-irsa": ("service_account_annotation", "verification_service_account", "aws_read_result", "access_denied"),
    "forbidden-rbac": ("binding_subject", "can_i_get_configmaps", "can_i_delete_configmaps"),
    "cloudwatch-application-error": ("application_endpoint", "ready", "request_result", "new_same_error_count"),
}

CORRECTION_CODES = {
    "pending-profile-selector": "restore-compute-label",
    "crashloop-application-config": "restore-app-mode",
    "access-denied-irsa": "restore-irsa-annotation",
    "forbidden-rbac": "restore-rolebinding-subject",
    "cloudwatch-application-error": "restore-application-endpoint",
}

ESCALATION_CODES = {
    "pending-profile-selector": "escalate-profile-or-shared-change",
    "crashloop-application-config": "escalate-unknown-or-shared-config",
    "access-denied-irsa": "escalate-iam-or-shared-identity-change",
    "forbidden-rbac": "escalate-cluster-scope-or-auth-change",
    "cloudwatch-application-error": "escalate-shared-endpoint-or-log-path-change",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _diagnose_pending(evidence: dict[str, Any], baseline: dict[str, Any]) -> str:
    _require(evidence["pod_phase"] == "Pending", "pending scenario must have Pending phase")
    _require(evidence["namespace"] == evidence["profile_namespace"], "namespace must match")
    _require(evidence["pod_compute_label"] != evidence["profile_compute_label"], "label mismatch missing")
    _require(not evidence["container_started"], "Pending container must not be treated as started")
    return "fargate-profile-selector-mismatch"


def _diagnose_crashloop(evidence: dict[str, Any], baseline: dict[str, Any]) -> str:
    _require(evidence["waiting_reason"] == "CrashLoopBackOff", "CrashLoopBackOff missing")
    _require(evidence["last_exit_code"] == 42, "expected application exit code missing")
    _require("APP_MODE=broken" in evidence["previous_log"], "previous log does not bind the config")
    _require(evidence["image_pulled"] and evidence["scheduled"], "earlier startup stages not excluded")
    return "application-config-mismatch"


def _diagnose_access_denied(evidence: dict[str, Any], baseline: dict[str, Any]) -> str:
    _require(evidence["access_target"] == "AWS API", "AWS API target missing")
    _require(evidence["aws_error_code"] == "AccessDenied", "AccessDenied missing")
    _require(not evidence["service_account_annotation_matches_baseline"], "IRSA annotation mismatch missing")
    _require(evidence["trust_matches_baseline"], "trust must be checked separately")
    _require(evidence["policy_allows_expected_read"], "policy must be checked separately")
    return "irsa-service-account-annotation-mismatch"


def _diagnose_forbidden(evidence: dict[str, Any], baseline: dict[str, Any]) -> str:
    _require(evidence["access_target"] == "Kubernetes API", "Kubernetes API target missing")
    _require(evidence["authenticated"], "Forbidden case must be authenticated")
    _require(evidence["api_error_code"] == "Forbidden", "Forbidden missing")
    _require(evidence["can_i_get_configmaps"] == "no", "denied can-i result missing")
    _require(evidence["binding_subject"] != evidence["expected_binding_subject"], "binding mismatch missing")
    return "rbac-rolebinding-subject-mismatch"


def _diagnose_cloudwatch(evidence: dict[str, Any], baseline: dict[str, Any]) -> str:
    _require(evidence["pod_phase"] == "Running", "application error pod must be Running")
    _require(evidence["container_request_id"] == evidence["cloudwatch_request_id"], "request IDs differ")
    _require(evidence["container_error_code"] == evidence["cloudwatch_error_code"], "error codes differ")
    _require(evidence["namespace"] == evidence["cloudwatch_namespace"], "namespaces differ")
    _require(evidence["pod"] == evidence["cloudwatch_pod"], "pods differ")
    _require(evidence["container"] == evidence["cloudwatch_container"], "containers differ")
    _require(
        evidence["application_endpoint"] != baseline["application_endpoint"],
        "application endpoint does not differ from the safe baseline",
    )
    return "application-endpoint-config-mismatch"


DIAGNOSERS = {
    "pending-profile-selector": _diagnose_pending,
    "crashloop-application-config": _diagnose_crashloop,
    "access-denied-irsa": _diagnose_access_denied,
    "forbidden-rbac": _diagnose_forbidden,
    "cloudwatch-application-error": _diagnose_cloudwatch,
}


def _restored_to_baseline(scenario: dict[str, Any]) -> bool:
    scenario_id = scenario["id"]
    baseline = scenario.get("baseline")
    observed = scenario.get("post_restoration")
    if not isinstance(baseline, dict) or not isinstance(observed, dict):
        return False
    keys = RESTORATION_KEYS[scenario_id]
    if any(key not in baseline or key not in observed for key in keys):
        return False
    return all(observed[key] == baseline[key] for key in keys)


def analyze(document: dict[str, Any]) -> dict[str, Any]:
    _require(document.get("schema_version") == 1, "schema_version must be 1")
    scenarios = document.get("scenarios")
    _require(isinstance(scenarios, list), "scenarios must be a list")
    ids = [item.get("id") for item in scenarios]
    _require(ids == SCENARIO_ORDER, "scenario population or order differs")

    results = []
    for scenario in scenarios:
        scenario_id = scenario["id"]
        _require(scenario.get("known_difference_count") == 1, f"{scenario_id}: one known difference is required")
        _require(bool(scenario.get("escalation_if")), f"{scenario_id}: escalation condition missing")
        baseline = scenario.get("baseline")
        _require(isinstance(baseline, dict), f"{scenario_id}: safe baseline missing")
        diagnosis = DIAGNOSERS[scenario_id](scenario["evidence"], baseline)
        restored = _restored_to_baseline(scenario)
        results.append(
            {
                "id": scenario_id,
                "lecture_id": scenario["lecture_id"],
                "diagnosis": diagnosis,
                "safe_action": scenario["safe_action"],
                "normalization_evidence": scenario.get("post_restoration"),
                "restored_to_baseline": restored,
                "escalation_if": scenario["escalation_if"],
            }
        )
    return {"scenario_count": len(results), "results": results, "restoration_complete": all(r["restored_to_baseline"] for r in results)}


def validate_learner_answers(report: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    _require(answers.get("schema_version") == 1, "answer schema_version must be 1")
    submitted = answers.get("answers")
    _require(isinstance(submitted, list), "answers must be a list")
    ids = [item.get("id") for item in submitted]
    _require(ids == SCENARIO_ORDER, "answer population or order differs")
    diagnoses = {item["id"]: item["diagnosis"] for item in report["results"]}
    scenario_results = []
    for answer in submitted:
        scenario_id = answer["id"]
        checks = {
            "diagnosis": answer.get("diagnosis") == diagnoses[scenario_id],
            "one_difference_correction": answer.get("correction") == CORRECTION_CODES[scenario_id],
            "normalization_evidence": answer.get("normalization_fields") == list(RESTORATION_KEYS[scenario_id]),
            "escalation_decision": answer.get("escalation") == ESCALATION_CODES[scenario_id],
        }
        scenario_results.append({"id": scenario_id, "passed": all(checks.values()), "checks": checks})
    return {"passed": all(item["passed"] for item in scenario_results), "scenario_results": scenario_results}


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# 固定データ診断結果", "", "| 順序 | Scenario | 原因候補 | 安全な次の行動 |", "| --- | --- | --- | --- |"]
    for index, item in enumerate(report["results"], 1):
        lines.append(f"| {index} | `{item['id']}` | `{item['diagnosis']}` | {item['safe_action']} |")
    lines.extend(["", f"- scenario_count: {report['scenario_count']}", f"- restoration_complete: {str(report['restoration_complete']).lower()}"])
    if "learner_result" in report:
        lines.append(f"- learner_answers_passed: {str(report['learner_result']['passed']).lower()}")
        for item in report["learner_result"]["scenario_results"]:
            lines.append(f"  - {item['id']}: {'pass' if item['passed'] else 'review-required'}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze the deterministic Section 9 first-response fixtures.")
    parser.add_argument("fixture", type=Path)
    parser.add_argument(
        "--answers",
        type=Path,
        required=True,
        help="Learner-produced diagnosis and recovery decisions in JSON format.",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = analyze(json.loads(args.fixture.read_text(encoding="utf-8")))
    answers = json.loads(args.answers.read_text(encoding="utf-8"))
    report["learner_result"] = validate_learner_answers(report, answers)
    if args.format == "markdown":
        print(render_markdown(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["learner_result"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
