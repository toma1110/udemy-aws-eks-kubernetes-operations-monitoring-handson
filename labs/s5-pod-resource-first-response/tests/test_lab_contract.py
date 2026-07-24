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
        capture = (PACKAGE / "scripts" / "capture-evidence.ps1").read_text(encoding="utf-8")
        for token in ('@("get",', '@("describe",', '@("logs",'):
            self.assertIn(token, capture)
        for token in ("kubectl apply ", "kubectl delete ", "kubectl patch ", "kubectl exec ", "Invoke-NativeResult"):
            self.assertNotIn(token, capture)
        cleanup = (PACKAGE / "scripts" / "cleanup-section.ps1").read_text(encoding="utf-8")
        self.assertIn('@("delete", "namespace", $Namespace', cleanup)
        self.assertIn('if ($result.Output -notmatch "NotFound")', cleanup)
        self.assertNotIn("--all", cleanup)
        self.assertNotIn("*", cleanup)

    def test_every_external_script_enforces_exact_target(self):
        for name in ("apply-scenarios.ps1", "capture-evidence.ps1", "cleanup-section.ps1"):
            text = (PACKAGE / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("Assert-S5Target", text)
        common = (PACKAGE / "scripts" / "common.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-ExpectedStackBinding", common)
        self.assertIn("Assert-ExactKubernetesContext", common)

    def test_readme_orders_section_before_common_cleanup(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        self.assertLess(readme.index("./scripts/cleanup-section.ps1"), readme.index("./scripts/delete.ps1"))
        self.assertIn("fixtureは合成データ", readme)
        self.assertIn("実請求", readme)


if __name__ == "__main__":
    unittest.main()
