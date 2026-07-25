from __future__ import annotations

import pathlib
import re
import hashlib
import json
import shlex
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def wsl_path(path: pathlib.Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    return f"/mnt/{drive}/{resolved.as_posix().split(':', 1)[1].lstrip('/')}"


def run_bash(body: str) -> subprocess.CompletedProcess[str]:
    common = shlex.quote(wsl_path(ROOT / "scripts" / "common.sh"))
    result = subprocess.run(
        ["bash"],
        input=f"set -euo pipefail\nsource {common}\n{body}\n".encode(),
        capture_output=True,
        check=False,
    )
    result.stdout = result.stdout.decode()
    result.stderr = result.stderr.decode()
    return result


class LiveContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.common = (ROOT / "scripts/common.sh").read_text(encoding="utf-8")
        cls.scripts = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "scripts").glob("*.sh"))
        }
        cls.joined = "\n".join(cls.scripts.values())
        cls.workload = (ROOT / "manifests/10-log-workload.yaml").read_text(
            encoding="utf-8"
        )

    def test_cloudshell_bash_is_the_only_learner_script_contract(self) -> None:
        self.assertEqual(
            {
                "apply-workload.sh",
                "cleanup-section.sh",
                "common.sh",
                "preflight.sh",
                "publish-logs.sh",
                "query-logs.sh",
                "verify-cleanup.sh",
            },
            set(self.scripts),
        )
        self.assertFalse(list((ROOT / "scripts").glob("*.ps1")))
        for token in (
            "AWS CloudShell",
            "Bash",
            "local PowerShellは不要",
            "aws --version",
            "kubectl version --client --output=json",
            "aws sts get-caller-identity",
            "ap-northeast-1",
            "$HOME",
            "1 GB",
        ):
            self.assertIn(token, self.readme)

    def test_region_name_and_external_binding_are_exact(self) -> None:
        for token in (
            'REGION="ap-northeast-1"',
            'CLUSTER_NAME="udemy4-c010-common-20260724"',
            "AWS_ACCOUNT_ID",
            "STS account does not equal AWS_ACCOUNT_ID",
            "kubectl context must equal the exact common cluster ARN",
            "endpointPrivateAccess",
            "endpointPublicAccess",
            "AccessDenied|Unauthorized|ExpiredToken|InvalidClientToken",
            "assert_exact_stack_tags",
            "assert_exact_eks_tags",
            "assert_fixed_stack_outputs",
        ):
            self.assertIn(token, self.common)

    def test_external_binding_rejects_stack_eks_and_output_drift(self) -> None:
        stack_id = (
            "arn:aws:cloudformation:ap-northeast-1:123456789012:"
            "stack/udemy4-c010-common-20260724/example"
        )
        stack_tags = [
            {"Key": "Course", "Value": "C010"},
            {"Key": "ManagedBy", "Value": "udemy4"},
            {"Key": "Purpose", "Value": "training"},
            {
                "Key": "TemplateContract",
                "Value": "udemy4-c010-common-eks-v2-20260724",
            },
            {"Key": "WorkPackage", "Value": "c010-common-eks"},
        ]
        eks_tags = {
            "Course": "C010",
            "ManagedBy": "udemy4",
            "Purpose": "training",
            "TemplateContract": "udemy4-c010-common-eks-v2-20260724",
            "WorkPackage": "c010-common-eks",
            "aws:cloudformation:logical-id": "EksCluster",
            "aws:cloudformation:stack-id": stack_id,
            "aws:cloudformation:stack-name": "udemy4-c010-common-20260724",
        }
        outputs = [
            {
                "OutputKey": "ClusterName",
                "OutputValue": "udemy4-c010-common-20260724",
            },
            {"OutputKey": "Region", "OutputValue": "ap-northeast-1"},
            {
                "OutputKey": "TemplateContract",
                "OutputValue": "udemy4-c010-common-eks-v2-20260724",
            },
        ]
        accepted = run_bash(
            f"assert_exact_stack_tags {shlex.quote(json.dumps(stack_tags))}; "
            f"assert_exact_eks_tags {shlex.quote(json.dumps(eks_tags))} "
            f"{shlex.quote(stack_id)}; "
            f"assert_fixed_stack_outputs {shlex.quote(json.dumps(outputs))}"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)

        bad_stack_tags = stack_tags + [{"Key": "Owner", "Value": "other"}]
        bad_eks_tags = dict(eks_tags)
        bad_eks_tags["aws:cloudformation:logical-id"] = "OtherCluster"
        bad_outputs = [dict(item) for item in outputs]
        bad_outputs[1]["OutputValue"] = "us-east-1"
        for rejected in (
            f"assert_exact_stack_tags {shlex.quote(json.dumps(bad_stack_tags))}",
            (
                f"assert_exact_eks_tags {shlex.quote(json.dumps(bad_eks_tags))} "
                f"{shlex.quote(stack_id)}"
            ),
            f"assert_fixed_stack_outputs {shlex.quote(json.dumps(bad_outputs))}",
        ):
            result = run_bash(rejected)
            self.assertNotEqual(0, result.returncode, rejected)

    def test_version_gates_use_semantic_behavior(self) -> None:
        accepted = run_bash(
            "assert_aws_cli_minimum_text 'aws-cli/2.12.3 Python/3.11'; "
            "assert_aws_cli_minimum_text 'aws-cli/2.20.0 Python/3.12'; "
            "assert_kubectl_minor_compatible v1.31.1 1.30; "
            "assert_kubectl_minor_compatible v1.29.8 1.30"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        for rejected in (
            "assert_aws_cli_minimum_text 'aws-cli/2.12.2 Python/3.11'",
            "assert_aws_cli_minimum_text 'aws-cli/1.99.99 Python/3.11'",
            "assert_kubectl_minor_compatible v1.28.9 1.30",
            "assert_kubectl_minor_compatible v2.30.0 1.30",
        ):
            result = run_bash(rejected)
            self.assertNotEqual(0, result.returncode, rejected)

    def test_runtime_endpoint_gate_rejects_cidr_drift_and_world_access(self) -> None:
        accepted = run_bash(
            "assert_runtime_endpoint_values true true 198.51.100.10/32 198.51.100.10/32"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        for rejected in (
            "assert_runtime_endpoint_values false true 198.51.100.10/32 198.51.100.10/32",
            "assert_runtime_endpoint_values true false 198.51.100.10/32 198.51.100.10/32",
            "assert_runtime_endpoint_values true true 198.51.100.10/32 198.51.100.11/32",
            "assert_runtime_endpoint_values true true 0.0.0.0/0 0.0.0.0/0",
            "assert_runtime_endpoint_values true true 198.51.100.10/32 198.51.100.10/32 198.51.100.11/32",
        ):
            result = run_bash(rejected)
            self.assertNotEqual(0, result.returncode, rejected)

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
        apply = self.scripts["apply-workload.sh"]
        self.assertLess(
            apply.index('manifests/00-namespace.yaml'),
            apply.index("apply_exact_cleanup_rbac"),
        )
        self.assertLess(
            apply.index("apply_exact_cleanup_rbac"),
            apply.index('manifests/10-log-workload.yaml'),
        )
        for token in (
            'resourceNames == ["s4-log-generator"]',
            'resourceNames == ["udemy4-s4-logs"]',
            "udemy4:c010:s4-cleanup",
            "CleanupRbacManifest",
        ):
            self.assertIn(token, self.common)

    def test_runtime_pod_and_six_rows_are_fail_closed(self) -> None:
        for token in (
            "Expected exactly one Pod selected by the exact Job label",
            '.kind == "Job"',
            ".uid == $uid",
            "assert_workload_log_rows",
            "select(length == 6)",
            ".namespace == $namespace",
            ".pod == $pod",
        ):
            self.assertIn(token, self.common)
        for script_name in ("apply-workload.sh", "publish-logs.sh"):
            script = self.scripts[script_name]
            self.assertIn('pod_name="$(get_exact_job_pod_name)"', script)
            self.assertIn("assert_workload_log_rows", script)
            self.assertIn('kubectl logs "$pod_name" -n "$NAMESPACE"', script)

    def test_query_scope_and_decoded_results_are_bounded(self) -> None:
        query_script = self.scripts["query-logs.sh"]
        self.assertIn("end_epoch - start_epoch <= 900", query_script)
        for query in (ROOT / "queries").glob("*.logs-insights"):
            text = query.read_text(encoding="utf-8")
            self.assertIn('namespace = "udemy4-s4-logs"', text)
            self.assertIn("pod like /^s4-log-generator-/", text)
            self.assertIn("fields @timestamp, namespace, pod", text)
            self.assertIn("limit 20", text)
        for token in (
            "logs start-query",
            "logs get-query-results",
            '[[ "$status" == "Complete" ]]',
            "decoded_results",
            '"all-events"',
            '"errors"',
            "expected_count",
        ):
            self.assertIn(token, query_script)

    def test_put_log_events_rejection_and_readback_are_checked(self) -> None:
        publish = self.scripts["publish-logs.sh"]
        for token in (
            "rejectedLogEventsInfo",
            "logs get-log-events",
            "CloudWatch readback did not return exactly six events",
            "diff -u",
            "end_epoch - start_epoch <= 900",
        ):
            self.assertIn(token, publish)
        predicate = (
            '(has("rejectedLogEventsInfo") | not) '
            'or (.rejectedLogEventsInfo == null)'
        )
        self.assertIn(predicate, publish)

        def accepted(payload: dict) -> bool:
            return (
                "rejectedLogEventsInfo" not in payload
                or payload["rejectedLogEventsInfo"] is None
            )

        self.assertTrue(accepted({}))
        self.assertTrue(accepted({"rejectedLogEventsInfo": None}))
        self.assertFalse(
            accepted({"rejectedLogEventsInfo": {"tooNewLogEventStartIndex": 0}})
        )

    def test_evidence_directory_rejects_git_worktrees(self) -> None:
        for token in (
            "LEARNER_REPO",
            "EVIDENCE_DIR",
            "must equal the exact Git worktree root",
            "outside the learner Git worktree",
            "must not be inside any Git worktree",
        ):
            self.assertIn(token, self.common)

    def test_cleanup_order_ownership_and_residuals_are_explicit(self) -> None:
        cleanup = self.scripts["cleanup-section.sh"]
        verify = self.scripts["verify-cleanup.sh"]
        for token in (
            'kubectl delete namespace "$NAMESPACE"',
            "assert_exact_namespace_labels",
            "assert_exact_log_group_tags",
            "logs delete-log-group",
        ):
            self.assertIn(token, cleanup)
        for token in (
            "Section namespace remains",
            "Section log group remains",
            "Cleanup verification failed closed",
        ):
            self.assertIn(token, verify)
        self.assertIn("必ずSectionを先に削除", self.readme)
        self.assertIn("guardを最後", self.readme)

    def test_manual_cleanup_requires_complete_namespace_and_job_label_maps(self) -> None:
        namespace = {
            "metadata": {
                "labels": {
                    "course": "c010",
                    "section": "s4",
                    "managed-by": "udemy4",
                    "kubernetes.io/metadata.name": "udemy4-s4-logs",
                }
            }
        }
        job = {
            "metadata": {
                "labels": {
                    "course": "c010",
                    "section": "s4",
                    "managed-by": "udemy4",
                }
            }
        }
        accepted = run_bash(
            f"assert_exact_namespace_labels {shlex.quote(json.dumps(namespace))} Namespace; "
            f"assert_exact_namespace_labels {shlex.quote(json.dumps(job))} Job"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        bad_namespace = json.loads(json.dumps(namespace))
        bad_namespace["metadata"]["labels"]["unexpected"] = "reject"
        bad_job = json.loads(json.dumps(job))
        bad_job["metadata"]["labels"]["unexpected"] = "reject"
        for payload, kind in ((bad_namespace, "Namespace"), (bad_job, "Job")):
            result = run_bash(
                f"assert_exact_namespace_labels {shlex.quote(json.dumps(payload))} {kind}"
            )
            self.assertNotEqual(0, result.returncode)

    def test_readme_has_required_learner_contract_and_not_run_boundary(self) -> None:
        for heading in (
            "## 前提条件",
            "## 手順",
            "## 期待結果",
            "## Cleanup",
            "## Fixture fallback",
            "## Troubleshooting",
        ):
            self.assertIn(heading, self.readme)
        for token in (
            "USD 0.76/GB",
            "USD 0.0076/GB",
            "最大15分",
            "最大6時間以内",
            "WorkPackage=c010-common-eks",
            "localのsyntax/fixture validationだけ",
            "成功したlive AWS runとして扱わない",
        ):
            self.assertIn(token, self.readme)

    def test_learner_inventory_is_exact_and_current(self) -> None:
        inventory = ROOT / "artifact-inventory.sha256"
        records = [
            line
            for line in inventory.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(18, len(records))
        paths = [record.split("  ", 1)[1] for record in records]
        self.assertEqual(paths, sorted(paths, key=lambda value: value.encode("utf-8")))
        discovered = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if (
                path == inventory
                or "__pycache__" in path.parts
            ):
                continue
            discovered.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(paths, sorted(discovered, key=lambda value: value.encode("utf-8")))
        for record in records:
            expected, relative = record.split("  ", 1)
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(expected, actual, relative)


if __name__ == "__main__":
    unittest.main()
