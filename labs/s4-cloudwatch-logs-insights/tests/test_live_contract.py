from __future__ import annotations

import pathlib
import re
import hashlib
import json
import shlex
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

JQ_STREAM_CONTRACT_DOUBLE = """#!/usr/bin/env python3
import json
import pathlib
import sys

arguments = sys.argv[1:]
variables = {}
positionals = []
slurp = False
index = 0
while index < len(arguments):
    argument = arguments[index]
    if argument in {"-e", "--exit-status"}:
        index += 1
    elif argument in {"-s", "--slurp"}:
        slurp = True
        index += 1
    elif argument == "--arg" and index + 2 < len(arguments):
        variables[arguments[index + 1]] = arguments[index + 2]
        index += 3
    elif argument.startswith("-"):
        raise SystemExit(2)
    else:
        positionals.append(argument)
        index += 1

if not slurp or len(positionals) != 2:
    raise SystemExit(2)

program, input_path = positionals
required_program_tokens = (
    "select(length == 6)",
    "all(.[];",
    "(keys | sort)",
    ".namespace == $namespace",
    ".pod == $pod",
    "type == \\"string\\" and length > 0",
)
if any(token not in program for token in required_program_tokens):
    raise SystemExit(2)

payload = pathlib.Path(input_path).read_text(encoding="utf-8")
decoder = json.JSONDecoder()
rows = []
cursor = 0
try:
    while cursor < len(payload):
        while cursor < len(payload) and payload[cursor].isspace():
            cursor += 1
        if cursor == len(payload):
            break
        row, cursor = decoder.raw_decode(payload, cursor)
        rows.append(row)
except (json.JSONDecodeError, UnicodeDecodeError):
    raise SystemExit(1)

expected_keys = {
    "level",
    "message",
    "namespace",
    "pod",
    "request_id",
    "timestamp",
}
valid = (
    len(rows) == 6
    and all(
        isinstance(row, dict)
        and set(row) == expected_keys
        and row["namespace"] == variables.get("namespace")
        and row["pod"] == variables.get("pod")
        and all(
            isinstance(row[field], str) and len(row[field]) > 0
            for field in ("timestamp", "level", "message", "request_id")
        )
        for row in rows
    )
)
raise SystemExit(0 if valid else 1)
"""


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

    def test_exact_tag_maps_are_locale_independent_and_do_not_call_sort(self) -> None:
        stack_id = (
            "arn:aws:cloudformation:ap-northeast-1:123456789012:"
            "stack/udemy4-c010-common-20260724/01234567-89ab-cdef-0123-456789abcdef"
        )
        stack_tags = [
            {"Key": "WorkPackage", "Value": "c010-common-eks"},
            {
                "Key": "TemplateContract",
                "Value": "udemy4-c010-common-eks-v2-20260724",
            },
            {"Key": "Purpose", "Value": "training"},
            {"Key": "ManagedBy", "Value": "udemy4"},
            {"Key": "Course", "Value": "C010"},
        ]
        eks_tags = {
            "aws:cloudformation:stack-name": "udemy4-c010-common-20260724",
            "aws:cloudformation:stack-id": stack_id,
            "aws:cloudformation:logical-id": "EksCluster",
            "WorkPackage": "c010-common-eks",
            "TemplateContract": "udemy4-c010-common-eks-v2-20260724",
            "Purpose": "training",
            "ManagedBy": "udemy4",
            "Course": "C010",
        }
        result = run_bash(
            "sort() { echo 'external sort must not be called' >&2; return 99; }; "
            "export -f sort; export LC_ALL=C.utf8; "
            f"assert_exact_stack_tags {shlex.quote(json.dumps(stack_tags))}; "
            f"assert_exact_eks_tags {shlex.quote(json.dumps(eks_tags))} "
            f"{shlex.quote(stack_id)}"
        )
        self.assertEqual(0, result.returncode, result.stderr)

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
            "--slurp",
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

    def test_workload_log_rows_slurps_valid_jsonl_and_rejects_invalid_streams(
        self,
    ) -> None:
        pod_name = "s4-log-generator-regression"
        valid_rows = [
            {
                "timestamp": f"2026-07-26T01:02:0{index}Z",
                "namespace": "udemy4-s4-logs",
                "pod": pod_name,
                "level": "INFO",
                "message": f"row-{index}",
                "request_id": f"req-{index}",
            }
            for index in range(1, 7)
        ]

        def jsonl(rows: list[object]) -> str:
            return (
                "\n".join(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                    for row in rows
                )
                + "\n"
            )

        invalid_streams: dict[str, str] = {
            "five rows": jsonl(valid_rows[:5]),
            "seven rows": jsonl(valid_rows + [dict(valid_rows[-1])]),
            "single top-level array": json.dumps(valid_rows) + "\n",
            "non-object row": jsonl(valid_rows[:5] + ["not-an-object"]),
            "malformed sixth row": jsonl(valid_rows[:5]) + '{"timestamp":\n',
        }
        for label, field, value in (
            ("missing key", "request_id", None),
            ("extra key", "extra", "reject"),
            ("wrong namespace", "namespace", "other"),
            ("wrong pod", "pod", "other"),
            ("empty message", "message", ""),
            ("non-string level", "level", 1),
        ):
            rows = [dict(row) for row in valid_rows]
            if label == "missing key":
                del rows[2][field]
            else:
                rows[2][field] = value
            invalid_streams[label] = jsonl(rows)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = pathlib.Path(temp_dir)
            jq_path = temp_root / "jq"
            jq_path.write_text(
                JQ_STREAM_CONTRACT_DOUBLE, encoding="utf-8", newline="\n"
            )
            jq_path.chmod(0o755)
            rows_path = temp_root / "workload-log-rows.jsonl"
            bash_path = shlex.quote(wsl_path(temp_root))
            rows_argument = shlex.quote(wsl_path(rows_path))
            pod_argument = shlex.quote(pod_name)

            def invoke(payload: str) -> subprocess.CompletedProcess[str]:
                rows_path.write_text(payload, encoding="utf-8", newline="\n")
                return run_bash(
                    f"export PATH={bash_path}:$PATH\n"
                    f"assert_workload_log_rows {rows_argument} {pod_argument}"
                )

            accepted = invoke(jsonl(valid_rows))
            self.assertEqual(0, accepted.returncode, accepted.stderr)

            for label, payload in invalid_streams.items():
                with self.subTest(label=label):
                    rejected = invoke(payload)
                    self.assertNotEqual(0, rejected.returncode, rejected.stderr)

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
        ordered_headings = (
            "## 目的",
            "## 前提条件",
            "## 手順",
            "## 期待結果",
            "## Cleanup",
            "## コストと安全上の注意",
            "## Fixture fallback",
            "## Troubleshooting",
            "## 安全設計の補足",
            "## 公式資料",
        )
        for heading in ordered_headings:
            self.assertIn(heading, self.readme)
        positions = [self.readme.index(heading) for heading in ordered_headings]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(8, self.readme.count("ここまでの成功"))
        for token in (
            "このハンズオンでは",
            "Namespace（名前空間）",
            "Job（ジョブ）",
            "log group（ロググループ）",
            "Logs Insights:",
            "USD 0.76/GB",
            "USD 0.0076/GB",
            "最大15分",
            "最大6時間以内",
            "WorkPackage=c010-common-eks",
            "localのsyntax/fixture validationだけ",
            "成功したlive AWS runとして扱わない",
        ):
            self.assertIn(token, self.readme)

        navigation_tokens = (
            'export LEARNER_REPO="$(git rev-parse --show-toplevel)"',
            'cd "$LEARNER_REPO/labs/s4-cloudwatch-logs-insights"',
            "test -f scripts/preflight.sh",
            "test -f queries/all-events.logs-insights",
            'export S4_DIR="$(pwd -P)"',
        )
        for token in navigation_tokens:
            self.assertIn(token, self.readme)
        navigation_positions = [
            self.readme.index(token) for token in navigation_tokens
        ]
        self.assertEqual(navigation_positions, sorted(navigation_positions))

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
