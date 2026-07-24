from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class LiveContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.public_readme = (ROOT.parents[1] / "README.md").read_text(encoding="utf-8")
        cls.common = (ROOT / "scripts/common.ps1").read_text(encoding="utf-8")
        cls.scripts = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted((ROOT / "scripts").glob("*.ps1"))
        )
        cls.workload = (ROOT / "manifests/10-log-workload.yaml").read_text(encoding="utf-8")

    def test_common_directory_and_region_are_exact(self) -> None:
        self.assertIn("labs/common-eks", self.readme)
        self.assertIn('$script:Region = "ap-northeast-1"', self.common)
        self.assertIn('$script:ClusterName = "udemy4-c010-common-20260724"', self.common)

    def test_external_binding_is_fail_closed(self) -> None:
        for token in (
            "AWS_ACCOUNT_ID",
            "STS account does not equal AWS_ACCOUNT_ID",
            "kubectl context must equal the exact common cluster ARN",
            "AccessDenied|Unauthorized|ExpiredToken|InvalidClientToken",
        ):
            self.assertIn(token, self.common)

    def test_workload_is_digest_pinned_and_emits_expected_levels(self) -> None:
        self.assertRegex(self.workload, r"busybox@sha256:[0-9a-f]{64}")
        self.assertEqual(3, len(re.findall(r"emit INFO ", self.workload)))
        self.assertEqual(1, len(re.findall(r"emit WARN ", self.workload)))
        self.assertEqual(2, len(re.findall(r"emit ERROR ", self.workload)))
        for field in ("timestamp", "namespace", "pod", "level", "message", "request_id"):
            self.assertIn(field, self.workload)
        for token in (
            "name: K8S_NAMESPACE",
            "fieldPath: metadata.namespace",
            "name: K8S_POD_NAME",
            "fieldPath: metadata.name",
            '"$K8S_NAMESPACE" "$K8S_POD_NAME"',
        ):
            self.assertIn(token, self.workload)
        self.assertNotIn('"namespace":"training"', self.workload)
        self.assertNotIn('"pod":"s4-log-generator"', self.workload)

    def test_runtime_pod_and_workload_rows_are_fail_closed(self) -> None:
        apply_script = (ROOT / "scripts/apply-workload.ps1").read_text(encoding="utf-8")
        publish_script = (ROOT / "scripts/publish-logs.ps1").read_text(encoding="utf-8")
        for token in (
            "Expected exactly one Pod selected by the exact Job label",
            '$_.kind -ceq "Job"',
            "$_.uid -ceq $job.metadata.uid",
            "Assert-WorkloadLogRows",
            "$event.namespace -cne $script:Namespace",
            "$event.pod -cne $PodName",
        ):
            self.assertIn(token, self.common)
        for script in (apply_script, publish_script):
            self.assertIn("$podName = Get-ExactJobPodName", script)
            self.assertIn("Assert-WorkloadLogRows -Lines $lines -PodName $podName", script)
            self.assertIn('Invoke-Kubectl @("logs", $podName, "-n", $Namespace)', script)

    def test_query_scope_is_bounded(self) -> None:
        query_script = (ROOT / "scripts/query-logs.ps1").read_text(encoding="utf-8")
        self.assertIn("gt 900", query_script)
        self.assertIn("--log-group-name", query_script)
        self.assertIn("--start-time", query_script)
        self.assertIn("--end-time", query_script)
        for query in (ROOT / "queries").glob("*.logs-insights"):
            text = query.read_text(encoding="utf-8")
            self.assertIn('namespace = "udemy4-s4-logs"', text)
            self.assertIn("pod like /^s4-log-generator-/", text)
            self.assertIn("fields @timestamp, namespace, pod", text)
            self.assertIn("limit 20", text)
        for token in (
            "$podName = Get-ExactJobPodName",
            "Convert-LogsInsightsRows",
            "$decoded.Count -ne $ExpectedCount",
            "$row.namespace -cne $Namespace",
            "$row.pod -cne $podName",
            '"all-events" "$PSScriptRoot/../queries/all-events.logs-insights" 6',
            '"errors" "$PSScriptRoot/../queries/errors.logs-insights" 2',
            "decoded_results = $decoded",
        ):
            self.assertIn(token, query_script)

    def test_cleanup_checks_real_residuals(self) -> None:
        cleanup = (ROOT / "scripts/cleanup-section.ps1").read_text(encoding="utf-8")
        verify = (ROOT / "scripts/verify-cleanup.ps1").read_text(encoding="utf-8")
        self.assertIn('@("delete", "namespace"', cleanup)
        self.assertIn('@("get", "namespace", $Namespace, "-o", "json")', cleanup)
        self.assertIn('@("get", "job", $JobName, "-n", $Namespace, "-o", "json")', cleanup)
        for token in ("course", "section", '"managed-by"', "Namespace ownership label mismatch", "Job ownership label mismatch"):
            self.assertIn(token, cleanup)
        self.assertIn("delete-log-group", cleanup)
        self.assertIn("list-tags-log-group", cleanup)
        self.assertIn("describe-log-groups", verify)
        self.assertIn("Cleanup verification failed closed", verify)

    def test_put_log_events_rejection_and_readback_are_checked(self) -> None:
        publish = (ROOT / "scripts/publish-logs.ps1").read_text(encoding="utf-8")
        for token in (
            "$putResponseText",
            "rejectedLogEventsInfo",
            "get-log-events",
            "readback did not return exactly six events",
            "Compare-Object",
        ):
            self.assertIn(token, publish)
        self.assertLess(
            publish.index("rejectedLogEventsInfo"),
            publish.index("all six Job log lines"),
        )

    def test_s4_and_common_paths_share_one_public_checkout(self) -> None:
        self.assertIn("current checkout", self.readme)
        self.assertIn("AWSとkubectlを実行するまでは", self.readme)
        for token in (
            "$PUBLIC_WORKTREE",
            "$ACTUAL_PUBLIC_ROOT",
            "if (-not (Test-Path -LiteralPath $env:UDEMY4_PUBLIC))",
            "$EXPECTED_COMMON_COMMIT",
            "git -C $PUBLIC_WORKTREE diff --quiet $EXPECTED_COMMON_COMMIT -- labs/common-eks",
            "$S4_LAB_DIR",
            "$COMMON_EKS_DIR",
            'Join-Path $COMMON_EKS_DIR "scripts/status.ps1"',
            'Join-Path $S4_LAB_DIR "scripts/preflight.ps1"',
        ):
            self.assertIn(token, self.readme)
        self.assertNotIn("$ROOT_WORKTREE", self.readme)
        self.assertNotIn("$S4_CANDIDATE_DIR", self.readme)
        self.assertNotIn("cd ../", self.readme)

    def test_public_root_summarizes_s4_mutations_and_prerequisites(self) -> None:
        for token in (
            "PowerShell 7",
            "AWS CLI v2",
            "`kubectl`",
            "承認済み認証",
            "namespace `udemy4-s4-logs`",
            "Job `s4-log-generator`",
            "log group `/udemy4/c010/s4/20260725`",
            "log stream `sample-workload`",
            "`apply-workload.ps1`",
            "`publish-logs.ps1`",
            "`cleanup-section.ps1`",
        ):
            self.assertIn(token, self.public_readme)

    def test_evidence_directory_rejects_inside_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = pathlib.Path(temp)
            root = base / "root"
            public = base / "public"
            outside = base / "evidence"
            inside = root / "evidence"
            for path in (root, public, outside, inside):
                path.mkdir(parents=True, exist_ok=True)
            command = (
                f'. "{(ROOT / "scripts/common.ps1").as_posix()}"; '
                f'$roots=@("{root.as_posix()}","{public.as_posix()}"); '
                f'$insideRejected=$false; '
                f'try {{ Assert-EvidenceOutsideWorktrees -EvidencePath "{inside.as_posix()}" -WorktreeRoots $roots }} '
                f'catch {{ $insideRejected=$true }}; '
                f'if (-not $insideRejected) {{ exit 2 }}; '
                f'Assert-EvidenceOutsideWorktrees -EvidencePath "{outside.as_posix()}" -WorktreeRoots $roots'
            )
            powershell = shutil.which("pwsh") or shutil.which("powershell")
            self.assertIsNotNone(powershell, "PowerShell is required for the containment regression test")
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_readme_has_required_learner_contract(self) -> None:
        for heading in (
            "## 前提条件",
            "## 手順",
            "## Cleanup",
            "## Fixture fallback",
            "## Troubleshooting",
        ):
            self.assertIn(heading, self.readme)
        for token in ("USD 0.76/GB", "USD 0.0076/GB", "15分以内", "6時間以内"):
            self.assertIn(token, self.readme)


if __name__ == "__main__":
    unittest.main()
