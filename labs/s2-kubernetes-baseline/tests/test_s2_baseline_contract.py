import json
import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]
NAMESPACE = "udemy4-c010-s2-baseline"
LAB = "s2-baseline"
COMMON_COMMIT = "554b2887e4c2750a57f2cd5264540b6accab95ab"
COMMON_TREE = "4596f883d7d12196c39c15c68da0d4f48ab5c654"


class S2BaselineContractTest(unittest.TestCase):
    def load_yaml(self, name):
        return yaml.safe_load((ROOT / "manifests" / name).read_text(encoding="utf-8"))

    def test_manifest_population_identity_and_selectors(self):
        namespace = self.load_yaml("00-namespace.yaml")
        deployment = self.load_yaml("10-deployment.yaml")
        service = self.load_yaml("20-service.yaml")
        self.assertEqual(NAMESPACE, namespace["metadata"]["name"])
        self.assertEqual(NAMESPACE, deployment["metadata"]["namespace"])
        self.assertEqual(NAMESPACE, service["metadata"]["namespace"])
        for obj in (namespace, deployment, service):
            self.assertEqual(LAB, obj["metadata"]["labels"]["udemy4.example/lab"])
        pod_labels = deployment["spec"]["template"]["metadata"]["labels"]
        for key, value in service["spec"]["selector"].items():
            self.assertEqual(value, pod_labels[key])
        self.assertEqual("ClusterIP", service["spec"]["type"])

    def test_deployment_is_bounded_pinned_and_non_privileged(self):
        deployment = self.load_yaml("10-deployment.yaml")
        self.assertEqual(1, deployment["spec"]["replicas"])
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(
            "public.ecr.aws/docker/library/busybox:1.36.1", container["image"]
        )
        self.assertTrue(container["securityContext"]["runAsNonRoot"])
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertEqual(["ALL"], container["securityContext"]["capabilities"]["drop"])
        self.assertIn("requests", container["resources"])
        self.assertIn("limits", container["resources"])

    def test_binding_is_minimal_and_exact(self):
        binding = json.loads(
            (ROOT / "common-foundation.binding.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {"schema", "common_foundation_commit", "common_foundation_path",
             "common_foundation_tree_oid"},
            set(binding),
        )
        self.assertEqual(COMMON_COMMIT, binding["common_foundation_commit"])
        self.assertEqual(COMMON_TREE, binding["common_foundation_tree_oid"])
        self.assertEqual("labs/common-eks", binding["common_foundation_path"])

    def test_scripts_are_cloudshell_first_and_fail_closed(self):
        scripts = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "scripts").glob("*.sh"))
        }
        for name, text in scripts.items():
            self.assertTrue(text.startswith("#!/usr/bin/env bash\nset -euo pipefail"), name)
            self.assertNotRegex(text, r"\b0\.0\.0\.0/0\b")
        common = scripts["common.sh"]
        self.assertIn("CloudShell environment required", common)
        self.assertIn('rev-parse "HEAD:$common_path"', common)
        cleanup = scripts["cleanup-section.sh"]
        self.assertIn("-o json --ignore-not-found", cleanup)
        self.assertNotIn("grep", cleanup)
        wrapper = scripts["delete-common-after-s2.sh"]
        self.assertIn("../../common-eks/scripts/delete.sh", wrapper)
        self.assertNotIn("verify-cleanup.sh", wrapper)
        capture = scripts["verify-and-capture.sh"]
        for token in (
            "(.items | length) == 1",
            '.status.phase == "Running"',
            ".status.readyReplicas == 1",
            ".status.availableReplicas == 1",
            "grep -Fqx 'baseline-started'",
            "grep -Fqx 'baseline-heartbeat'",
        ):
            self.assertIn(token, capture)

    def test_evidence_template_is_not_an_execution_claim(self):
        evidence = json.loads(
            (ROOT / "evidence" / "live-verification.template.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("not-run", evidence["result"])
        self.assertEqual("ap-northeast-1", evidence["execution_environment"]["region"])
        self.assertFalse(evidence["cleanup"]["section_namespace_absent"])
        self.assertTrue(evidence["not_run_reason"])

    def test_readme_complete_flow_and_public_wording(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for token in (
            "aws --version",
            "kubectl version --client",
            "aws sts get-caller-identity",
            'df -h "$HOME"',
            "apply-workload.sh",
            "verify-and-capture.sh",
            "cleanup-section.sh",
            "delete-common-after-s2.sh",
            "料金",
            "NotFound",
        ):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
