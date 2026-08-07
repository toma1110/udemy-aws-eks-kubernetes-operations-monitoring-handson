import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from runtime_contract import ContractError, RESTART_STAGES, decide_irsa_cleanup, validate_execute_preflight, validate_profile_results, validate_record, validate_restart_population, validate_restart_preflight, verify_inputs
import capture_target_record


ACCOUNT = "123456789012"
ISSUER = "oidc.eks.ap-northeast-1.amazonaws.com/id/ABCDEF123456"
ROLE = "eksctl-eks-fargate-ops-lab-FargatePodExecutionRole-Example"
TAGS = {"Course": "c010", "Section": "s3", "ManagedBy": "learner", "Purpose": "training"}
S3_PACKAGE = PACKAGE.parent / "s3"
if not S3_PACKAGE.exists():
    S3_PACKAGE = PACKAGE.parent / "s3-fargate-environment"
IRSA_TEMPLATE = json.loads((S3_PACKAGE / "templates" / "irsa-policy.json").read_text(encoding="utf-8"))
LOGGING_TEMPLATE = json.loads((S3_PACKAGE / "templates" / "pod-execution-logging-policy.json").read_text(encoding="utf-8"))


def record():
    value = {
        "schema": "c010-s3-cleanup-target-v1", "account_id": ACCOUNT,
        "region": "ap-northeast-1", "cluster_name": "eks-fargate-ops-lab",
        "cluster_arn": f"arn:aws:eks:ap-northeast-1:{ACCOUNT}:cluster/eks-fargate-ops-lab",
        "namespace": "eks-fargate-ops", "ownership_tags": TAGS,
        "oidc_issuer": ISSUER, "pod_execution_role_name": ROLE,
        "irsa_role_name": "eks-fargate-ops-irsa-reader",
        "irsa_policy_arn": f"arn:aws:iam::{ACCOUNT}:policy/eks-fargate-ops-describe-cluster",
        "log_group": "/aws/eks/eks-fargate-ops-lab/containers",
    }
    value["ownership"] = {
        "cluster_stack": {
            "stack_name": "eksctl-eks-fargate-ops-lab-cluster",
            "stack_id": f"arn:aws:cloudformation:ap-northeast-1:{ACCOUNT}:stack/eksctl-eks-fargate-ops-lab-cluster/example",
            "ownership_tags": TAGS,
            "resources": [
                {"logical_id": "FargateRole", "type": "AWS::IAM::Role", "physical_id": ROLE, "status": "CREATE_COMPLETE"},
                {"logical_id": "OIDC", "type": "AWS::IAM::OIDCProvider", "physical_id": f"arn:aws:iam::{ACCOUNT}:oidc-provider/{ISSUER}", "status": "CREATE_COMPLETE"},
                {"logical_id": "VPC", "type": "AWS::EC2::VPC", "physical_id": "vpc-0123abcd", "status": "CREATE_COMPLETE"},
                {"logical_id": "NATGateway", "type": "AWS::EC2::NatGateway", "physical_id": "nat-0123abcd", "status": "CREATE_COMPLETE"},
            ],
        },
        "irsa_stack": {
            "stack_name": "eksctl-eks-fargate-ops-lab-addon-iamserviceaccount-eks-fargate-ops-irsa-reader",
            "stack_id": f"arn:aws:cloudformation:ap-northeast-1:{ACCOUNT}:stack/eksctl-eks-fargate-ops-lab-addon-iamserviceaccount-eks-fargate-ops-irsa-reader/example",
            "ownership_tags": TAGS,
            "resources": [
                {"logical_id": "Role1", "type": "AWS::IAM::Role", "physical_id": "eks-fargate-ops-irsa-reader", "status": "CREATE_COMPLETE"}
            ],
        },
    }
    return value


