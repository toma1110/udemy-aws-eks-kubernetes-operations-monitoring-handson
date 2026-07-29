import json
import re
import unittest
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]


class PublicLabContractTests(unittest.TestCase):
    def test_required_learner_files_exist(self):
        required = [
            "README.md",
            "analyze.py",
            "expected-results.json",
            "templates/observation-notes.md",
            "scripts/common.sh",
            "scripts/prepare-private-run.sh",
            "scripts/status-redacted.sh",
            "scripts/preflight.sh",
            "scripts/capture-observations.sh",
            "scripts/cleanup-local-evidence.sh",
        ]
        for relative in required:
            with self.subTest(relative=relative):
                self.assertTrue((LAB / relative).is_file())

    def test_cloudshell_and_cleanup_contract(self):
        readme = (LAB / "README.md").read_text(encoding="utf-8")
        for token in (
            "AWS CloudShell",
            "ap-northeast-1",
            "aws --version",
            "kubectl version --client",
            'df -h "$HOME"',
            '"$COMMON_EKS_DIR/scripts/delete.sh"',
            '"$COMMON_EKS_DIR/scripts/post-guard-verify.sh"',
        ):
            self.assertIn(token, readme)
        self.assertLess(
            readme.index('"$COMMON_EKS_DIR/scripts/delete.sh"'),
            readme.index('"$COMMON_EKS_DIR/scripts/post-guard-verify.sh"'),
        )

    def test_learner_output_redacts_identity(self):
        readme = (LAB / "README.md").read_text(encoding="utf-8")
        self.assertIn("irsa_annotation_present:", readme)
        self.assertNotIn(
            '"$TARGET_SERVICE_ACCOUNT" \\\n  -n "$TARGET_NAMESPACE" \\\n  -o yaml',
            readme,
        )
        learner_block = readme[
            readme.index("## 5. ServiceAccount")
            : readme.index("## 6. AWS側")
        ]
        self.assertNotIn("arn:aws:iam::", learner_block)
        self.assertIsNone(re.search(r"(?<!\d)\d{12}(?!\d)", learner_block))

    def test_observation_scripts_do_not_grant_permissions(self):
        scripts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((LAB / "scripts").glob("*.sh"))
        )
        forbidden = (
            "kubectl apply",
            "kubectl create",
            "kubectl patch",
            "create-access-entry",
            "associate-access-policy",
            "create-pod-identity-association",
            "update-pod-identity-association",
            "attach-role-policy",
            "put-role-policy",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, scripts)

    def test_expected_results_bind_exact_hands_on_lectures(self):
        expected = json.loads(
            (LAB / "expected-results.json").read_text(encoding="utf-8")
        )
        self.assertEqual(expected["hands_on_lectures"], ["s6-l4", "s6-l5"])


if __name__ == "__main__":
    unittest.main()

