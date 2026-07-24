import re
import hashlib
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


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
        cls.scripts = {
            p.name: p.read_text(encoding="utf-8")
            for p in (ROOT / "scripts").glob("*.ps1")
        }

    def test_template_parses_and_has_required_resources(self):
        resources = self.template["Resources"]
        types = [r["Type"] for r in resources.values()]
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
        self.assertFalse(any("LoadBalancer" in value for value in types))

    def test_exact_name_region_and_tags(self):
        self.assertIn("udemy4-c010-common-20260724", self.text)
        joined = "\n".join(self.scripts.values())
        self.assertIn('Region = "ap-northeast-1"', joined)
        for token in ("Course", "C010", "Lab", "section-s5", "ManagedBy", "udemy4", "Purpose", "training", "TemplateContract"):
            self.assertIn(token, self.text)
            self.assertIn(token, joined)

    def test_api_cidr_has_no_default_and_rejects_world(self):
        cidr = self.template["Parameters"]["ApiPublicAccessCidr"]
        self.assertNotIn("Default", cidr)
        self.assertIn("0\\.0\\.0\\.0/0", cidr["AllowedPattern"])
        self.assertIn('Cidr -eq "0.0.0.0/0"', self.scripts["common.ps1"])

    def test_one_t3_medium_and_20_gib_gp3(self):
        node = self.template["Resources"]["ManagedNodeGroup"]["Properties"]
        self.assertEqual(node["InstanceTypes"], ["t3.medium"])
        self.assertEqual(node["ScalingConfig"], {"DesiredSize": 1, "MinSize": 1, "MaxSize": 1})
        ebs = self.template["Resources"]["NodeLaunchTemplate"]["Properties"]["LaunchTemplateData"]["BlockDeviceMappings"][0]["Ebs"]
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
        self.assertNotIn("Action: '*'", self.text)

    def test_command_order_and_fail_closed_cleanup(self):
        create = self.scripts["create.ps1"]
        self.assertLess(create.index("Assert-Preflight"), create.index('"cloudformation", "deploy"'))
        self.assertLess(create.index('"cloudformation", "deploy"'), create.index("Get-ExpectedStackBinding"))
        self.assertLess(create.index("Get-ExpectedStackBinding"), create.index('"eks", "update-kubeconfig"'))
        delete = self.scripts["delete.ps1"]
        self.assertLess(delete.index("Get-ExpectedStackBinding"), delete.index('"cloudformation", "delete-stack"'))
        self.assertLess(delete.index('"cloudformation", "wait", "stack-delete-complete"'), delete.index("verify-cleanup.ps1"))
        verify = self.scripts["verify-cleanup.ps1"]
        for token in ("describe-stacks", "describe-cluster", "describe-instances", "describe-volumes", "describe-network-interfaces", "describe-log-groups"):
            self.assertIn(token, verify)
        self.assertIn("Cleanup verification failed closed", verify)
        self.assertIn("Amazon EKS $ClusterName", verify)

    def test_exact_account_stack_and_context_binding(self):
        common = self.scripts["common.ps1"]
        for token in (
            "AWS_ACCOUNT_ID",
            "STS account does not equal AWS_ACCOUNT_ID",
            "Stack ID, account, Region, or name mismatch",
            "Assert-ExactTagMap",
            "Assert-ExactEksClusterTagMap",
            'aws:cloudformation:stack-name',
            'aws:cloudformation:stack-id',
            'aws:cloudformation:logical-id',
            '"EksCluster"',
            "TemplateContract",
            "Current kubectl context must equal",
            "-cne $expected",
        ):
            self.assertIn(token, common)
        create = self.scripts["create.ps1"]
        self.assertIn("The fixed stack already exists", create)
        self.assertNotIn("--no-fail-on-empty-changeset", create)

    def test_realistic_eks_cloudformation_tag_fixtures(self):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        self.assertIsNotNone(shell, "PowerShell is required for the realistic tag fixture test")
        common_path = str(ROOT / "scripts" / "common.ps1").replace("'", "''")
        command = rf"""
$ErrorActionPreference = 'Stop'
. '{common_path}'
$accountId = '123456' + '789012'
$stackUuid = '11111111-2222-3333-4444-' + '555555' + '555555'
$stackId = "arn:aws:cloudformation:ap-northeast-1:$accountId`:stack/udemy4-c010-common-20260724/$stackUuid"
$tags = @(
    [pscustomobject]@{{Key='Course'; Value='C010'}}
    [pscustomobject]@{{Key='Lab'; Value='section-s5'}}
    [pscustomobject]@{{Key='ManagedBy'; Value='udemy4'}}
    [pscustomobject]@{{Key='Purpose'; Value='training'}}
    [pscustomobject]@{{Key='TemplateContract'; Value='udemy4-c010-common-eks-v2-20260724'}}
    [pscustomobject]@{{Key='aws:cloudformation:stack-name'; Value='udemy4-c010-common-20260724'}}
    [pscustomobject]@{{Key='aws:cloudformation:stack-id'; Value=$stackId}}
    [pscustomobject]@{{Key='aws:cloudformation:logical-id'; Value='EksCluster'}}
)
Assert-ExactEksClusterTagMap -Tags $tags -StackId $stackId
function Copy-Tags($source) {{
    return @($source | ForEach-Object {{ [pscustomobject]@{{Key=$_.Key; Value=$_.Value}} }})
}}
function Assert-Rejected($candidate, [string]$caseName) {{
    $rejected = $false
    try {{ Assert-ExactEksClusterTagMap -Tags $candidate -StackId $stackId }} catch {{ $rejected = $true }}
    if (-not $rejected) {{ throw "Unsafe EKS tag fixture accepted: $caseName" }}
}}
$unexpected = @(Copy-Tags $tags) + @([pscustomobject]@{{Key='Owner'; Value='unexpected'}})
Assert-Rejected $unexpected 'unexpected tag'
$wrongStackName = @(Copy-Tags $tags)
($wrongStackName | Where-Object Key -eq 'aws:cloudformation:stack-name').Value = 'other-stack'
Assert-Rejected $wrongStackName 'wrong stack name'
$wrongStackId = @(Copy-Tags $tags)
($wrongStackId | Where-Object Key -eq 'aws:cloudformation:stack-id').Value = "arn:aws:cloudformation:ap-northeast-1:$accountId`:stack/other/uuid"
Assert-Rejected $wrongStackId 'wrong stack ID'
$wrongLogicalId = @(Copy-Tags $tags)
($wrongLogicalId | Where-Object Key -eq 'aws:cloudformation:logical-id').Value = 'OtherResource'
Assert-Rejected $wrongLogicalId 'wrong logical ID'
$missing = @((Copy-Tags $tags) | Where-Object Key -ne 'aws:cloudformation:logical-id')
Assert-Rejected $missing 'missing system tag'
"""
        result = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_checked_wrappers_and_explicit_not_found(self):
        common = self.scripts["common.ps1"]
        self.assertIn("Invoke-CheckedNative", common)
        self.assertIn("Invoke-AwsAllowExactNotFound", common)
        self.assertIn("AccessDenied|Unauthorized|ExpiredToken", common)
        joined = "\n".join(self.scripts.values())
        self.assertNotRegex(joined, r"(?m)^\s*&?\s*(aws|kubectl)\s+")

    def test_external_guard_precedes_common_and_survives_common_create_failure(self):
        common = self.scripts["common.ps1"]
        for token in (
            "Assert-EksQuotaHeadroom",
            "No EKS cluster quota headroom",
            "AVAILABILITY_ZONE_A",
            "AVAILABILITY_ZONE_B",
            "foreach ($az in @($azA, $azB))",
            "CLEANUP_DEADLINE_UTC",
            "no more than 6 hours",
        ):
            self.assertIn(token, common)
        self.assertNotIn("AutomaticCleanupSchedule", self.template["Resources"])
        self.assertNotIn("CleanupSchedulerRole", self.template["Resources"])
        resources = self.guard_template["Resources"]
        schedule = resources["AutomaticCleanupSchedule"]["Properties"]
        self.assertEqual(resources["AutomaticCleanupSchedule"]["Type"], "AWS::Scheduler::Schedule")
        self.assertNotIn("ActionAfterCompletion", schedule)
        self.assertEqual(schedule["FlexibleTimeWindow"]["Mode"], "OFF")
        self.assertEqual(schedule["Target"]["Arn"], "arn:aws:scheduler:::aws-sdk:cloudformation:deleteStack")
        role_policy = resources["CleanupSchedulerRole"]["Properties"]["Policies"][0]["PolicyDocument"]
        self.assertEqual(role_policy["Statement"][0]["Action"], "cloudformation:DeleteStack")
        self.assertEqual(
            role_policy["Statement"][0]["Resource"],
            "arn:${AWS::Partition}:cloudformation:ap-northeast-1:${AccountId}:stack/udemy4-c010-common-20260724/*",
        )
        trust = resources["CleanupSchedulerRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
        self.assertEqual(trust["Principal"], {"Service": "scheduler.amazonaws.com"})
        self.assertEqual(trust["Condition"]["StringEquals"]["aws:SourceAccount"], "AccountId")
        self.assertEqual(
            trust["Condition"]["ArnEquals"]["aws:SourceArn"],
            "arn:${AWS::Partition}:scheduler:ap-northeast-1:${AccountId}:schedule-group/default",
        )
        self.assertIn("CleanupScheduleExpression", self.guard_template["Parameters"])
        create = self.scripts["create.ps1"]
        self.assertLess(create.index('"cloudformation", "create-stack"'), create.index("Get-ExpectedGuardBinding"))
        self.assertLess(create.index("Get-ExpectedGuardBinding"), create.index('"cloudformation", "deploy"'))
        self.assertNotIn("delete-stack", create)
        verify = self.scripts["verify-cleanup.ps1"]
        self.assertLess(verify.index("if ($failures.Count -gt 0)"), verify.index("Get-ExpectedGuardBinding"))
        self.assertLess(verify.index("Get-ExpectedGuardBinding"), verify.index('"cloudformation", "delete-stack"'))

    def test_canonical_inventory_is_byte_ordinal_and_exact(self):
        repository = ROOT.parents[1]
        inventory_path = ROOT / "artifact-inventory.sha256"
        records = [
            line for line in inventory_path.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        paths = [record.split("  ", 1)[1] for record in records]
        self.assertEqual(paths, sorted(paths, key=lambda value: value.encode("utf-8")))
        discovered = []
        for package in (ROOT, ROOT.parent / "s5-pod-resource-first-response"):
            for path in package.rglob("*"):
                relative = path.relative_to(repository).as_posix()
                if not path.is_file():
                    continue
                if path == inventory_path or "__pycache__" in path.parts:
                    continue
                discovered.append(relative)
        self.assertEqual(paths, sorted(discovered, key=lambda value: value.encode("utf-8")))
        for record in records:
            expected_hash, relative = record.split("  ", 1)
            actual_hash = hashlib.sha256((repository / relative).read_bytes()).hexdigest()
            self.assertEqual(expected_hash, actual_hash, relative)

    def test_no_dangerous_wildcard_delete(self):
        joined = "\n".join(self.scripts.values())
        self.assertNotRegex(joined, r"\b(delete|remove)[^\n]*(--all|\*|all-resources)")
        self.assertNotIn("0.0.0.0/0", self.template["Resources"]["EksCluster"]["Properties"]["ResourcesVpcConfig"]["PublicAccessCidrs"])

    def test_readme_has_cost_cleanup_and_official_sources(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for token in ("6時間以内", "約USD 0.97", "実請求", "./scripts/delete.ps1", "verify-cleanup.ps1", "AWS_ACCOUNT_ID", "ActionAfterCompletion"):
            self.assertIn(token, readme)
        urls = re.findall(r"https://[^)]+", readme)
        self.assertTrue(urls)
        self.assertTrue(all(url.startswith(("https://aws.amazon.com/", "https://docs.aws.amazon.com/")) for url in urls))

    def test_readme_deadline_examples_are_runtime_relative(self):
        expected = "$env:CLEANUP_DEADLINE_UTC = [DateTimeOffset]::UtcNow.AddHours(4).ToString(\"yyyy-MM-dd'T'HH:mm:ss'Z'\", [Globalization.CultureInfo]::InvariantCulture)"
        fixed_deadline = re.compile(
            r'\$env:CLEANUP_DEADLINE_UTC\s*=\s*"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"'
        )
        for path in (ROOT / "README.md", ROOT.parent / "s5-pod-resource-first-response" / "README.md"):
            readme = path.read_text(encoding="utf-8")
            self.assertEqual(readme.count(expected), 1, path.name)
            self.assertIsNone(fixed_deadline.search(readme), path.name)


if __name__ == "__main__":
    unittest.main()