class RuntimeContractTests(unittest.TestCase):
    def _captured_record(self, resources):
        target = record()
        target["ownership"]["irsa_stack"]["resources"] = resources
        cluster = {"cluster": {"identity": {"oidc": {"issuer": f"https://{ISSUER}"}}}}
        profile = {"fargateProfile": {"podExecutionRoleArn": f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"}}
        def fake_stack(name, optional=False):
            return target["ownership"]["irsa_stack"] if "addon-iamserviceaccount" in name else target["ownership"]["cluster_stack"]
        def fake_aws(*args, absent=()):
            if args[:2] == ("eks", "describe-cluster"): return cluster
            if args[:2] == ("eks", "describe-fargate-profile"): return profile
            if args[:2] == ("iam", "get-policy"): return {"Policy": {"PolicyId": "ANPAEXAMPLE"}}
            if args[:2] == ("iam", "list-policy-tags"): return {"Tags": [{"Key": key, "Value": value} for key, value in TAGS.items()]}
            if args[:2] == ("iam", "get-open-id-connect-provider"): return {}
            raise AssertionError(args)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "target.json"
            with patch.object(capture_target_record, "stack", side_effect=fake_stack), patch.object(capture_target_record, "aws", side_effect=fake_aws), patch.object(sys, "argv", ["capture_target_record.py", str(output), ACCOUNT]):
                capture_target_record.main()
            return json.loads(output.read_text(encoding="utf-8"))

    def test_profile_describe_error_fails_closed(self):
        with self.assertRaises(ContractError):
            validate_profile_results(True, ["ops-workloads"], {"ops-workloads": {"status": "error"}})

    def test_profile_absence_requires_successful_list(self):
        with self.assertRaises(ContractError):
            validate_profile_results(False, [], {})

    def test_missing_issuer_and_wrong_account_fail(self):
        with self.assertRaises(ContractError):
            verify_inputs(ACCOUNT, ACCOUNT, "", ROLE)
        with self.assertRaises(ContractError):
            verify_inputs(ACCOUNT, "000000000000", ISSUER, ROLE)

    def _snapshot(self):
        value = record()
        issuer = value["oidc_issuer"]
        oidc_arn = f"arn:aws:iam::{ACCOUNT}:oidc-provider/{issuer}"
        return {
            "stacks": value["ownership"],
            "irsa_role": {
                "name": value["irsa_role_name"], "attached": [value["irsa_policy_arn"]], "inline": {},
                "trust": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Federated": oidc_arn}, "Action": "sts:AssumeRoleWithWebIdentity", "Condition": {"StringEquals": {f"{issuer}:aud": "sts.amazonaws.com", f"{issuer}:sub": "system:serviceaccount:eks-fargate-ops:irsa-reader"}}}]},
            },
            "pod_role": {
                "name": ROLE, "attached": ["arn:aws:iam::aws:policy/AmazonEKSFargatePodExecutionRolePolicy"], "inline": {},
                "trust": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "eks-fargate-pods.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
            },
            "irsa_policy": {"arn": value["irsa_policy_arn"], "attachments": {"roles": [value["irsa_role_name"]], "users": [], "groups": []}, "document": json.loads(json.dumps(IRSA_TEMPLATE))},
            "oidc": {"arn": oidc_arn, "referencing_roles": [value["irsa_role_name"]]},
            "profiles": [{"name": "ops-workloads", "tags": TAGS, "describe_status": "success", "pod_role": ROLE,
                          "selectors": [{"namespace": "eks-fargate-ops", "labels": {"compute": "ops-lab"}}]}],
        }

    def test_execute_preflight_rejects_extra_trust_and_stack_members(self):
        snapshot = self._snapshot()
        snapshot["irsa_role"]["trust"]["Statement"].append({"Effect": "Allow", "Principal": {"AWS": "*"}, "Action": "sts:AssumeRole"})
        with self.assertRaises(ContractError):
            validate_execute_preflight(record(), snapshot, ACCOUNT)
        snapshot = self._snapshot()
        snapshot["stacks"]["cluster_stack"]["resources"].append({"logical_id": "Unexpected", "type": "AWS::IAM::Role", "physical_id": "unrelated", "status": "CREATE_COMPLETE"})
        with self.assertRaises(ContractError):
            validate_execute_preflight(record(), snapshot, ACCOUNT)

    def test_execute_preflight_rejects_unbound_irsa_policy(self):
        snapshot = self._snapshot()
        snapshot["irsa_policy"]["attachments"]["roles"] = []
        with self.assertRaises(ContractError):
            validate_execute_preflight(record(), snapshot, ACCOUNT)

    def test_execute_preflight_rejects_extra_pod_trust_principal(self):
        snapshot = self._snapshot()
        snapshot["pod_role"]["trust"]["Statement"][0]["Principal"]["AWS"] = "*"
        with self.assertRaises(ContractError):
            validate_execute_preflight(record(), snapshot, ACCOUNT)

    def test_execute_preflight_rejects_unexpected_profile_selector(self):
        snapshot = self._snapshot()
        snapshot["profiles"][0]["selectors"][0]["namespace"] = "default"
        with self.assertRaises(ContractError):
            validate_execute_preflight(record(), snapshot, ACCOUNT)

    def test_every_restart_boundary_is_monotonic(self):
        for boundary in range(len(RESTART_STAGES) + 1):
            population = {name: ("absent" if i < boundary else "present") for i, name in enumerate(RESTART_STAGES)}
            self.assertEqual(validate_restart_population(population), boundary)

    def test_cluster_absent_stack_and_iam_only_boundaries(self):
        base = {name: "absent" for name in RESTART_STAGES}
        allowed = [
            ("irsa_stack", "irsa_policy", "oidc_provider", "pod_logging_policy", "cluster_stack", "log_group"),
            ("irsa_policy", "oidc_provider", "pod_logging_policy", "cluster_stack", "log_group"),
            ("irsa_policy", "log_group"), ("log_group",), (),
        ]
        for boundary, present in enumerate(allowed):
            population = dict(base); population.update({name: "present" for name in present})
            self.assertEqual(validate_restart_population(population, "cluster-absent"), boundary)
        ambiguous = dict(base); ambiguous.update({"oidc_provider": "present", "log_group": "present"})
        with self.assertRaises(ContractError):
            validate_restart_population(ambiguous, "cluster-absent")

    def test_partial_stack_anchor_accepts_real_creation_boundaries(self):
        for keep in (set(), {"AWS::IAM::OIDCProvider"}, {"AWS::IAM::Role"}, {"AWS::IAM::OIDCProvider", "AWS::IAM::Role"}):
            target = record(); target["schema"] = "c010-s3-cleanup-target-v2"; target["capture_mode"] = "partial-stack-anchor"; target["partial_policy_identity"] = None; target["ownership"]["irsa_stack"] = None
            target["ownership"]["cluster_stack"]["resources"] = [x for x in target["ownership"]["cluster_stack"]["resources"] if x["type"] not in {"AWS::IAM::Role", "AWS::IAM::OIDCProvider"} or x["type"] in keep]
            if "AWS::IAM::Role" not in keep: target["pod_execution_role_name"] = None
            if "AWS::IAM::OIDCProvider" not in keep: target["oidc_issuer"] = None
            validate_record(target, ACCOUNT)
        target["ownership"]["cluster_stack"]["resources"].append({"logical_id": "Unexpected", "type": "AWS::S3::Bucket", "physical_id": "unsafe", "status": "CREATE_COMPLETE"})
        with self.assertRaises(ContractError): validate_record(target, ACCOUNT)

    def test_partial_restart_rejects_ambiguous_reverse_population(self):
        target = record(); target["schema"] = "c010-s3-cleanup-target-v2"; target["capture_mode"] = "partial-stack-anchor"; target["partial_policy_identity"] = None; target["ownership"]["irsa_stack"] = None
        snapshot = {"branch": "partial-cluster-absent", "population": {name: "absent" for name in RESTART_STAGES}, "stacks": {"cluster_stack": None, "irsa_stack": None}}
        snapshot["population"]["oidc_provider"] = "present"
        with self.assertRaises(ContractError): validate_restart_preflight(target, snapshot, ACCOUNT)

    def _partial_readable(self):
        target = record(); target["schema"] = "c010-s3-cleanup-target-v2"; target["capture_mode"] = "partial-stack-anchor"; target["partial_policy_identity"] = {"policy_id": "ANPAEXAMPLE", "ownership_tags": TAGS}
        snapshot = self._snapshot(); snapshot["branch"] = "partial-readable-cluster"; snapshot["population"] = {name: "present" for name in RESTART_STAGES}; snapshot["irsa_policy"].update({"policy_id": "ANPAEXAMPLE", "ownership_tags": TAGS}); snapshot["pod_role"]["inline"] = {"eks-fargate-ops-logging": json.loads(json.dumps(LOGGING_TEMPLATE))}; snapshot["profiles"].append({"name": "system-coredns", "tags": TAGS, "describe_status": "success", "pod_role": ROLE, "selectors": [{"namespace": "kube-system", "labels": {"k8s-app": "kube-dns"}}]})
        return target, snapshot

    def test_partial_same_name_exact_document_policy_without_identity_fails(self):
        target, snapshot = self._partial_readable(); target["partial_policy_identity"] = None
        with self.assertRaises(ContractError): validate_restart_preflight(target, snapshot, ACCOUNT)

    def test_partial_malicious_role_and_oidc_reference_drift_fail(self):
        target, snapshot = self._partial_readable(); snapshot["pod_role"]["name"] = "malicious-role"
        with self.assertRaises(ContractError): validate_restart_preflight(target, snapshot, ACCOUNT)
        target, snapshot = self._partial_readable(); snapshot["oidc"]["referencing_roles"].append("malicious-role")
        with self.assertRaises(ContractError): validate_restart_preflight(target, snapshot, ACCOUNT)

    def test_partial_failed_irsa_stack_with_empty_population_requires_no_role(self):
        target, snapshot = self._partial_readable(); target["ownership"]["irsa_stack"]["resources"] = []; snapshot["stacks"]["irsa_stack"]["resources"] = []; snapshot["irsa_role"] = None; snapshot["irsa_policy"]["attachments"]["roles"] = []; snapshot["oidc"]["referencing_roles"] = []
        validate_restart_preflight(target, snapshot, ACCOUNT)

    def test_mocked_capture_main_to_restart_preflight_and_cleanup_routes(self):
        capture = self._captured_record
        empty = capture([])
        self.assertEqual(empty["schema"], "c010-s3-cleanup-target-v2")
        validate_record(empty, ACCOUNT)
        _, empty_snapshot = self._partial_readable(); empty_snapshot["stacks"] = empty["ownership"]; empty_snapshot["irsa_role"] = None; empty_snapshot["irsa_policy"]["attachments"]["roles"] = []; empty_snapshot["oidc"]["referencing_roles"] = []
        self.assertEqual(decide_irsa_cleanup(empty, empty_snapshot, ACCOUNT), {"action": "delete-exact-stack", "plan": "delete exact captured iamserviceaccount CloudFormation stack"})

        failed_member = {"logical_id": "Role1", "type": "AWS::IAM::Role", "physical_id": "eks-fargate-ops-irsa-reader", "status": "CREATE_FAILED"}
        failed = capture([failed_member])
        self.assertEqual(failed["schema"], "c010-s3-cleanup-target-v2")
        validate_record(failed, ACCOUNT)
        _, failed_snapshot = self._partial_readable(); failed_snapshot["stacks"] = failed["ownership"]
        self.assertEqual(decide_irsa_cleanup(failed, failed_snapshot, ACCOUNT)["action"], "delete-iamserviceaccount")

        creating_member = dict(failed_member); creating_member["status"] = "CREATE_IN_PROGRESS"
        creating = capture([creating_member])
        self.assertEqual(creating["schema"], "c010-s3-cleanup-target-v2")
        validate_record(creating, ACCOUNT)
        _, creating_snapshot = self._partial_readable(); creating_snapshot["stacks"] = creating["ownership"]
        self.assertEqual(decide_irsa_cleanup(creating, creating_snapshot, ACCOUNT)["action"], "delete-iamserviceaccount")

        for status in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
            complete_member = dict(failed_member); complete_member["status"] = status
            complete = capture([complete_member])
            self.assertEqual(complete["schema"], "c010-s3-cleanup-target-v1")
            _, complete_snapshot = self._partial_readable(); complete_snapshot["branch"] = "readable-cluster"; complete_snapshot["stacks"] = complete["ownership"]
            self.assertEqual(decide_irsa_cleanup(complete, complete_snapshot, ACCOUNT)["action"], "delete-iamserviceaccount")

        for field, value in (("logical_id", "UnanchoredRole"), ("type", "AWS::IAM::Policy"), ("physical_id", "unanchored-role"), ("status", "DELETE_COMPLETE")):
            drifted_member = dict(failed_member); drifted_member[field] = value
            drifted = capture([drifted_member])
            _, drifted_snapshot = self._partial_readable(); drifted_snapshot["stacks"] = drifted["ownership"]
            with self.assertRaises(ContractError):
                decide_irsa_cleanup(drifted, drifted_snapshot, ACCOUNT)

        unanchored_snapshot = json.loads(json.dumps(empty_snapshot)); unanchored_snapshot["stacks"]["irsa_stack"]["stack_id"] += "-other"
        with self.assertRaises(ContractError): decide_irsa_cleanup(empty, unanchored_snapshot, ACCOUNT)
        reversed_snapshot = json.loads(json.dumps(empty_snapshot)); reversed_snapshot["population"]["logging_configmap"] = "absent"
        with self.assertRaises(ContractError): decide_irsa_cleanup(empty, reversed_snapshot, ACCOUNT)

    def test_actual_cleanup_plan_and_execute_use_the_same_mocked_decision(self):
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        shell_env = subprocess.run([bash, "-lc", 'printf "%s\\n%s" "$PATH" "$(command -v python3)"'], text=True, capture_output=True, check=True).stdout.splitlines()
        shell_path_value, shell_python = shell_env

        def shell_path(path):
            value = Path(path).resolve()
            drive, tail = os.path.splitdrive(str(value))
            return f"/mnt/{drive[0].lower()}/{tail.lstrip('\\\\/').replace(os.sep, '/')}" if drive else value.as_posix()

        def run_cleanup(target, snapshot, mode, role_present):
            with tempfile.TemporaryDirectory() as directory:
                work = Path(directory); mock_bin = work / "bin"; mock_bin.mkdir()
                target_path = work / "target.json"; snapshot_path = work / "snapshot.json"; log_path = work / "mutations.log"
                target_path.write_text(json.dumps(target), encoding="utf-8"); snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
                scripts = {
                    "python": '''#!/usr/bin/env bash
if [[ "${1:-}" == *execute_preflight.py ]]; then
  while [[ $# -gt 0 ]]; do [[ "$1" == "--snapshot" ]] && { cp "$MOCK_SNAPSHOT" "$2"; exit 0; }; shift; done
fi
exec "$REAL_PYTHON" "$@"
''',
                    "timeout": '''#!/usr/bin/env bash
for value in "$@"; do [[ "$value" == *verify-residuals.sh ]] && exit 0; done
shift
exec "$@"
''',
                    "kubectl": f'''#!/usr/bin/env bash
if [[ "$*" == "config current-context" ]]; then printf '%s\\n' 'arn:aws:eks:ap-northeast-1:{ACCOUNT}:cluster/eks-fargate-ops-lab'; exit 0; fi
if [[ "$*" == *"get namespace"* ]]; then printf '%s\\n' '{{"metadata":{{"labels":{{"course":"c010","section":"s3"}}}}}}'; exit 0; fi
if [[ "$*" == *"get configmap"* ]]; then printf '%s\\n' '{{"data":{{"output.conf":"log_group_name /aws/eks/eks-fargate-ops-lab/containers"}}}}'; exit 0; fi
printf 'kubectl %s\\n' "$*" >> "$MOCK_LOG"
''',
                    "eksctl": '''#!/usr/bin/env bash
printf 'eksctl %s\n' "$*" >> "$MOCK_LOG"
''',
                    "aws": f'''#!/usr/bin/env bash
args="$*"
if [[ "$args" == "sts get-caller-identity --query Account --output text" ]]; then printf '%s\\n' '{ACCOUNT}'; exit 0; fi
if [[ "$args" == eks\\ describe-cluster* ]]; then printf '%s\\n' '{{"cluster":{{"arn":"arn:aws:eks:ap-northeast-1:{ACCOUNT}:cluster/eks-fargate-ops-lab","identity":{{"oidc":{{"issuer":"https://{ISSUER}"}}}},"tags":{{"Course":"c010","Section":"s3","ManagedBy":"learner","Purpose":"training"}}}}}}'; exit 0; fi
if [[ "$args" == eks\\ list-fargate-profiles* ]]; then printf '%s\\n' '["ops-workloads","system-coredns"]'; exit 0; fi
if [[ "$args" == eks\\ delete-fargate-profile* ]]; then name="${{args##*--fargate-profile-name }}"; : > "$MOCK_DIR/deleted-${{name%% *}}"; printf 'aws %s\\n' "$args" >> "$MOCK_LOG"; exit 0; fi
if [[ "$args" == eks\\ describe-fargate-profile* ]]; then
  name="${{args##*--fargate-profile-name }}"; name="${{name%% *}}"; [[ -f "$MOCK_DIR/deleted-$name" ]] && {{ printf 'ResourceNotFoundException\\n' >&2; exit 1; }}
  if [[ "$name" == "ops-workloads" ]]; then selector='{{"namespace":"eks-fargate-ops","labels":{{"compute":"ops-lab"}}}}'; else selector='{{"namespace":"kube-system","labels":{{"k8s-app":"kube-dns"}}}}'; fi
  printf '{{"fargateProfile":{{"fargateProfileName":"%s","podExecutionRoleArn":"arn:aws:iam::{ACCOUNT}:role/{ROLE}","selectors":[%s],"tags":{{"Course":"c010","Section":"s3","ManagedBy":"learner","Purpose":"training"}}}}}}\\n' "$name" "$selector"; exit 0
fi
if [[ "$args" == "iam get-role --role-name eks-fargate-ops-irsa-reader" ]]; then [[ "$MOCK_ROLE_PRESENT" == 1 ]] && {{ printf '{{}}\\n'; exit 0; }}; printf 'NoSuchEntity\\n' >&2; exit 1; fi
if [[ "$args" == iam\\ get-policy* || "$args" == iam\\ get-open-id-connect-provider* || "$args" == iam\\ get-role-policy* ]]; then printf 'NoSuchEntity\\n' >&2; exit 1; fi
if [[ "$args" == logs\\ describe-log-groups* ]]; then printf '0\\n'; exit 0; fi
printf 'aws %s\\n' "$args" >> "$MOCK_LOG"
''',
                }
                for name, text in scripts.items():
                    path = mock_bin / name; path.write_text(text, encoding="utf-8", newline="\n"); path.chmod(0o755)
                subprocess.run([bash, "-lc", f"chmod +x {shell_path(mock_bin)}/*"], check=True)
                env = os.environ.copy(); env.update({
                    "PATH": shell_path(mock_bin) + ":" + shell_path_value, "REAL_PYTHON": shell_python,
                    "MOCK_SNAPSHOT": shell_path(snapshot_path), "MOCK_LOG": shell_path(log_path), "MOCK_DIR": shell_path(work),
                    "MOCK_ROLE_PRESENT": "1" if role_present else "0", "PYTHONDONTWRITEBYTECODE": "1",
                    "AWS_REGION": "ap-northeast-1", "AWS_DEFAULT_REGION": "ap-northeast-1", "CLUSTER_NAME": "eks-fargate-ops-lab",
                    "NAMESPACE": "eks-fargate-ops", "EXPECTED_AWS_ACCOUNT_ID": ACCOUNT,
                    "CONFIRM_CLEANUP_TARGET": "DELETE eks-fargate-ops-lab IN ap-northeast-1", "TARGET_RECORD_PATH": shell_path(target_path),
                })
                shell_keys = ("PATH", "REAL_PYTHON", "MOCK_SNAPSHOT", "MOCK_LOG", "MOCK_DIR", "MOCK_ROLE_PRESENT", "PYTHONDONTWRITEBYTECODE", "AWS_REGION", "AWS_DEFAULT_REGION", "CLUSTER_NAME", "NAMESPACE", "EXPECTED_AWS_ACCOUNT_ID", "CONFIRM_CLEANUP_TARGET", "TARGET_RECORD_PATH")
                exports = "; ".join(f"export {key}={shlex.quote(env[key])}" for key in shell_keys)
                command = f"{exports}; exec bash {shlex.quote(shell_path(PACKAGE / 'cleanup.sh'))} {shlex.quote(mode)}"
                result = subprocess.run([bash, "-lc", command], text=True, capture_output=True, env=env, check=False)
                mutations = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
                return result, mutations

        failed_member = {"logical_id": "Role1", "type": "AWS::IAM::Role", "physical_id": "eks-fargate-ops-irsa-reader", "status": "CREATE_FAILED"}
        cases = [([], False, "delete exact captured iamserviceaccount CloudFormation stack", "cloudformation delete-stack", "eksctl delete iamserviceaccount")]
        cases += [([dict(failed_member, status=status)], True, "delete exact iamserviceaccount through eksctl", "eksctl delete iamserviceaccount", "cloudformation delete-stack") for status in ("CREATE_FAILED", "CREATE_IN_PROGRESS", "CREATE_COMPLETE", "UPDATE_COMPLETE")]
        for resources, role_present, plan, expected, forbidden in cases:
            target = self._captured_record(resources); _, snapshot = self._partial_readable(); snapshot["stacks"] = target["ownership"]
            if not resources: snapshot["irsa_role"] = None; snapshot["irsa_policy"]["attachments"]["roles"] = []; snapshot["oidc"]["referencing_roles"] = []
            if target["schema"].endswith("v1"): snapshot["branch"] = "readable-cluster"
            planned, plan_log = run_cleanup(target, snapshot, "--plan", role_present)
            self.assertEqual(planned.returncode, 0, planned.stderr); self.assertIn(f"PLAN: {plan}", planned.stdout); self.assertEqual(plan_log, "")
            executed, execute_log = run_cleanup(target, snapshot, "--execute", role_present)
            self.assertEqual(executed.returncode, 0, executed.stderr); self.assertIn(f"PLAN: {plan}", executed.stdout); self.assertIn(expected, execute_log); self.assertNotIn(forbidden, execute_log)

        empty = self._captured_record([]); _, base = self._partial_readable(); base["stacks"] = empty["ownership"]; base["irsa_role"] = None; base["irsa_policy"]["attachments"]["roles"] = []; base["oidc"]["referencing_roles"] = []
        invalid = []
        for field, value in (("logical_id", "Other"), ("type", "AWS::IAM::Policy"), ("physical_id", "other"), ("status", "DELETE_COMPLETE")):
            member = dict(failed_member); member[field] = value; target = self._captured_record([member]); snapshot = json.loads(json.dumps(base)); snapshot["stacks"] = target["ownership"]; snapshot["irsa_role"] = self._snapshot()["irsa_role"]; invalid.append((target, snapshot))
        unanchored = json.loads(json.dumps(base)); unanchored["stacks"]["irsa_stack"]["stack_id"] += "-other"; invalid.append((empty, unanchored))
        reversed_state = json.loads(json.dumps(base)); reversed_state["population"]["logging_configmap"] = "absent"; invalid.append((empty, reversed_state))
        for target, snapshot in invalid:
            for mode in ("--plan", "--execute"):
                stopped, mutation_log = run_cleanup(target, snapshot, mode, bool(snapshot.get("irsa_role")))
                self.assertNotEqual(stopped.returncode, 0); self.assertNotIn("PLAN:", stopped.stdout); self.assertEqual(mutation_log, "")

    def test_partial_exact_role_and_presence_negative_probes(self):
        mutations = [
            lambda s: s["irsa_role"]["trust"]["Statement"][0].update({"Effect": "Deny"}),
            lambda s: s["irsa_role"]["trust"]["Statement"][0]["Condition"].update({"Bool": {"aws:SecureTransport": "true"}}),
            lambda s: s["pod_role"]["trust"]["Statement"][0].update({"Extra": True}),
        ]
        for mutate in mutations:
            target, snapshot = self._partial_readable(); mutate(snapshot)
            with self.assertRaises(ContractError): validate_restart_preflight(target, snapshot, ACCOUNT)
        target, snapshot = self._partial_readable(); snapshot["population"]["pod_logging_policy"] = "present"; snapshot["pod_role"]["inline"] = {"eks-fargate-ops-logging": json.loads(json.dumps(LOGGING_TEMPLATE))}; snapshot["pod_role"]["inline"]["eks-fargate-ops-logging"]["Statement"][0]["Resource"] = "*"
        with self.assertRaises(ContractError): validate_restart_preflight(target, snapshot, ACCOUNT)
        target, snapshot = self._partial_readable(); snapshot["oidc"] = None
        with self.assertRaises(ContractError): validate_restart_preflight(target, snapshot, ACCOUNT)
        target, snapshot = self._partial_readable(); snapshot["population"]["irsa_policy"] = "absent"
        with self.assertRaises(ContractError): validate_restart_preflight(target, snapshot, ACCOUNT)

    def test_readable_oidc_then_policy_or_iamserviceaccount_failure_contracts(self):
        target, snapshot = self._partial_readable(); target["ownership"]["irsa_stack"] = None; target["partial_policy_identity"] = None; snapshot["stacks"]["irsa_stack"] = None; snapshot["irsa_role"] = None; snapshot["irsa_policy"] = None; snapshot["population"]["irsa_stack"] = "absent"; snapshot["population"]["irsa_policy"] = "absent"; snapshot["oidc"]["referencing_roles"] = []
        validate_restart_preflight(target, snapshot, ACCOUNT)
        target, snapshot = self._partial_readable(); target["ownership"]["irsa_stack"] = None; snapshot["stacks"]["irsa_stack"] = None; snapshot["irsa_role"] = None; snapshot["population"]["irsa_stack"] = "absent"; snapshot["irsa_policy"]["attachments"]["roles"] = []; snapshot["oidc"]["referencing_roles"] = []
        validate_restart_preflight(target, snapshot, ACCOUNT)

    def test_partial_raw_consistent_reversed_states_are_rejected(self):
        target, snapshot = self._partial_readable(); snapshot["population"]["workload_profile"] = "absent"; snapshot["population"]["coredns_profile"] = "absent"; snapshot["profiles"] = []
        with self.assertRaises(ContractError): validate_restart_preflight(target, snapshot, ACCOUNT)
        target, snapshot = self._partial_readable(); snapshot["population"]["logging_configmap"] = "absent"
        with self.assertRaises(ContractError): validate_restart_preflight(target, snapshot, ACCOUNT)
        target, snapshot = self._partial_readable(); snapshot["branch"] = "partial-cluster-absent"; snapshot["population"] = {name: "absent" for name in RESTART_STAGES}; snapshot["population"].update({"irsa_policy": "present", "log_group": "present"}); snapshot["stacks"] = {"cluster_stack": None, "irsa_stack": None}; snapshot["irsa_role"] = None; snapshot["pod_role"] = None; snapshot["oidc"] = None; snapshot["profiles"] = []; snapshot["irsa_policy"]["attachments"]["roles"] = []
        with self.assertRaises(ContractError): validate_restart_preflight(target, snapshot, ACCOUNT)

    def test_restart_rejects_skipped_unreadable_and_unexpected_states(self):
        skipped = {name: "present" for name in RESTART_STAGES}
        skipped["logging_configmap"] = "absent"
        with self.assertRaises(ContractError):
            validate_restart_population(skipped)
        unreadable = {name: "present" for name in RESTART_STAGES}
        unreadable["namespace"] = "error"
        with self.assertRaises(ContractError):
            validate_restart_population(unreadable)
        extra = {name: "present" for name in RESTART_STAGES}
        extra["unexpected"] = "present"
        with self.assertRaises(ContractError):
            validate_restart_population(extra)

    def test_execute_preflight_rejects_extra_document_key_and_version(self):
        snapshot = self._snapshot()
        snapshot["irsa_policy"]["document"]["Extra"] = True
        with self.assertRaises(ContractError):
            validate_execute_preflight(record(), snapshot, ACCOUNT)

    def test_current_section3_raw_policy_templates_are_accepted(self):
        snapshot = self._snapshot()
        snapshot["pod_role"]["inline"] = {"eks-fargate-ops-logging": LOGGING_TEMPLATE}
        validate_execute_preflight(record(), snapshot, ACCOUNT)
        snapshot["population"] = {name: "present" for name in RESTART_STAGES}
        snapshot["branch"] = "readable-cluster"
        snapshot["profiles"].append({"name": "system-coredns", "tags": TAGS, "describe_status": "success", "pod_role": ROLE, "selectors": [{"namespace": "kube-system", "labels": {"k8s-app": "kube-dns"}}]})
        validate_restart_preflight(record(), snapshot, ACCOUNT)

    def test_restart_rejects_same_unexpected_stack_member_in_record_and_current(self):
        target = record()
        target["ownership"]["cluster_stack"]["resources"].append(
            {"logical_id": "UnexpectedRole", "type": "AWS::IAM::Role", "physical_id": "unexpected", "status": "CREATE_COMPLETE"}
        )
        snapshot = self._snapshot()
        snapshot["stacks"] = target["ownership"]
        snapshot["population"] = {name: "present" for name in RESTART_STAGES}
        snapshot["branch"] = "readable-cluster"
        with self.assertRaises(ContractError):
            validate_restart_preflight(target, snapshot, ACCOUNT)

    def test_tampered_record_extra_key_is_rejected(self):
        target = record()
        target["untrusted_override"] = True
        with self.assertRaises(ContractError):
            validate_restart_preflight(target, {"branch": "cluster-absent", "population": {}}, ACCOUNT)
        snapshot = self._snapshot()
        snapshot["pod_role"]["trust"]["Version"] = "2008-10-17"
        with self.assertRaises(ContractError):
            validate_execute_preflight(record(), snapshot, ACCOUNT)


if __name__ == "__main__":
    unittest.main()
