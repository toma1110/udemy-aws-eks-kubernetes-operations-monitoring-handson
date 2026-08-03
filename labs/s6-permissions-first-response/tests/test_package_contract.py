import hashlib
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
    def test_learner_readme_cloudshell_contract(self):
        text = (PACKAGE / "README.md").read_text(encoding="utf-8")
        for token in (
            "AWS CloudShell",
            "ap-northeast-1",
            "aws --version",
            "kubectl version --client",
            "jq --version",
            'df -h "$HOME"',
            "Regionごとに1 GB",
            "https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson/tree/main/labs/s6-permissions-first-response",
            "../common-eks/README.md",
            "https://docs.aws.amazon.com/cloudshell/latest/userguide/vm-specs.html",
            "## 費用",
            "## Troubleshooting",
            "## 8. Cleanup",
        ):
            self.assertIn(token, text)
        self.assertNotIn("```powershell", text.lower())
        for internal_word in (
            "fixture",
            "回帰",
            "Worker",
            "Reviewer",
            "QA",
            "公開アナライザー",
            "公開ラボ",
            "live AWS",
            "同じ対象",
            "読み取りの確認",
        ):
            self.assertNotIn(internal_word, text)

    def test_staged_prerequisites_are_cloudshell_first(self):
        text = (PACKAGE.parents[1] / "docs" / "prerequisites.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "AWS CloudShell",
            "Bash",
            "ap-northeast-1",
            "aws --version",
            "kubectl version --client --output=json",
            "jq --version",
            'df -h "$HOME"',
            "Regionごとに1 GB",
            "../labs/common-eks/README.md",
            "https://docs.aws.amazon.com/cloudshell/latest/userguide/vm-specs.html",
        ):
            self.assertIn(token, text)
        self.assertNotIn("```powershell", text.lower())

    def test_reviewed_common_dependency_bytes_are_present(self):
        common = PACKAGE.parent / "common-eks" / "scripts"
        expected = {
            "bind-current-identity.sh": "35065d40f4fb017d96be980d0d560068bf7d70a639c7cfbcdd84092614838382",
            "post-guard-verify.sh": "3c53f8ee94ef70e3e7691bb81ec0d1eaca4c70d2d6541e8b3fd7301b0468e669",
        }
        for name, expected_sha256 in expected.items():
            with self.subTest(name=name):
                actual = hashlib.sha256((common / name).read_bytes()).hexdigest()
                self.assertEqual(actual, expected_sha256)

    def test_scripts_are_read_only_except_exact_local_cleanup(self):
        capture = (PACKAGE / "scripts" / "capture-observations.sh").read_text(
            encoding="utf-8"
        )
        for required in (
            'required_kubectl "$raw_dir/serviceaccount.json" get serviceaccount',
            'required_kubectl "$raw_dir/rolebindings.json" get rolebindings',
            'required_kubectl "$raw_dir/clusterrolebindings.json" get clusterrolebindings',
            "eks list-access-entries",
            "eks describe-access-entry",
            "eks list-associated-access-policies",
            "eks list-pod-identity-associations",
            "eks describe-pod-identity-association",
        ):
            self.assertIn(required, capture)
        forbidden = (
            "kubectl apply",
            "kubectl create",
            "kubectl patch",
            "kubectl delete",
            "create-access-entry",
            "associate-access-policy",
            "create-pod-identity-association",
            "update-pod-identity-association",
            "attach-role-policy",
            "put-role-policy",
        )
        all_scripts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((PACKAGE / "scripts").glob("*.sh"))
            if path.name != "cleanup-local-evidence.sh"
        )
        for token in forbidden:
            self.assertNotIn(token, all_scripts)
        cleanup = (PACKAGE / "scripts" / "cleanup-local-evidence.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('rm -rf -- "$evidence_dir"', cleanup)
        self.assertIn("CURRENT_STS_IDENTITY_FILE", cleanup)
        self.assertNotIn("aws ", cleanup)
        self.assertNotIn("kubectl ", cleanup)

    def test_scripts_enforce_exact_common_target(self):
        common = (PACKAGE / "scripts" / "common.sh").read_text(encoding="utf-8")
        for token in (
            "assert_preflight true",
            "get_expected_stack_binding",
            "assert_exact_kubernetes_context",
            "assert_s6_inputs",
        ):
            self.assertIn(token, common)
        capture = (PACKAGE / "scripts" / "capture-observations.sh").read_text(
            encoding="utf-8"
        )
        self.assertEqual(capture.count("assert_s6_target"), 1)
        self.assertFalse((PACKAGE / "scripts" / "preflight.sh").exists())
        self.assertFalse((PACKAGE / "scripts" / "status-redacted.sh").exists())

    def test_run_directory_is_atomic_no_clobber_and_rejects_stale_raw(self):
        prepare = (PACKAGE / "scripts" / "prepare-private-run.sh").read_text(
            encoding="utf-8"
        )
        common = (PACKAGE / "scripts" / "common.sh").read_text(encoding="utf-8")
        creation = prepare + common
        for token in (
            "mktemp -d",
            "mv -Tn --",
            "Run-specific evidence target already exists",
            "Temporary run sibling was not empty",
            "Atomic no-clobber run installation collided",
        ):
            self.assertIn(token, creation)
        capture = (PACKAGE / "scripts" / "capture-observations.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("Run-specific raw directory is not empty", capture)
        self.assertNotIn("mkdir -p", capture)

    def test_failure_injection_removes_temp_and_new_empty_parent(self):
        common = PACKAGE / "scripts" / "common.sh"
        for fail_point in ("after-parent", "after-temp", "after-contract"):
            with self.subTest(fail_point=fail_point), tempfile.TemporaryDirectory() as temp:
                private_dir = Path(temp) / "current-run"
                private_dir.mkdir()
                identity = private_dir / "current-sts-identity.json"
                identity.write_text("{}\n", encoding="utf-8")
                command = f'''
source "{common.as_posix()}"
export PRIVATE_EXECUTION_DIR="{private_dir.as_posix()}"
export CURRENT_STS_IDENTITY_FILE="{identity.as_posix()}"
export AWS_REGION="ap-northeast-1"
export AWS_DEFAULT_REGION="ap-northeast-1"
export TARGET_NAMESPACE="default"
export TARGET_SERVICE_ACCOUNT="default"
export S6_RUN_ID="20260730T000000Z-a1b2c3d4"
export S6_OBSERVATION_ROOT="$PRIVATE_EXECUTION_DIR/s6-observations"
export S6_EVIDENCE_DIR="$S6_OBSERVATION_ROOT/observations-$S6_RUN_ID"
export S6_TEST_FAIL_POINT="{fail_point}"
if create_s6_run_directory; then exit 91; fi
[[ ! -e "$S6_OBSERVATION_ROOT" ]]
'''
                result = subprocess.run(
                    ["bash", "-c", command],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_single_capture_entrypoint_redacts_exact_target(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        capture = (PACKAGE / "scripts" / "capture-observations.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('"$COMMON_EKS_DIR/scripts/status.sh"', readme)
        self.assertNotIn("status-redacted.sh", readme)
        self.assertNotIn("preflight.sh", readme)
        self.assertEqual(readme.count('"$S6_DIR/scripts/capture-observations.sh"'), 1)
        self.assertIn("観察対象を確認しました", capture)
        self.assertNotIn("AWS_ACCOUNT_ID", capture)

    def test_learner_uses_one_private_capture_instead_of_duplicate_manual_reads(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("kubectl get serviceaccount", readme)
        self.assertNotIn("kubectl get rolebindings", readme)
        self.assertNotIn("kubectl get clusterrolebindings", readme)
        learner_block = readme[readme.index("## 5.") : readme.index("## 6.")]
        self.assertNotIn("arn:aws:iam::", learner_block)
        self.assertNotRegex(learner_block, r"(?<!\d)\d{12}(?!\d)")

    def test_identity_cleanup_is_two_phase_and_residual_gated(self):
        phase_one = (PACKAGE / "scripts" / "cleanup-local-evidence.sh").read_text(
            encoding="utf-8"
        )
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        prepare = (PACKAGE / "scripts" / "prepare-private-run.sh").read_text(
            encoding="utf-8"
        )
        common = (PACKAGE / "scripts" / "common.sh").read_text(encoding="utf-8")
        identity_flow = prepare + common
        self.assertIn("Governed common identity must remain", phase_one)
        for token in (
            "bind-current-identity.sh",
            "source",
            "PRIVATE_EXECUTION_DIR",
            "CURRENT_STS_IDENTITY_FILE",
        ):
            self.assertIn(token, identity_flow)
        self.assertNotIn("identity.json", phase_one)
        self.assertFalse((PACKAGE / "scripts" / "finalize-private-cleanup.sh").exists())
        self.assertIn('"$COMMON_EKS_DIR/scripts/delete.sh"', readme)
        self.assertIn('"$COMMON_EKS_DIR/scripts/post-guard-verify.sh"', readme)
        self.assertLess(
            readme.index('"$COMMON_EKS_DIR/scripts/delete.sh"'),
            readme.index('"$COMMON_EKS_DIR/scripts/post-guard-verify.sh"'),
        )

    def test_analyzer_separates_layers_and_redacts_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            documents = {
                "serviceaccount.json": {
                    "metadata": {
                        "name": "aws-node",
                        "namespace": "kube-system",
                        "annotations": {
                            "eks.amazonaws.com/role-arn": "arn:aws:iam::ACCOUNT_ID_REDACTED:role/private"
                        },
                    }
                },
                "rolebindings.json": {
                    "items": [
                        {
                            "kind": "RoleBinding",
                            "metadata": {"name": "reader", "namespace": "kube-system"},
                            "subjects": [
                                {
                                    "kind": "ServiceAccount",
                                    "name": "aws-node",
                                    "namespace": "kube-system",
                                }
                            ],
                            "roleRef": {"kind": "Role", "name": "reader"},
                        }
                    ]
                },
                "clusterrolebindings.json": {"items": []},
                "access-entry-a.json": {
                    "accessEntry": {
                        "principalArn": "arn:aws:iam::ACCOUNT_ID_REDACTED:role/admin",
                        "type": "STANDARD",
                        "kubernetesGroups": ["ops"],
                    }
                },
                "access-policies-a.json": {
                    "associatedAccessPolicies": [
                        {
                            "policyArn": "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy",
                            "accessScope": {"type": "cluster"},
                        }
                    ]
                },
                "pod-identity-a.json": {
                    "association": {
                        "associationArn": "arn:aws:eks:ap-northeast-1:ACCOUNT_ID_REDACTED:podidentityassociation/x",
                        "roleArn": "arn:aws:iam::ACCOUNT_ID_REDACTED:role/pod",
                        "namespace": "kube-system",
                        "serviceAccount": "aws-node",
                    }
                },
            }
            status_dir = root / "status"
            status_dir.mkdir()
            status_documents = {
                "eks_access_list.json": {
                    "layer": "eks_access_list",
                    "observed": True,
                    "reason": "observed",
                },
                "pod_identity_list.json": {
                    "layer": "pod_identity_list",
                    "observed": True,
                    "reason": "observed",
                },
                "eks_access_detail.json": {
                    "listed": True,
                    "entry_count": 1,
                    "described_count": 1,
                    "policy_listed_count": 1,
                    "complete": True,
                },
                "pod_identity_detail.json": {
                    "listed": True,
                    "association_count": 1,
                    "described_count": 1,
                    "complete": True,
                },
            }
            for name, document in documents.items():
                (root / name).write_text(json.dumps(document), encoding="utf-8")
            for name, document in status_documents.items():
                (status_dir / name).write_text(json.dumps(document), encoding="utf-8")
            summary = analyze.build_summary(
                root, "kube-system", "aws-node", status_dir
            )
            analyze.reject_sensitive_summary(summary)
            encoded = json.dumps(summary)
            self.assertNotIn("ACCOUNT_ID_REDACTED", encoded)
            self.assertNotIn("arn:aws:iam::", encoded)
            self.assertEqual(summary["kubernetes_rbac"]["binding_count"], 1)
            self.assertTrue(summary["irsa_annotation"]["present"])
            self.assertTrue(summary["pod_identity"]["target_association_present"])
            self.assertEqual(summary["eks_access"]["listed_count"], 1)
            self.assertEqual(summary["eks_access"]["described_count"], 1)
            self.assertEqual(summary["eks_access"]["policy_listed_count"], 1)
            self.assertTrue(summary["eks_access"]["observed"])
            self.assertTrue(summary["eks_access"]["complete"])

    def test_analyzer_reports_partial_permissions_without_false_absence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            status_dir = root / "status"
            status_dir.mkdir()
            base_documents = {
                "serviceaccount.json": {"metadata": {"annotations": {}}},
                "rolebindings.json": {"items": []},
                "clusterrolebindings.json": {"items": []},
            }
            for name, document in base_documents.items():
                (root / name).write_text(json.dumps(document), encoding="utf-8")
            statuses = {
                "eks_access_list.json": {
                    "observed": True,
                    "reason": "observed",
                },
                "pod_identity_list.json": {
                    "observed": True,
                    "reason": "observed",
                },
                "eks_access_detail.json": {
                    "listed": True,
                    "entry_count": 1,
                    "described_count": 0,
                    "policy_listed_count": 1,
                    "detail_access_denied_count": 1,
                    "detail_read_failed_count": 0,
                    "complete": False,
                },
                "pod_identity_detail.json": {
                    "listed": True,
                    "association_count": 1,
                    "described_count": 0,
                    "detail_access_denied_count": 0,
                    "detail_read_failed_count": 1,
                    "complete": False,
                },
            }
            for name, document in statuses.items():
                (status_dir / name).write_text(json.dumps(document), encoding="utf-8")
            summary = analyze.build_summary(
                root, "default", "default", status_dir
            )
            self.assertTrue(summary["eks_access"]["observed"])
            self.assertFalse(summary["eks_access"]["complete"])
            self.assertEqual(summary["eks_access"]["listed_count"], 1)
            self.assertEqual(summary["eks_access"]["described_count"], 0)
            self.assertEqual(summary["eks_access"]["detail_failure_count"], 1)
            self.assertEqual(
                summary["eks_access"]["detail_not_observed_reasons"],
                ["access-denied"],
            )
            self.assertTrue(summary["pod_identity"]["observed"])
            self.assertFalse(summary["pod_identity"]["complete"])
            self.assertEqual(summary["pod_identity"]["listed_count"], 1)
            self.assertEqual(summary["pod_identity"]["described_count"], 0)
            self.assertEqual(summary["pod_identity"]["detail_failure_count"], 1)
            self.assertIsNone(summary["pod_identity"]["target_association_present"])
            self.assertEqual(
                summary["pod_identity"]["detail_not_observed_reasons"],
                ["read-failed"],
            )

    def test_policy_list_denied_is_counted_and_makes_access_detail_incomplete(self):
        capture = (PACKAGE / "scripts" / "capture-observations.sh").read_text(
            encoding="utf-8"
        )
        for token in (
            "access_policies_observed",
            'reason="$(jq -r \'.reason\' "$status_dir/access_policies_$ordinal.json")"',
            "policy_listed_count:$policies_observed",
            "$total == $observed and $total == $policies_observed",
        ):
            self.assertIn(token, capture)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            status_dir = root / "status"
            status_dir.mkdir()
            documents = {
                "serviceaccount.json": {"metadata": {"annotations": {}}},
                "rolebindings.json": {"items": []},
                "clusterrolebindings.json": {"items": []},
                "access-entry-a.json": {
                    "accessEntry": {
                        "type": "STANDARD",
                        "kubernetesGroups": [],
                    }
                },
            }
            for name, document in documents.items():
                (root / name).write_text(json.dumps(document), encoding="utf-8")
            statuses = {
                "eks_access_list.json": {"observed": True, "reason": "observed"},
                "pod_identity_list.json": {"observed": True, "reason": "observed"},
                "eks_access_detail.json": {
                    "listed": True,
                    "entry_count": 1,
                    "described_count": 1,
                    "policy_listed_count": 0,
                    "detail_access_denied_count": 1,
                    "detail_read_failed_count": 0,
                    "complete": False,
                },
                "pod_identity_detail.json": {
                    "listed": True,
                    "association_count": 0,
                    "described_count": 0,
                    "detail_access_denied_count": 0,
                    "detail_read_failed_count": 0,
                    "complete": True,
                },
            }
            for name, document in statuses.items():
                (status_dir / name).write_text(json.dumps(document), encoding="utf-8")
            summary = analyze.build_summary(root, "default", "default", status_dir)
            self.assertEqual(summary["eks_access"]["listed_count"], 1)
            self.assertEqual(summary["eks_access"]["described_count"], 1)
            self.assertEqual(summary["eks_access"]["policy_listed_count"], 0)
            self.assertFalse(summary["eks_access"]["complete"])
            self.assertEqual(summary["eks_access"]["detail_failure_count"], 1)
            self.assertEqual(
                summary["eks_access"]["detail_not_observed_reasons"],
                ["access-denied"],
            )

    def test_expected_results_and_population(self):
        contract = json.loads(
            (PACKAGE / "expected-results.json").read_text(encoding="utf-8")
        )
        self.assertEqual(contract["hands_on_lectures"], ["s6-l4", "s6-l5"])
        self.assertEqual(contract["cleanup"]["section_cloud_resources"], "none")


if __name__ == "__main__":
    unittest.main()
