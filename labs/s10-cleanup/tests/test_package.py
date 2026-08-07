import hashlib
import json
import sys
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

import validate_package


class CleanupPackageTests(unittest.TestCase):
    def test_local_contract(self):
        validate_package.validate()

    def test_inventory_has_no_unexpected_files(self):
        inventory = json.loads((PACKAGE / "package-inventory.json").read_text(encoding="utf-8"))["files"]
        self.assertEqual([p for p in PACKAGE.rglob("__pycache__") if p.is_dir()], [])
        actual = {
            p.relative_to(PACKAGE).as_posix()
            for p in PACKAGE.rglob("*")
            if p.is_file() and p.name != "package-inventory.json"
        }
        self.assertEqual(set(inventory), actual)
        for relative, expected in inventory.items():
            self.assertEqual(hashlib.sha256((PACKAGE / relative).read_bytes()).hexdigest(), expected)

    def test_readme_validation_commands_do_not_create_cache(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        self.assertIn("export PYTHONDONTWRITEBYTECODE=1", readme)
        self.assertIn('$env:PYTHONDONTWRITEBYTECODE="1"', readme)
        self.assertIn("compile(p.read_text", readme)
        self.assertNotIn("python -m py_compile", readme)

    def test_exact_target_gate_precedes_mutation(self):
        text = (PACKAGE / "cleanup.sh").read_text(encoding="utf-8")
        gate = text.index("PASS: complete read-only preflight for exact cleanup target")
        for mutation in ("kubectl delete namespace", "kubectl delete configmap", "eksctl delete iamserviceaccount",
                         "aws cloudformation delete-stack", "aws iam delete-policy",
                         "aws iam delete-open-id-connect-provider", "aws iam delete-role-policy",
                         "aws eks delete-fargate-profile", "eksctl delete cluster", "aws logs delete-log-group"):
            self.assertLess(gate, text.index(mutation))

    def test_record_and_final_preflight_cover_readable_and_absent_cluster_paths(self):
        text = (PACKAGE / "cleanup.sh").read_text(encoding="utf-8")
        branch = text.index("if CLUSTER_LOOKUP=")
        final_gate = text.index("PASS: complete read-only preflight for exact cleanup target")
        self.assertLess(text.index("TARGET_RECORD_PATH must name"), branch)
        self.assertLess(text.index("validate-record"), branch)
        self.assertGreater(final_gate, text.index("ResourceNotFoundException", branch))
        self.assertGreater(final_gate, text.index("current cluster OIDC issuer differs", branch))

    def test_shared_resource_and_broad_delete_are_excluded(self):
        text = (PACKAGE / "cleanup.sh").read_text(encoding="utf-8")
        self.assertNotIn("kubectl delete namespace aws-observability", text)
        self.assertNotIn("aws ec2 delete-vpc", text)
        self.assertNotIn("aws ec2 delete-nat-gateway", text)
        self.assertIn("unexpected Fargate Profile exists", text)
        self.assertIn("IAM policy is still attached", text)
        self.assertIn("OIDC provider is still referenced", text)

    def test_residual_verification_requires_validated_record(self):
        text = (PACKAGE / "verify-residuals.sh").read_text(encoding="utf-8")
        self.assertIn("TARGET_RECORD_PATH must name", text)
        self.assertIn("validate-record --path \"$TARGET_RECORD_PATH\" --expected-account \"$ACCOUNT_ID\"", text)
        self.assertLess(text.index("validate-record"), text.index("aws eks describe-cluster"))

    def test_mutations_use_shared_deadline_and_incomplete_handler(self):
        text = (PACKAGE / "cleanup.sh").read_text(encoding="utf-8")
        self.assertIn("run_bounded()", text)
        self.assertIn('timeout "$remaining" "$@" || incomplete', text)
        for line in text.splitlines():
            if any(command in line for command in ("kubectl delete", "eksctl delete", "aws iam delete-", "aws cloudformation delete-stack", "aws eks delete-fargate-profile", "aws logs delete-log-group")):
                self.assertIn("run_bounded", line)

    def test_post_mutation_aws_reads_are_deadline_bounded(self):
        text = (PACKAGE / "cleanup.sh").read_text(encoding="utf-8")
        post = text[text.index('run_bounded "namespace deletion"'):]
        for line in post.splitlines():
            if "aws " in line and not line.lstrip().startswith("#"):
                self.assertTrue("run_bounded" in line or "bounded_read" in line, line)
        self.assertIn('bounded_read PROFILE_WAIT "Fargate Profile post-mutation polling read"', post)
        self.assertIn('incomplete "Fargate Profile deletion could not be proven', post)
        self.assertIn('bounded_read LOG_COUNT "CloudWatch log group post-mutation lookup"', post)
        self.assertIn('|| incomplete "CloudWatch log group lookup failed"', post)

    def test_residual_checks_use_recorded_exact_stack_vpc_nat_ids(self):
        text = (PACKAGE / "verify-residuals.sh").read_text(encoding="utf-8")
        for term in ("EXACT_STACK_IDS", "EXACT_VPC_IDS", "EXACT_NAT_IDS", "--stack-name \"$stack_id\"", "--vpc-ids \"$vpc_id\"", "--nat-gateway-ids \"$nat_id\""):
            self.assertIn(term, text)
        self.assertIn("broad discovery", text)

    def test_residual_call_graph_uses_shared_deadline_without_recursion(self):
        cleanup = (PACKAGE / "cleanup.sh").read_text(encoding="utf-8")
        verify = (PACKAGE / "verify-residuals.sh").read_text(encoding="utf-8")
        self.assertIn('VERIFY_DEADLINE_EPOCH="$CLEANUP_DEADLINE_EPOCH"', cleanup)
        self.assertIn('timeout "$remaining" env TARGET_RECORD_PATH=', cleanup)
        self.assertIn('aws() { local now remaining;', verify)
        self.assertIn('timeout "$remaining" "$REAL_AWS" "$@"', verify)
        self.assertNotIn("run_residual_check", verify)

    def test_mutation_timeout_reserves_and_triggers_verifier(self):
        cleanup = (PACKAGE / "cleanup.sh").read_text(encoding="utf-8")
        self.assertIn("RESIDUAL_RESERVE_SECONDS=180", cleanup)
        self.assertIn("MUTATION_DEADLINE_EPOCH", cleanup)
        self.assertIn("incomplete() {", cleanup)
        self.assertIn("run_residual_check || true", cleanup)
        self.assertIn('timeout "$remaining" "$@" || incomplete', cleanup)

    def test_readable_partial_capture_derives_and_checks_exact_oidc(self):
        text = (PACKAGE / "capture_target_record.py").read_text(encoding="utf-8")
        self.assertIn('if cluster is not None else', text)
        self.assertIn('exact_oidc_arn = f"arn:aws:iam::{args.account}:oidc-provider/{issuer}"', text)
        self.assertIn('get-open-id-connect-provider', text)

    def test_no_credentials_or_local_paths(self):
        prohibited = ("AK" + "IA", "AS" + "IA", "BEGIN PRIVATE" + " KEY", "C:" + "\\\\Users\\\\", "/" + "Users/")
        for path in PACKAGE.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                text = path.read_text(encoding="utf-8")
                for marker in prohibited:
                    self.assertNotIn(marker, text)

    def test_stack_population_preflight_precedes_stack_deletion(self):
        text = (PACKAGE / "cleanup.sh").read_text(encoding="utf-8")
        gate = text.index("PASS: complete read-only preflight for exact cleanup target")
        self.assertIn("list-stack-resources", (PACKAGE / "execute_preflight.py").read_text(encoding="utf-8"))
        self.assertLess(gate, text.index("aws cloudformation delete-stack"))


if __name__ == "__main__":
    unittest.main()
