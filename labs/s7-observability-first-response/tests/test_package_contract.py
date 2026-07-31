import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

import analyze


class PackageContractTests(unittest.TestCase):
    def test_learner_readme_is_cloudshell_first_and_complete(self):
        text = (PACKAGE / "README.md").read_text(encoding="utf-8")
        for token in (
            "AWS CloudShell",
            "ap-northeast-1",
            "aws --version",
            "kubectl version --client",
            'df -h "$HOME"',
            "Region ごとに 1 GB",
            "## 費用",
            "## Troubleshooting",
            "## 9. Cleanup",
            "最大 6 時間",
            "summary.json",
            "effective_log_collection",
            "not-determined",
        ):
            self.assertIn(token, text)
        self.assertNotIn("```powershell", text.lower())
    def test_common_foundation_is_available(self):
        common = PACKAGE.parent / "common-eks"
        self.assertTrue((common / "README.md").is_file())
        self.assertTrue((common / "scripts" / "bind-current-identity.sh").is_file())
        self.assertTrue((common / "scripts" / "delete.sh").is_file())
        self.assertTrue((common / "scripts" / "post-guard-verify.sh").is_file())

    def test_scripts_are_read_only_except_exact_private_cleanup(self):
        scripts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((PACKAGE / "scripts").glob("*.sh"))
            if path.name != "cleanup-local-evidence.sh"
        )
        for token in (
            "create-addon",
            "update-addon",
            "delete-addon",
            "attach-role-policy",
            "put-role-policy",
            "create-pod-identity-association",
            "kubectl apply",
            "kubectl create",
            "kubectl patch",
            "kubectl delete",
            "logs delete-log-group",
        ):
            self.assertNotIn(token, scripts)
        cleanup = (PACKAGE / "scripts" / "cleanup-local-evidence.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('rm -rf -- "$evidence_dir"', cleanup)
        self.assertNotIn("aws ", cleanup)
        self.assertNotIn("kubectl ", cleanup)

    def test_capture_covers_every_s7_claim_layer(self):
        capture = (PACKAGE / "scripts" / "capture-observations.sh").read_text(
            encoding="utf-8"
        )
        for token in (
            "eks describe-addon",
            "get pods",
            "get daemonsets",
            "get serviceaccounts",
            "get configmaps",
            "get events",
            "get nodes",
            "cloudwatch list-metrics",
            "logs describe-log-groups",
            "AccessDenied",
            "timeout",
            "configuration error",
            "agent-logs.json",
            "agent_logs",
            "read-denied",
            "no-target",
            "container_logs_override",
            "otel_container_insights_override",
            "classic_container_insights_override",
            "legacy_enhanced_observability_override",
            "effective_log_collection",
        ):
            self.assertIn(token, capture)
        expected = json.loads(
            (PACKAGE / "expected-results.json").read_text(encoding="utf-8")
        )
        self.assertEqual(expected["hands_on_lectures"], ["s7-l2", "s7-l3"])
        self.assertTrue(expected["read_only"])

    def test_all_external_scripts_revalidate_exact_target(self):
        for name in ("preflight.sh", "capture-observations.sh"):
            text = (PACKAGE / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("assert_s7_target", text)
        common = (PACKAGE / "scripts" / "common.sh").read_text(encoding="utf-8")
        for token in (
            "record_current_sts_identity",
            "get_expected_stack_binding",
            "assert_exact_kubernetes_context",
            "udemy4-c010-common-20260724",
            "ap-northeast-1",
        ):
            self.assertIn(token, common)
        self.assertLess(
            common.index("record_current_sts_identity"),
            common.index("assert_preflight true"),
        )

    def test_retained_identity_rejects_current_account_mismatch(self):
        command = r'''
set -euo pipefail
source "labs/s7-observability-first-response/scripts/common.sh"
PRIVATE_TEST_DIR="$(mktemp -d)"
trap 'rm -rf -- "$PRIVATE_TEST_DIR"' EXIT
export CURRENT_STS_IDENTITY_FILE="$PRIVATE_TEST_DIR/current-sts-identity.json"
RETAINED_ACCOUNT="$(printf '1%.0s' {1..12})"
CURRENT_ACCOUNT="$(printf '2%.0s' {1..12})"
printf '{"Account":"%s","Arn":"arn:aws:%s::%s:role/retained","UserId":"retained-user"}\n' \
  "$RETAINED_ACCOUNT" "iam" "$RETAINED_ACCOUNT" >"$CURRENT_STS_IDENTITY_FILE"
cp "$CURRENT_STS_IDENTITY_FILE" "$PRIVATE_TEST_DIR/before.json"
printf '{"Account":"%s","Arn":"arn:aws:%s::%s:assumed-role/current/session","UserId":"current-user"}\n' \
  "$CURRENT_ACCOUNT" "sts" "$CURRENT_ACCOUNT" >"$PRIVATE_TEST_DIR/current.json"
aws_json() { cat "$PRIVATE_TEST_DIR/current.json"; }
jq() {
  if [[ "$1" == "-e" ]]; then
    cat >/dev/null
    return 0
  fi
  if [[ "$1" == "-S" ]]; then
    cat
    return 0
  fi
  return 97
}
if record_current_sts_identity >/dev/null 2>&1; then
  exit 91
fi
cmp -s "$CURRENT_STS_IDENTITY_FILE" "$PRIVATE_TEST_DIR/before.json"
'''
        command = command.replace("\r", "")
        result = subprocess.run(
            ["bash"],
            cwd=PACKAGE.parents[1],
            input=command.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode, 0, result.stderr.decode("utf-8", errors="replace")
        )

    def test_cleanup_removes_empty_root_and_allows_retained_rebinding(self):
        command = r'''
set -euo pipefail
PACKAGE_ROOT="labs/s7-observability-first-response"
TEST_HOME="$(mktemp -d)"
trap 'rm -rf -- "$TEST_HOME"' EXIT
export HOME="$TEST_HOME"
export PRIVATE_EXECUTION_DIR="$HOME/eks-monitoring-private/c010-s4/current-run"
export CURRENT_STS_IDENTITY_FILE="$PRIVATE_EXECUTION_DIR/current-sts-identity.json"
export S7_RUN_ID="20260731T083000Z-a1b2c3d4"
export S7_EVIDENCE_ROOT="$PRIVATE_EXECUTION_DIR/s7-observations"
export S7_EVIDENCE_DIR="$S7_EVIDENCE_ROOT/observations-$S7_RUN_ID"
mkdir -p "$S7_EVIDENCE_DIR/raw" "$S7_EVIDENCE_DIR/status"
ACCOUNT="$(printf '3%.0s' {1..12})"
printf '{"Account":"%s","Arn":"arn:aws:%s::%s:role/current","UserId":"current-user"}\n' \
  "$ACCOUNT" "iam" "$ACCOUNT" >"$CURRENT_STS_IDENTITY_FILE"
mkdir "$S7_EVIDENCE_ROOT/unexpected-sibling"
if bash "$PACKAGE_ROOT/scripts/cleanup-local-evidence.sh" >/dev/null 2>&1; then
  exit 91
fi
[[ -d "$S7_EVIDENCE_DIR" && -d "$S7_EVIDENCE_ROOT/unexpected-sibling" ]]
rmdir "$S7_EVIDENCE_ROOT/unexpected-sibling"
bash "$PACKAGE_ROOT/scripts/cleanup-local-evidence.sh" >/dev/null
[[ ! -e "$S7_EVIDENCE_ROOT" ]]
mapfile -d '' PRIVATE_ENTRIES < <(
  find "$PRIVATE_EXECUTION_DIR" -mindepth 1 -maxdepth 1 -print0
)
[[ "${#PRIVATE_ENTRIES[@]}" == "1" ]]
[[ "$(realpath "${PRIVATE_ENTRIES[0]}")" == "$(realpath "$CURRENT_STS_IDENTITY_FILE")" ]]

aws() { cat "$CURRENT_STS_IDENTITY_FILE"; }
jq() {
  if [[ "$1" == "-e" ]]; then
    cat >/dev/null
    return 0
  fi
  if [[ "$1" == "-S" ]]; then
    cat
    return 0
  fi
  return 97
}
source "labs/common-eks/scripts/bind-current-identity.sh"
[[ "$PRIVATE_EXECUTION_DIR" == "$HOME/eks-monitoring-private/c010-s4/current-run" ]]
[[ "$CURRENT_STS_IDENTITY_FILE" == "$PRIVATE_EXECUTION_DIR/current-sts-identity.json" ]]
'''
        result = subprocess.run(
            ["bash"],
            cwd=PACKAGE.parents[1],
            input=command.replace("\r", "").encode("utf-8"),
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode, 0, result.stderr.decode("utf-8", errors="replace")
        )

    def test_fixture_diagnoses_addon_absence_without_false_live_proof(self):
        doc = analyze.load_document(PACKAGE / "fixtures" / "addon-missing.json")
        summary = analyze.build_summary(doc)
        self.assertIn("confirm-addon-installation", summary["next_checks"])
        self.assertIn(
            "inspect-enhanced-observability-and-time-range", summary["next_checks"]
        )
        self.assertIn(
            "inspect-region-agent-log-configuration-and-iam", summary["next_checks"]
        )
        self.assertFalse(summary["live_proof"])

    def test_fixture_separates_scheduling_iam_and_configuration(self):
        doc = analyze.load_document(PACKAGE / "fixtures" / "agent-unhealthy.json")
        summary = analyze.build_summary(doc)
        self.assertIn("inspect-addon-health", summary["next_checks"])
        self.assertIn(
            "inspect-pod-status-events-and-previous-logs", summary["next_checks"]
        )
        self.assertIn(
            "inspect-node-taints-capacity-and-tolerations", summary["next_checks"]
        )
        self.assertIn("inspect-iam-or-pod-identity", summary["next_checks"])
        self.assertEqual(summary["agent_pods"]["waiting_reasons"], ["CrashLoopBackOff"])
        self.assertEqual(
            summary["configuration"]["effective_log_collection"],
            "explicitly-disabled",
        )
        self.assertIn(
            "inspect-agent-log-collection-configuration", summary["next_checks"]
        )

    def test_running_phase_waiting_states_trigger_pod_diagnostics(self):
        for name, reason in (
            ("running-crashloopbackoff.json", "CrashLoopBackOff"),
            ("running-imagepullbackoff.json", "ImagePullBackOff"),
        ):
            with self.subTest(name=name):
                doc = analyze.load_document(PACKAGE / "fixtures" / name)
                self.assertEqual(doc["agent_pods"]["non_running"], 0)
                summary = analyze.build_summary(doc)
                self.assertEqual(summary["agent_pods"]["waiting_reasons"], [reason])
                self.assertIn(
                    "inspect-pod-status-events-and-previous-logs",
                    summary["next_checks"],
                )

    def test_fixture_separates_log_gap_from_healthy_metrics(self):
        doc = analyze.load_document(
            PACKAGE / "fixtures" / "healthy-agent-log-gap.json"
        )
        summary = analyze.build_summary(doc)
        self.assertNotIn(
            "inspect-enhanced-observability-and-time-range", summary["next_checks"]
        )
        self.assertIn(
            "inspect-region-agent-log-configuration-and-iam", summary["next_checks"]
        )
        self.assertIn(
            "inspect-dns-egress-or-cloudwatch-endpoint", summary["next_checks"]
        )
        self.assertTrue(
            summary["configuration"]["agent_log_pipeline_config_present"]
        )
        self.assertEqual(
            summary["configuration"]["container_logs_override"], "enabled"
        )
        self.assertEqual(
            summary["configuration"]["approach_interpretation"]["otel"],
            "explicitly-disabled",
        )
        self.assertEqual(
            summary["configuration"]["approach_interpretation"]["classic_root"],
            "explicitly-enabled",
        )
        self.assertEqual(
            summary["configuration"]["approach_interpretation"]["configured_mode_signal"],
            "classic-only-configured",
        )

    def test_unobserved_agent_logs_do_not_become_negative_signals(self):
        cases = (
            ("agent-logs-unavailable.json", "unavailable", "retry-agent-log-capture"),
            (
                "agent-logs-read-denied.json",
                "read-denied",
                "confirm-agent-log-read-permission",
            ),
            ("agent-logs-no-target.json", "no-target", "confirm-agent-log-target"),
        )
        for name, reason, expected_check in cases:
            with self.subTest(name=name):
                doc = analyze.load_document(PACKAGE / "fixtures" / name)
                summary = analyze.build_summary(doc)
                self.assertEqual(
                    summary["agent_logs"],
                    {"observed": False, "reason": reason},
                )
                self.assertIn(expected_check, summary["next_checks"])
                self.assertNotIn("inspect-iam-or-pod-identity", summary["next_checks"])
                self.assertNotIn(
                    "inspect-dns-egress-or-cloudwatch-endpoint",
                    summary["next_checks"],
                )
                self.assertFalse(summary["agent_signals"]["access_denied"])
                self.assertFalse(summary["agent_signals"]["network_error"])
                self.assertFalse(summary["agent_signals"]["configuration_error"])

        contradictory = analyze.load_document(
            PACKAGE / "fixtures" / "agent-logs-read-denied.json"
        )
        contradictory["agent_signals"]["access_denied"] = True
        with self.assertRaises(ValueError):
            analyze.build_summary(contradictory)

    def test_configuration_presence_does_not_imply_effective_enablement(self):
        doc = analyze.load_document(PACKAGE / "fixtures" / "addon-missing.json")
        summary = analyze.build_summary(doc)
        self.assertFalse(summary["addon"]["configuration_values_present"])
        self.assertEqual(
            summary["configuration"]["effective_log_collection"], "not-observed"
        )
        doc = analyze.load_document(
            PACKAGE / "fixtures" / "running-crashloopbackoff.json"
        )
        summary = analyze.build_summary(doc)
        self.assertTrue(
            summary["configuration"]["agent_log_pipeline_config_present"]
        )
        self.assertEqual(
            summary["configuration"]["effective_log_collection"], "not-determined"
        )
        self.assertEqual(
            summary["configuration"]["approach_interpretation"]["otel"],
            "disabled-by-default",
        )
        self.assertEqual(
            summary["configuration"]["approach_interpretation"]["classic_root"],
            "default-dependent",
        )
        self.assertEqual(
            summary["configuration"]["approach_interpretation"]["configured_mode_signal"],
            "default-dependent",
        )

    def test_otel_only_dual_publish_and_legacy_compatibility(self):
        otel = analyze.build_summary(
            analyze.load_document(PACKAGE / "fixtures" / "otel-only.json")
        )
        self.assertEqual(
            otel["configuration"]["approach_interpretation"]["otel"],
            "explicitly-enabled",
        )
        self.assertEqual(
            otel["configuration"]["approach_interpretation"]["classic_root"],
            "explicitly-disabled",
        )
        self.assertEqual(
            otel["configuration"]["approach_interpretation"]["configured_mode_signal"],
            "otel-only-configured",
        )

        dual = analyze.build_summary(
            analyze.load_document(PACKAGE / "fixtures" / "dual-publish.json")
        )
        self.assertEqual(
            dual["configuration"]["approach_interpretation"]["configured_mode_signal"],
            "dual-publish-configured",
        )

        legacy = analyze.build_summary(
            analyze.load_document(PACKAGE / "fixtures" / "agent-unhealthy.json")
        )
        self.assertEqual(
            legacy["configuration"]["approach_interpretation"]["legacy_nested"],
            "explicitly-enabled",
        )
        self.assertEqual(
            legacy["configuration"]["approach_interpretation"]["configured_mode_signal"],
            "legacy-classic-configured",
        )

    def test_analyzer_rejects_wrong_target_and_sensitive_summary(self):
        doc = analyze.load_document(PACKAGE / "fixtures" / "addon-missing.json")
        doc["region"] = "us-east-1"
        with self.assertRaises(ValueError):
            analyze.build_summary(doc)
        account = "123" * 4
        with self.assertRaises(ValueError):
            analyze.reject_sensitive(
                {"principal": f"arn:aws:iam::{account}:role/private"}
            )

    def test_analyzer_cli_is_deterministic(self):
        fixture = PACKAGE / "fixtures" / "agent-unhealthy.json"
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "first.json"
            second = Path(temp) / "second.json"
            for output in (first, second):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(PACKAGE / "analyze.py"),
                        "--input",
                        str(fixture),
                        "--output",
                        str(output),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
