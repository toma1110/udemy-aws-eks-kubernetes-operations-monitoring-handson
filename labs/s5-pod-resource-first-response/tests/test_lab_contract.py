import sys
import unittest
from pathlib import Path

import yaml

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

import analyze
import lab_validate


class DeployableLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = lab_validate.validate()
        cls.documents = []
        for path in analyze.PRIMARY_LAB_MANIFESTS:
            cls.documents.extend(yaml.safe_load_all(path.read_text(encoding="utf-8")))

    def test_primary_manifest_inventory(self):
        self.assertEqual(self.result["status"], "pass")
        self.assertEqual(self.result["manifest_count"], 4)
        self.assertEqual(self.result["pod_count"], 3)

    def test_exact_names_namespace_and_labels(self):
        for document in self.documents:
            self.assertTrue(document["metadata"]["name"].startswith("udemy4-c010-s5-20260724"))
            if document["kind"] == "Pod":
                self.assertEqual(document["metadata"]["namespace"], "udemy4-c010-s5-20260724")
                self.assertEqual(document["metadata"]["labels"]["app.kubernetes.io/managed-by"], "udemy4")

    def test_bounded_non_host_pods_with_resources(self):
        for document in self.documents:
            if document["kind"] != "Pod":
                continue
            spec = document["spec"]
            self.assertLessEqual(spec["activeDeadlineSeconds"], 600)
            self.assertNotIn("hostNetwork", spec)
            self.assertNotIn("hostPID", spec)
            self.assertNotIn("hostIPC", spec)
            for container in spec["containers"]:
                self.assertIn("requests", container["resources"])
                self.assertIn("limits", container["resources"])

    def test_pending_request_is_unscheduled_not_node_exhaustion(self):
        pending = next(d for d in self.documents if d["metadata"]["name"].endswith("pending-capacity"))
        self.assertEqual(pending["spec"]["containers"][0]["resources"]["requests"]["memory"], "8Gi")
        self.assertEqual(pending["spec"]["restartPolicy"], "Never")

    def test_crashloops_are_bounded_and_low_limit(self):
        crash = [d for d in self.documents if d["kind"] == "Pod" and "crashloop" in d["metadata"]["name"]]
        self.assertEqual(len(crash), 2)
        limits = [d["spec"]["containers"][0]["resources"]["limits"]["memory"] for d in crash]
        self.assertEqual(limits, ["32Mi", "24Mi"])

    def test_read_only_capture_and_exact_cleanup(self):
        capture = (PACKAGE / "scripts" / "capture-evidence.sh").read_text(encoding="utf-8")
        for token in ("kubectl get ", "kubectl describe ", "kubectl logs "):
            self.assertIn(token, capture)
        for token in ("kubectl apply ", "kubectl delete ", "kubectl patch ", "kubectl exec "):
            self.assertNotIn(token, capture)
        cleanup = (PACKAGE / "scripts" / "cleanup-section.sh").read_text(encoding="utf-8")
        self.assertIn('kubectl delete namespace "$NAMESPACE"', cleanup)
        self.assertIn("grep -q 'NotFound'", cleanup)
        self.assertNotIn("--all", cleanup)
        self.assertNotIn("*", cleanup)

    def test_every_external_script_enforces_exact_target(self):
        for name in ("apply-scenarios.sh", "capture-evidence.sh", "cleanup-section.sh"):
            text = (PACKAGE / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("assert_s5_target", text)
        common = (PACKAGE / "scripts" / "common.sh").read_text(encoding="utf-8")
        self.assertIn("get_expected_stack_binding", common)
        self.assertIn("assert_exact_kubernetes_context", common)

    def test_readme_orders_section_before_common_cleanup(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        self.assertLess(readme.index('scripts/cleanup-section.sh"'), readme.index('scripts/delete.sh"'))
        self.assertIn("実請求", readme)

    def test_readme_is_learner_first_and_links_to_the_exact_lab(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "https://github.com/toma1110/udemy-aws-eks-kubernetes-operations-monitoring-handson/"
            "tree/main/labs/s5-pod-resource-first-response",
            readme,
        )
        for internal_term in ("受講者向け既定環境", "固定fixture", "回帰fallback"):
            with self.subTest(internal_term=internal_term):
                self.assertNotIn(internal_term, readme)
        self.assertLess(readme.index("## 1. CloudShellを開く"), readme.index("## 2. 共通EKS環境を作る"))

    def test_readme_bootstraps_or_safely_reuses_the_public_repository(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        required = (
            'export HANDSON_REPO="$HOME/udemy-aws-eks-kubernetes-operations-monitoring-handson"',
            'git clone "$HANDSON_URL" "$HANDSON_REPO"',
            'git -C "$HANDSON_REPO" remote get-url origin',
            'git -C "$HANDSON_REPO" status --porcelain',
            'git -C "$HANDSON_REPO" pull --ff-only',
            'cd "$HANDSON_REPO/labs/s5-pod-resource-first-response"',
        )
        for command in required:
            with self.subTest(command=command):
                self.assertIn(command, readme)
        self.assertLess(
            readme.index('cd "$HANDSON_REPO/labs/s5-pod-resource-first-response"'),
            readme.index("cd ../common-eks"),
        )

    def test_cloudshell_bash_is_the_only_learner_command_environment(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        for token in (
            "AWS CloudShell",
            "ap-northeast-1",
            "aws --version",
            "kubectl version --client",
            'df -h "$HOME"',
            "Regionごとに1 GB",
        ):
            self.assertIn(token, readme)
        self.assertNotIn("```powershell", readme.lower())
        self.assertNotIn(".ps1", readme.lower())
        self.assertEqual(list((PACKAGE / "scripts").glob("*.ps1")), [])

    def test_namespace_assertion_accepts_effective_manifest_labels_and_rejects_drift(self):
        namespace = next(document for document in self.documents if document["kind"] == "Namespace")
        effective_labels = {
            **namespace["metadata"]["labels"],
            "kubernetes.io/metadata.name": namespace["metadata"]["name"],
        }
        expected_labels = {
            "app.kubernetes.io/part-of": "udemy4-c010",
            "app.kubernetes.io/managed-by": "udemy4",
            "udemy4.example/course": "C010",
            "udemy4.example/work-package": "issue-31",
            "udemy4.example/purpose": "training",
            "kubernetes.io/metadata.name": "udemy4-c010-s5-20260724",
        }
        self.assertEqual(expected_labels, effective_labels)
        common = (PACKAGE / "scripts" / "common.sh").read_text(encoding="utf-8")
        self.assertIn(".metadata.labels == {", common)
        for key, value in expected_labels.items():
            expected_source = (
                f'"{key}": $namespace'
                if key == "kubernetes.io/metadata.name"
                else f'"{key}": "{value}"'
            )
            self.assertIn(expected_source, common)
        self.assertNotEqual(expected_labels, {**effective_labels, "unexpected": "reject"})
        self.assertNotEqual(
            expected_labels,
            {**effective_labels, "udemy4.example/work-package": "issue-999"},
        )


if __name__ == "__main__":
    unittest.main()
