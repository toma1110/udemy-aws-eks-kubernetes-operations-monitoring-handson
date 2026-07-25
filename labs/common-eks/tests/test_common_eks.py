import hashlib
import copy
import json
import os
import re
import shlex
import subprocess
import sys
import types
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def wsl_path(path):
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    return f"/mnt/{drive}/{resolved.as_posix().split(':', 1)[1].lstrip('/')}"


def run_bash(body):
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


class CfnLoader(yaml.SafeLoader):
    pass


def unknown(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


CfnLoader.add_multi_constructor("!", unknown)


class CommonEksContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "template.yaml").read_text(encoding="utf-8")
        cls.template = yaml.load(cls.text, Loader=CfnLoader)
        cls.guard_text = (ROOT / "cleanup-guard.yaml").read_text(encoding="utf-8")
        cls.guard_template = yaml.load(cls.guard_text, Loader=CfnLoader)
        cls.rollback_fixture = json.loads(
            (ROOT / "fixtures" / "rollback-complete-stack.json").read_text(
                encoding="utf-8"
            )
        )
        cls.scripts = {
            path.name: path.read_text(encoding="utf-8")
            for path in (ROOT / "scripts").glob("*.sh")
        }
        cls.joined = "\n".join(cls.scripts.values())

    def test_cloudshell_bash_is_the_only_learner_script_contract(self):
        self.assertEqual(
            {
                "common.sh",
                "create.sh",
                "delete.sh",
                "preflight.sh",
                "recover-cidr.sh",
                "status.sh",
                "verify-cleanup.sh",
            },
            set(self.scripts),
        )
        self.assertFalse(list((ROOT / "scripts").glob("*.ps1")))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
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
            self.assertIn(token, readme)

    def test_template_parses_and_has_required_resources(self):
        resources = self.template["Resources"]
        types = [resource["Type"] for resource in resources.values()]
        for required in (
            "AWS::EC2::VPC",
            "AWS::EC2::InternetGateway",
            "AWS::EKS::Cluster",
            "AWS::EKS::Nodegroup",
            "AWS::EC2::LaunchTemplate",
        ):
            self.assertIn(required, types)
        self.assertEqual(types.count("AWS::EC2::Subnet"), 2)
        self.assertNotIn("AWS::EC2::NatGateway", types)

    def test_node_join_regression_private_and_restricted_public_endpoints(self):
        config = self.template["Resources"]["EksCluster"]["Properties"]["ResourcesVpcConfig"]
        self.assertIs(config["EndpointPrivateAccess"], True)
        self.assertIs(config["EndpointPublicAccess"], True)
        self.assertEqual(config["PublicAccessCidrs"], ["ApiPublicAccessCidr"])
        self.assertNotIn(
            "0.0.0.0/0",
            str(config["PublicAccessCidrs"]),
        )
        common = self.scripts["common.sh"]
        for token in (
            "endpointPrivateAccess",
            "endpointPublicAccess",
            "publicAccessCidrs must contain exactly one value",
        ):
            self.assertIn(token, common)

    def test_low_cost_deadline_guard_has_private_kubernetes_cleanup_gates(self):
        resources = self.guard_template["Resources"]
        resource_types = {resource["Type"] for resource in resources.values()}
        self.assertNotIn("AWS::EC2::NatGateway", resource_types)
        self.assertNotIn("AWS::EC2::EIP", resource_types)
        self.assertIn("AWS::Lambda::Function", resource_types)
        self.assertIn("AWS::StepFunctions::StateMachine", resource_types)

        schedule = resources["AutomaticCleanupSchedule"]["Properties"]
        self.assertEqual("CleanupStateMachine", schedule["Target"]["Arn"])
        self.assertEqual(
            '{"contract":"udemy4-c010-deadline-cleanup-v2"}',
            schedule["Target"]["Input"],
        )
        scheduler_policy = resources["CleanupSchedulerRole"]["Properties"]["Policies"][
            0
        ]["PolicyDocument"]["Statement"][0]
        self.assertEqual("states:StartExecution", scheduler_policy["Action"])
        self.assertNotIn("cloudformation:DeleteStack", str(scheduler_policy))
        self.assertNotIn(
            "cloudformation:DeleteStack",
            str(resources["CleanupHandlerRole"]),
        )

        definition = json.loads(
            resources["CleanupStateMachine"]["Properties"]["DefinitionString"]
        )
        states = definition["States"]
        exact_log_group_arn = (
            "arn:${AWS::Partition}:logs:ap-northeast-1:${AccountId}:"
            "log-group:/udemy4/c010/s4/20260725"
        )
        state_machine_statements = resources["CleanupStateMachineRole"]["Properties"][
            "Policies"
        ][0]["PolicyDocument"]["Statement"]
        list_tags_statement = next(
            statement
            for statement in state_machine_statements
            if statement["Action"] == "logs:ListTagsForResource"
        )
        delete_log_statement = next(
            statement
            for statement in state_machine_statements
            if statement["Action"] == "logs:DeleteLogGroup"
        )
        self.assertEqual(exact_log_group_arn, list_tags_statement["Resource"])
        self.assertFalse(list_tags_statement["Resource"].endswith(":*"))
        self.assertEqual(f"{exact_log_group_arn}:*", delete_log_statement["Resource"])
        self.assertTrue(delete_log_statement["Resource"].endswith(":*"))
        self.assertNotIn("logs:ListTagsLogGroup", self.guard_text)
        self.assertNotEqual(f"{exact_log_group_arn}:*", list_tags_statement["Resource"])
        self.assertNotEqual(exact_log_group_arn, delete_log_statement["Resource"])
        self.assertEqual(
            "arn:${AWS::Partition}:states:::aws-sdk:cloudwatchlogs:listTagsForResource",
            states["GetSectionLogTags"]["Resource"],
        )
        self.assertEqual(
            {"ResourceArn": exact_log_group_arn},
            states["GetSectionLogTags"]["Parameters"],
        )
        self.assertLess((ROOT / "cleanup-guard.yaml").stat().st_size, 51200)
        for state in states.values():
            targets = []
            if "Next" in state:
                targets.append(state["Next"])
            if "Default" in state:
                targets.append(state["Default"])
            targets.extend(choice["Next"] for choice in state.get("Choices", []))
            targets.extend(catcher["Next"] for catcher in state.get("Catch", []))
            for target in targets:
                self.assertIn(target, states)
        self.assertEqual("MissingSectionGate", states["MissingSectionGate"]["Error"])
        self.assertEqual("DeleteCommon", states["CommonStackKnown"]["Choices"][0]["Next"])
        self.assertEqual(
            "udemy4-c010-deadline-cleanup-v2:kubernetes-absent",
            states["SectionGateReady"]["Choices"][0]["StringEquals"],
        )
        self.assertEqual(
            "arn:${AWS::Partition}:states:::aws-sdk:cloudformation:deleteStack",
            states["DeleteCommon"]["Resource"],
        )
        self.assertEqual(
            "arn:${AWS::Partition}:states:::aws-sdk:cloudformation:deleteStack",
            states["RemoveGuard"]["Resource"],
        )
        self.assertEqual("RemoveGuard", states["FinalSectionLogAbsent"]["Default"])
        self.assertEqual(
            "DirectDeleteBypass",
            states["DescribeClusterWithoutStack"]["Next"],
        )
        failed_payload = states["ValidateStackWithoutCluster"]["Parameters"]["Payload"]
        self.assertEqual("validate_failed_stack", failed_payload["action"])
        self.assertEqual("SectionAlreadyAbsent", states["ValidateStackWithoutCluster"]["Next"])
        self.assertEqual("ValidateCommon", states["DescribeCluster"]["Next"])
        self.assertEqual(
            "ValidateStackWithoutCluster",
            states["DescribeCluster"]["Catch"][0]["Next"],
        )
        for name in ("DescribeCommon", "DeleteCommon", "PollCommonDelete"):
            self.assertEqual(
                ["CloudFormation.ValidationErrorException"],
                states[name]["Catch"][0]["ErrorEquals"],
            )
        attach = states["AttachCleanupHandler"]["Parameters"]["VpcConfig"]
        self.assertEqual(
            "$.validation.Payload.subnet_ids",
            attach["SubnetIds.$"],
        )
        self.assertEqual(
            {"SubnetIds": [], "SecurityGroupIds": []},
            states["DetachCleanupHandler"]["Parameters"]["VpcConfig"],
        )

        common_resources = self.template["Resources"]
        access = common_resources["CleanupHandlerAccessEntry"]["Properties"]
        self.assertNotIn("AccessPolicies", access)
        self.assertEqual(["udemy4:c010:s4-cleanup"], access["KubernetesGroups"])
        self.assertNotIn(
            "AmazonEKSClusterAdminPolicy", self.text + self.guard_text
        )
        rbac = yaml.safe_load(self.template["Outputs"]["CleanupRbacManifest"]["Value"])
        self.assertEqual("List", rbac["kind"])
        objects = {(item["kind"], item["metadata"]["name"]): item for item in rbac["items"]}
        job_role = objects[("Role", "udemy4-s4-cleanup-job")]
        self.assertEqual("udemy4-s4-logs", job_role["metadata"]["namespace"])
        self.assertEqual(
            [{
                "apiGroups": ["batch"],
                "resources": ["jobs"],
                "resourceNames": ["s4-log-generator"],
                "verbs": ["get", "delete"],
            }],
            job_role["rules"],
        )
        namespace_role = objects[
            ("ClusterRole", "udemy4-c010-s4-cleanup-namespace")
        ]
        self.assertEqual(
            [{
                "apiGroups": [""],
                "resources": ["namespaces"],
                "resourceNames": ["udemy4-s4-logs"],
                "verbs": ["get", "delete"],
            }],
            namespace_role["rules"],
        )
        for binding_kind, binding_name, role_kind, role_name in (
            ("RoleBinding", "udemy4-s4-cleanup-job", "Role", "udemy4-s4-cleanup-job"),
            (
                "ClusterRoleBinding",
                "udemy4-c010-s4-cleanup-namespace",
                "ClusterRole",
                "udemy4-c010-s4-cleanup-namespace",
            ),
        ):
            binding = objects[(binding_kind, binding_name)]
            self.assertEqual(
                [{
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Group",
                    "name": "udemy4:c010:s4-cleanup",
                }],
                binding["subjects"],
            )
            self.assertEqual(role_kind, binding["roleRef"]["kind"])
            self.assertEqual(role_name, binding["roleRef"]["name"])
        ingress = common_resources["CleanupHandlerEksIngress"]["Properties"]
        self.assertEqual(443, ingress["FromPort"])
        self.assertEqual("CleanupHandlerSecurityGroup", ingress["SourceSecurityGroupId"])

    def test_deadline_handler_behavior_rejects_early_and_direct_delete_invocation(self):
        code = self.guard_template["Resources"]["CleanupHandler"]["Properties"]["Code"][
            "ZipFile"
        ]
        fake_boto3 = types.ModuleType("boto3")
        fake_botocore = types.ModuleType("botocore")
        fake_signers = types.ModuleType("botocore.signers")
        fake_signers.RequestSigner = object
        saved_modules = {
            name: sys.modules.get(name)
            for name in ("boto3", "botocore", "botocore.signers")
        }
        saved_account = os.environ.get("EXPECTED_ACCOUNT")
        saved_schedule = os.environ.get("SCHEDULE_EXPRESSION")
        try:
            sys.modules["boto3"] = fake_boto3
            sys.modules["botocore"] = fake_botocore
            sys.modules["botocore.signers"] = fake_signers
            os.environ["EXPECTED_ACCOUNT"] = "123456789012"
            os.environ["SCHEDULE_EXPRESSION"] = "at(2999-01-01T00:00:00)"
            early = {}
            exec(compile(code, "cleanup-handler.py", "exec"), early)
            with self.assertRaisesRegex(RuntimeError, "before the exact deadline"):
                early["assert_trigger"](
                    {"contract": "udemy4-c010-deadline-cleanup-v2"}
                )

            os.environ["SCHEDULE_EXPRESSION"] = "at(2020-01-01T00:00:00)"
            post_deadline = {}
            exec(compile(code, "cleanup-handler.py", "exec"), post_deadline)
            failed = post_deadline["validate_failed_stack"](
                self.rollback_fixture["Stacks"][0]
            )
            self.assertEqual("ready", failed["status"])
            for mutation in ("status", "tag", "account", "name"):
                rejected = copy.deepcopy(self.rollback_fixture["Stacks"][0])
                if mutation == "status":
                    rejected["StackStatus"] = "UPDATE_ROLLBACK_COMPLETE"
                elif mutation == "tag":
                    rejected["Tags"].append({"Key": "Unexpected", "Value": "reject"})
                elif mutation == "account":
                    rejected["StackId"] = rejected["StackId"].replace(
                        "123456789012", "999999999999"
                    )
                else:
                    rejected["StackName"] = "other"
                with self.assertRaises(RuntimeError):
                    post_deadline["validate_failed_stack"](rejected)
            post_deadline["assert_labels"](
                {
                    "metadata": {
                        "labels": {
                            "course": "c010",
                            "section": "s4",
                            "managed-by": "udemy4",
                            "kubernetes.io/metadata.name": "udemy4-s4-logs",
                        }
                    }
                },
                "Namespace",
            )
            with self.assertRaisesRegex(
                RuntimeError, "Namespace exact ownership labels mismatch"
            ):
                post_deadline["assert_labels"](
                    {
                        "metadata": {
                            "labels": {
                                "course": "c010",
                                "section": "s4",
                                "managed-by": "udemy4",
                                "kubernetes.io/metadata.name": "udemy4-s4-logs",
                                "unexpected-user-label": "reject",
                            }
                        }
                    },
                    "Namespace",
                )
            with self.assertRaisesRegex(RuntimeError, "direct-delete"):
                post_deadline["handler"](
                    {
                        "contract": "udemy4-c010-deadline-cleanup-v2",
                        "action": "delete_common",
                    },
                    None,
                )
        finally:
            for name, module in saved_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
            if saved_account is None:
                os.environ.pop("EXPECTED_ACCOUNT", None)
            else:
                os.environ["EXPECTED_ACCOUNT"] = saved_account
            if saved_schedule is None:
                os.environ.pop("SCHEDULE_EXPRESSION", None)
            else:
                os.environ["SCHEDULE_EXPRESSION"] = saved_schedule

    def test_version_gates_use_semantic_behavior(self):
        accepted = run_bash(
            "assert_aws_cli_minimum_text 'aws-cli/2.12.3 Python/3.11'; "
            "assert_aws_cli_minimum_text 'aws-cli/2.13.0 Python/3.11'; "
            "assert_kubectl_minor_compatible v1.31.2 1.30; "
            "assert_kubectl_minor_compatible v1.29.9 1.30"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        for rejected in (
            "assert_aws_cli_minimum_text 'aws-cli/2.12.2 Python/3.11'",
            "assert_aws_cli_minimum_text 'aws-cli/1.99.99 Python/3.11'",
            "assert_kubectl_minor_compatible v1.32.0 1.30",
            "assert_kubectl_minor_compatible v2.30.0 1.30",
        ):
            result = run_bash(rejected)
            self.assertNotEqual(0, result.returncode, rejected)

    def test_runtime_endpoint_gate_rejects_world_mismatch_and_drift(self):
        accepted = run_bash(
            "assert_runtime_endpoint_values true true 198.51.100.10/32 198.51.100.10/32"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        for rejected in (
            "assert_runtime_endpoint_values false true 198.51.100.10/32 198.51.100.10/32",
            "assert_runtime_endpoint_values true true 198.51.100.10/32 198.51.100.11/32",
            "assert_runtime_endpoint_values true true 0.0.0.0/0 0.0.0.0/0",
            "assert_runtime_endpoint_values true true 198.51.100.10/32 198.51.100.10/32 198.51.100.11/32",
        ):
            result = run_bash(rejected)
            self.assertNotEqual(0, result.returncode, rejected)

    def test_exact_name_region_tags_and_account_binding(self):
        for token in (
            'REGION="ap-northeast-1"',
            'STACK_NAME="udemy4-c010-common-20260724"',
            'CLUSTER_NAME="udemy4-c010-common-20260724"',
            "AWS_ACCOUNT_ID",
            "STS account does not equal AWS_ACCOUNT_ID",
            "Course=C010",
            "WorkPackage=c010-common-eks",
            "ManagedBy=udemy4",
            "Purpose=training",
            "TemplateContract",
        ):
            self.assertIn(token, self.joined)

    def test_api_cidr_has_no_default_and_rejects_world(self):
        cidr = self.template["Parameters"]["ApiPublicAccessCidr"]
        self.assertNotIn("Default", cidr)
        self.assertIn("0\\.0\\.0\\.0/0", cidr["AllowedPattern"])
        self.assertIn('"0.0.0.0/0"', self.scripts["common.sh"])

    def test_one_t3_medium_and_20_gib_gp3(self):
        node = self.template["Resources"]["ManagedNodeGroup"]["Properties"]
        self.assertEqual(node["InstanceTypes"], ["t3.medium"])
        self.assertEqual(
            node["ScalingConfig"],
            {"DesiredSize": 1, "MinSize": 1, "MaxSize": 1},
        )
        ebs = self.template["Resources"]["NodeLaunchTemplate"]["Properties"][
            "LaunchTemplateData"
        ]["BlockDeviceMappings"][0]["Ebs"]
        self.assertEqual(ebs["VolumeSize"], 20)
        self.assertEqual(ebs["VolumeType"], "gp3")
        self.assertTrue(ebs["DeleteOnTermination"])

    def test_minimum_role_policy_set_is_explicit(self):
        cluster = self.template["Resources"]["ClusterRole"]["Properties"]["ManagedPolicyArns"]
        node = self.template["Resources"]["NodeRole"]["Properties"]["ManagedPolicyArns"]
        self.assertEqual(cluster, ["arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"])
        self.assertEqual(
            node,
            [
                "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
                "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPullOnly",
                "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
            ],
        )
        self.assertNotIn('"Action": "*"', self.text)

    def test_guard_precedes_common_and_deadline_is_bounded(self):
        create = self.scripts["create.sh"]
        self.assertLess(
            create.index('--stack-name "$GUARD_STACK_NAME"'),
            create.index('--stack-name "$STACK_NAME"'),
        )
        self.assertLess(
            create.index("get_expected_guard_binding"),
            create.index('--stack-name "$STACK_NAME"'),
        )
        self.assertEqual(2, create.count("cloudformation create-stack"))
        self.assertEqual(2, create.count("cloudformation wait stack-create-complete"))
        self.assertNotIn("cloudformation deploy", create)
        self.assertNotIn("cloudformation update-stack", create)
        self.assertIn("AlreadyExistsException", create)
        self.assertIn("refusing to update or adopt", create)
        self.assertNotIn("delete-stack", create)
        update_scripts = [
            name
            for name, body in self.scripts.items()
            if "cloudformation update-stack" in body
        ]
        self.assertEqual(["recover-cidr.sh"], update_scripts)
        common = self.scripts["common.sh"]
        for token in (
            "CLEANUP_DEADLINE_UTC",
            "datetime.timedelta(minutes=15)",
            "datetime.timedelta(hours=6)",
            "AVAILABILITY_ZONE_A",
            "AVAILABILITY_ZONE_B",
            "No EKS cluster quota headroom",
        ):
            self.assertIn(token, common)

    def test_cloudshell_cidr_recovery_is_exact_and_non_adopting(self):
        recovery = self.scripts["recover-cidr.sh"]
        for token in (
            "get_expected_guard_binding",
            "Existing runtime endpoint does not match",
            "Common stack parameter set mismatch",
            "ParameterKey=$key,ParameterValue=$new_cidr",
            "UsePreviousValue=true",
            "cloudformation update-stack",
            "cloudformation wait stack-update-complete",
            "get_expected_stack_binding",
            "assert_exact_kubernetes_context",
        ):
            self.assertIn(token, recovery)
        self.assertLess(
            recovery.index("assert_exact_tag_map"),
            recovery.index("cloudformation update-stack"),
        )
        self.assertLess(
            recovery.index("cloudformation wait stack-update-complete"),
            recovery.index("get_expected_stack_binding"),
        )
        accepted = run_bash(
            "assert_runtime_endpoint_values true true 198.51.100.10/32 198.51.100.10/32"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        for rejected in (
            "assert_runtime_endpoint_values true true 198.51.100.10/32 0.0.0.0/0",
            "assert_runtime_endpoint_values true true 198.51.100.10/32 198.51.100.10/32 198.51.100.11/32",
        ):
            self.assertNotEqual(0, run_bash(rejected).returncode)

    def test_rollback_complete_fixture_and_manual_recovery_are_fail_closed(self):
        fixture = json.dumps(self.rollback_fixture, separators=(",", ":"))
        accepted = run_bash(
            "export AWS_ACCOUNT_ID=123456789012; "
            f"assert_failed_stack_document {shlex.quote(fixture)} >/dev/null; "
            "assert_aws_identity(){ :; }; aws_exact_not_found(){ return 0; }; "
            f"get_failed_stack_binding {shlex.quote(fixture)}; "
            "require_common_cleanup_gate"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        active_cluster = run_bash(
            "export AWS_ACCOUNT_ID=123456789012; "
            "assert_aws_identity(){ :; }; aws_exact_not_found(){ return 1; }; "
            f"get_failed_stack_binding {shlex.quote(fixture)}"
        )
        self.assertNotEqual(0, active_cluster.returncode)
        for mutation in ("status", "tag", "account", "name"):
            rejected = copy.deepcopy(self.rollback_fixture)
            stack = rejected["Stacks"][0]
            if mutation == "status":
                stack["StackStatus"] = "UPDATE_ROLLBACK_COMPLETE"
            elif mutation == "tag":
                stack["Tags"].append({"Key": "Unexpected", "Value": "reject"})
            elif mutation == "account":
                stack["StackId"] = stack["StackId"].replace(
                    "123456789012", "999999999999"
                )
            else:
                stack["StackName"] = "other"
            result = run_bash(
                "export AWS_ACCOUNT_ID=123456789012; "
                f"assert_failed_stack_document {shlex.quote(json.dumps(rejected))}"
            )
            self.assertNotEqual(0, result.returncode, mutation)

        delete = self.scripts["delete.sh"]
        self.assertIn('[[ "$status" == "ROLLBACK_COMPLETE" ]]', delete)
        self.assertIn('get_failed_stack_binding "$stacks"', delete)
        self.assertLess(
            delete.index('get_failed_stack_binding "$stacks"'),
            delete.index("cloudformation delete-stack"),
        )
        self.assertLess(
            delete.index("cloudformation wait stack-delete-complete"),
            delete.index('source "$SCRIPT_DIR/verify-cleanup.sh"'),
        )
        self.assertIn("require_common_cleanup_gate", self.scripts["verify-cleanup.sh"])

    def test_cleanup_is_fail_closed_and_guard_is_removed_last(self):
        verify = self.scripts["verify-cleanup.sh"]
        for token in (
            "describe-stacks",
            "describe-cluster",
            "describe-instances",
            "describe-volumes",
            "describe-network-interfaces",
            "describe-log-groups",
            "Cleanup verification failed closed",
            "get_expected_guard_binding",
            "scheduler get-schedule",
            "Section s4 log group remains",
            "require_common_cleanup_gate",
            "must only be sourced by delete.sh",
        ):
            self.assertIn(token, verify)
        self.assertLess(
            verify.index('[[ "${BASH_SOURCE[0]}" == "$0" ]]'),
            verify.index("require_common_cleanup_gate"),
        )
        self.assertLess(
            verify.index("if ((${#failures[@]}))"),
            verify.index("get_expected_guard_binding"),
        )
        self.assertLess(
            verify.index("get_expected_guard_binding"),
            verify.index("cloudformation delete-stack"),
        )
        common = self.scripts["common.sh"]
        delete = self.scripts["delete.sh"]
        for token in (
            "kubectl get namespace udemy4-s4-logs",
            "kubectl get job s4-log-generator -n udemy4-s4-logs",
            'select(.logGroupName == "/udemy4/c010/s4/20260725")',
            "SECTION_S4_CLEANUP_GATE_PASSED",
        ):
            self.assertIn(token, common)
        self.assertLess(
            delete.index("assert_section_s4_residuals_absent"),
            delete.index("cloudformation delete-stack"),
        )
        self.assertLess(
            delete.index("cloudformation wait stack-delete-complete"),
            delete.index('source "$SCRIPT_DIR/verify-cleanup.sh"'),
        )

    def test_cleanup_gate_cannot_be_skipped_or_replayed_for_another_binding(self):
        result = run_bash(
            "export AWS_ACCOUNT_ID=123456789012 API_PUBLIC_ACCESS_CIDR=198.51.100.10/32; "
            "printf -v expected '%s|%s|%s|%s|%s|%s' "
            '"$AWS_ACCOUNT_ID" "$REGION" "$CLUSTER_NAME" "$API_PUBLIC_ACCESS_CIDR" '
            "'udemy4-s4-logs' '/udemy4/c010/s4/20260725'; "
            "unset SECTION_S4_CLEANUP_GATE_PASSED; "
            "if require_section_s4_cleanup_gate; then exit 20; fi; "
            "SECTION_S4_CLEANUP_GATE_PASSED='wrong-binding'; "
            "if require_section_s4_cleanup_gate; then exit 21; fi; "
            "SECTION_S4_CLEANUP_GATE_PASSED=$expected; "
            "require_section_s4_cleanup_gate"
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_explicit_not_found_rejects_permission_and_network_errors(self):
        common = self.scripts["common.sh"]
        for token in (
            "aws_exact_not_found",
            "AccessDenied",
            "Unauthorized",
            "ExpiredToken",
            "InvalidClientToken",
            "Could not connect",
        ):
            self.assertIn(token, common)

    def test_no_dangerous_wildcard_delete(self):
        self.assertNotRegex(
            self.joined,
            r"\b(delete|remove)[^\n]*(--all|\*|all-resources)",
        )
        self.assertNotIn(
            "0.0.0.0/0",
            self.template["Resources"]["EksCluster"]["Properties"][
                "ResourcesVpcConfig"
            ]["PublicAccessCidrs"],
        )

    def test_readme_has_cost_cleanup_and_official_sources(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for token in (
            "4時間",
            "最大6時間",
            "約USD 0.97",
            "実請求",
            "scripts/delete.sh",
            "scripts/verify-cleanup.sh",
            "AWS_ACCOUNT_ID",
            "Section 4",
            "guardを最後",
        ):
            self.assertIn(token, readme)
        urls = re.findall(r"https://[^)]+", readme)
        self.assertTrue(urls)
        self.assertTrue(
            all(
                url.startswith(("https://aws.amazon.com/", "https://docs.aws.amazon.com/"))
                or url.startswith("https://checkip.amazonaws.com")
                for url in urls
            )
        )

    def test_canonical_inventory_is_byte_ordinal_and_exact(self):
        inventory_path = ROOT / "artifact-inventory.sha256"
        records = [
            line
            for line in inventory_path.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        paths = [record.split("  ", 1)[1] for record in records]
        self.assertEqual(paths, sorted(paths, key=lambda value: value.encode("utf-8")))
        discovered = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if path == inventory_path or "__pycache__" in path.parts:
                continue
            discovered.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(paths, sorted(discovered, key=lambda value: value.encode("utf-8")))
        for record in records:
            expected_hash, relative = record.split("  ", 1)
            actual_hash = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(expected_hash, actual_hash, relative)


if __name__ == "__main__":
    unittest.main()
