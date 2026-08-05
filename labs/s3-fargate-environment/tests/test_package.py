import hashlib
import json
import sys
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

import render_validate


class PackageTests(unittest.TestCase):
    def test_local_contract(self):
        render_validate.validate()

    def test_inventory_matches_current_bytes(self):
        inventory = json.loads((PACKAGE / "package-inventory.json").read_text(encoding="utf-8"))
        listed = inventory["files"]
        actual = {
            path.relative_to(PACKAGE).as_posix()
            for path in PACKAGE.rglob("*")
            if path.is_file()
            and path.name != "package-inventory.json"
            and "__pycache__" not in path.parts
        }
        self.assertEqual(set(listed), actual)
        for relative, expected in listed.items():
            with self.subTest(relative=relative):
                actual_hash = hashlib.sha256((PACKAGE / relative).read_bytes()).hexdigest()
                self.assertEqual(expected, actual_hash)

    def test_no_credentials_or_local_paths(self):
        prohibited = (
            "AK" + "IA",
            "AS" + "IA",
            "C:" + "\\\\Users\\\\",
            "/" + "Users/",
            "BEGIN PRIVATE" + " KEY",
        )
        for path in PACKAGE.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for marker in prohibited:
                with self.subTest(path=path.name, marker=marker):
                    self.assertNotIn(marker, text)

    def test_lecture_scope_and_recovery_are_explicit(self):
        text = (PACKAGE / "README.md").read_text(encoding="utf-8")
        for lecture in ("s3-l2", "s3-l3", "s3-l4", "s3-l5", "s3-l6"):
            self.assertIn(lecture, text)
        for term in ("Running", "1/1", "restart", "障害差分", "復旧値", "s10-l1-cleanup"):
            self.assertIn(term, text)

    def test_images_are_version_pinned(self):
        app = (PACKAGE / "templates/application.yaml").read_text(encoding="utf-8")
        irsa = (PACKAGE / "templates/irsa-check.yaml").read_text(encoding="utf-8")
        self.assertIn("amazonlinux:2023.8.20250721.2", app)
        self.assertIn("aws-cli:2.27.49", irsa)
        self.assertNotIn(":latest", app + irsa)

    def test_preflight_collision_and_runtime_safeguards_are_explicit(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        cluster = (PACKAGE / "templates/cluster.yaml").read_text(encoding="utf-8")
        baseline = (PACKAGE / "baseline-record.md").read_text(encoding="utf-8")
        for term in ("system-coredns", "kube-system", "k8s-app: kube-dns"):
            self.assertIn(term, cluster)
        for term in (
            "CoreDNS Deployment", "実際", "aws --version", "eksctl version",
            "kubectl version --client", "Python 3.11", "canonical固定名",
            "権限やcredentialを追加・変更せず停止", "job/irsa-describe-cluster",
            "0.215.0以上", "fargate-getting-started.html",
            "aws iam get-role --role-name eks-fargate-ops-irsa-reader",
            "NoSuchEntity", "NAMESPACE_CHECK", "(NotFound)",
            "canonical namespace already exists", "namespace absence was not proven",
        ):
            self.assertIn(term, readme)
        for term in ("CoreDNS", "IRSA check image version", "`eks:DescribeCluster` result"):
            self.assertIn(term, baseline)

    def test_preflight_fail_closed_control_flow_precedes_mutation(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        preflight = readme.split("canonical固定名のcluster", 1)[1].split("## 2.", 1)[0]
        cluster_create = readme.split("## 3.", 1)[1].split("期待状態:", 1)[0]

        for term in (
            'if CLUSTER_CHECK="$(aws eks describe-cluster',
            "An error occurred (ResourceNotFoundException) when calling the DescribeCluster operation:",
            'No cluster found for name: $CLUSTER_NAME.',
            'if IAM_POLICY_CHECK="$(aws iam get-policy',
            "An error occurred (NoSuchEntity) when calling the GetPolicy operation:",
            'grep -Fq "$CANONICAL_IRSA_POLICY_ARN"',
            "grep -Fq 'was not found'",
            'if LOG_GROUP_MATCH_COUNT="$(aws logs describe-log-groups',
            '[[ "$LOG_GROUP_MATCH_COUNT" == "0" ]]',
            "log group absence was not proven",
        ):
            self.assertIn(term, preflight)
        self.assertLess(preflight.index("if CLUSTER_CHECK="), preflight.index("if IAM_POLICY_CHECK="))
        self.assertLess(preflight.index("if IAM_POLICY_CHECK="), preflight.index("if LOG_GROUP_MATCH_COUNT="))
        self.assertNotIn("create-log-group", preflight)
        self.assertNotIn("put-retention-policy", preflight)

        self.assertIn("if eksctl create cluster -f templates/cluster.yaml; then", cluster_create)
        self.assertIn("cluster creation failed; do not run update-kubeconfig or later mutation commands", cluster_create)
        self.assertLess(
            cluster_create.index("if eksctl create cluster -f templates/cluster.yaml; then"),
            cluster_create.index('aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"'),
        )
        self.assertIn("exit 1\nfi\nif aws eks update-kubeconfig", cluster_create)

    def test_context_and_logging_mutations_are_success_gated(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        cluster_create = readme.split("## 3.", 1)[1].split("期待状態:", 1)[0]
        logging = readme.split("## 5.", 1)[1].split("CloudWatch Logsで", 1)[0]

        update = 'if aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"; then'
        expected = 'export EXPECTED_EKS_CONTEXT="arn:aws:eks:${AWS_REGION}:${CONTEXT_ACCOUNT_ID}:cluster/${CLUSTER_NAME}"'
        exact = '[[ "$CURRENT_CONTEXT" == "$EXPECTED_EKS_CONTEXT" ]]'
        namespace_lookup = 'if NAMESPACE_CHECK="$(kubectl get namespace'
        for term in (
            update,
            "update-kubeconfig failed; do not run namespace lookup or kubectl mutation commands",
            expected,
            exact,
            "current context is empty, unreadable, or not exactly the intended EKS context ARN",
            namespace_lookup,
        ):
            self.assertIn(term, cluster_create)
        self.assertLess(cluster_create.index(update), cluster_create.index(expected))
        self.assertLess(cluster_create.index(expected), cluster_create.index(exact))
        self.assertLess(cluster_create.index(exact), cluster_create.index(namespace_lookup))
        self.assertNotIn('[[ "$CURRENT_CONTEXT" == *"$EXPECTED_EKS_CONTEXT"* ]]', cluster_create)

        create = 'if aws logs create-log-group --region "$AWS_REGION"'
        retention = '  if ! aws logs put-retention-policy --region "$AWS_REGION"'
        role_policy = '  if ! aws iam put-role-policy --role-name "$POD_EXECUTION_ROLE_NAME"'
        configmap = '  if ! kubectl apply -f templates/logging.yaml; then'
        restart = '  if ! kubectl rollout restart deployment/baseline-app -n "$NAMESPACE"; then'
        create_failure = "else\n  printf 'STOP: create-log-group failed"
        for term in (create, retention, role_policy, configmap, restart, create_failure):
            self.assertIn(term, logging)
        self.assertLess(logging.index(create), logging.index(retention))
        self.assertLess(logging.index(retention), logging.index(role_policy))
        self.assertLess(logging.index(role_policy), logging.index(configmap))
        self.assertLess(logging.index(configmap), logging.index(restart))
        self.assertLess(logging.index(restart), logging.index(create_failure))
        self.assertNotIn('\naws logs put-retention-policy', logging)
        self.assertNotIn('\naws iam put-role-policy', logging)
        self.assertNotIn('\nkubectl apply -f templates/logging.yaml', logging)

    def test_irsa_rbac_dependencies_are_exact_and_fail_closed(self):
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        irsa = readme.split("## 6.", 1)[1].split("IRSA Jobは", 1)[0]
        gates = (
            'if eksctl utils associate-iam-oidc-provider --region "$AWS_REGION"',
            'if IRSA_ACCOUNT_ID="$(aws sts get-caller-identity',
            'if IRSA_POLICY_ARN="$(aws iam create-policy',
            '[[ "$IRSA_POLICY_ARN" =~ ^arn:aws:iam::[0-9]{12}:policy/eks-fargate-ops-describe-cluster$ && "$IRSA_POLICY_ARN" == "$EXPECTED_IRSA_POLICY_ARN" ]]',
            'if eksctl create iamserviceaccount --region "$AWS_REGION"',
            'if kubectl apply -f templates/rbac.yaml; then',
            'if kubectl apply -f templates/irsa-check.yaml; then',
            'if kubectl wait --for=condition=complete job/irsa-describe-cluster',
            'if IRSA_JOB_LOG="$(kubectl logs job/irsa-describe-cluster',
            '[[ "$IRSA_JOB_LOG" == "ACTIVE" ]]',
            'if IRSA_JOB_COMPLETE="$(kubectl get job irsa-describe-cluster',
            '[[ "$IRSA_JOB_COMPLETE" == "True" ]]',
            'if RBAC_CAN_GET="$(kubectl auth can-i get configmaps',
            '[[ "$RBAC_CAN_GET" == "yes" ]]',
            'if RBAC_CAN_DELETE="$(kubectl auth can-i delete configmaps',
            '[[ "$RBAC_CAN_DELETE" == "no" ]]',
        )
        for gate in gates:
            self.assertIn(gate, irsa)
        for earlier, later in zip(gates, gates[1:]):
            self.assertLess(irsa.index(earlier), irsa.index(later))

        for failure in (
            "OIDC provider association failed",
            "current STS account ID is empty, malformed, or unavailable",
            "create-policy returned an empty, malformed, wrong-account, or wrong-name ARN",
            "create-policy failed",
            "IRSA ServiceAccount creation failed",
            "RBAC apply failed",
            "IRSA Job apply failed",
            "IRSA Job wait failed or timed out",
            "IRSA Job log failed or was not exactly ACTIVE",
            "IRSA Job Complete condition was empty, unreadable, or not exactly True",
            "RBAC get check failed or was not exactly yes",
            "RBAC delete check failed or was not exactly no",
        ):
            self.assertIn(failure, irsa)
            self.assertIn("exit 1", irsa.split(failure, 1)[1].split("fi", 1)[0])
        self.assertIn("partial resource", irsa)
        self.assertIn("inline削除せず", irsa)
        for unguarded in (
            "\neksctl utils associate-iam-oidc-provider",
            "\naws iam create-policy",
            "\neksctl create iamserviceaccount",
            "\nkubectl apply -f templates/rbac.yaml",
            "\nkubectl apply -f templates/irsa-check.yaml",
        ):
            self.assertNotIn(unguarded, irsa)


if __name__ == "__main__":
    unittest.main()
