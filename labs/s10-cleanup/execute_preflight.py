#!/usr/bin/env python3
"""Collect and validate the complete read-only AWS cleanup preflight."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from runtime_contract import EXPECTED_TAGS, ContractError, validate_execute_preflight, validate_restart_preflight

REGION = "ap-northeast-1"
CLUSTER = "eks-fargate-ops-lab"
PROFILE_NAMES = ("ops-workloads", "system-coredns")


def aws(*args: str) -> dict[str, Any]:
    process = subprocess.run(
        ["aws", *args, "--output", "json"], capture_output=True, text=True, check=False
    )
    if process.returncode:
        raise ContractError(f"read-only AWS preflight failed: {' '.join(args[:3])}")
    try:
        value = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("read-only AWS preflight returned unreadable JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("read-only AWS preflight returned an unexpected JSON type")
    return value


def aws_maybe(absence_marker: str, *args: str) -> dict[str, Any] | None:
    process = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True, check=False)
    if process.returncode:
        if absence_marker in process.stderr:
            return None
        raise ContractError(f"read-only AWS restart preflight failed: {' '.join(args[:3])}")
    try:
        value = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("read-only AWS restart preflight returned unreadable JSON") from exc
    return value


def listed_profiles() -> list[str]:
    process = subprocess.run(
        ["aws", "eks", "list-fargate-profiles", "--region", REGION, "--cluster-name", CLUSTER, "--output", "json"],
        capture_output=True, text=True, check=False,
    )
    if process.returncode:
        if "ResourceNotFoundException" in process.stderr:
            return []
        raise ContractError("complete Fargate Profile population is unreadable")
    try:
        names = json.loads(process.stdout).get("fargateProfileNames")
    except (json.JSONDecodeError, AttributeError) as exc:
        raise ContractError("complete Fargate Profile population is unreadable") from exc
    if not isinstance(names, list):
        raise ContractError("complete Fargate Profile population is unreadable")
    return names


def stack(name: str) -> dict[str, Any]:
    described = aws("cloudformation", "describe-stacks", "--region", REGION, "--stack-name", name)
    resources = aws("cloudformation", "list-stack-resources", "--region", REGION, "--stack-name", name)
    stacks = described.get("Stacks", [])
    members = resources.get("StackResourceSummaries")
    if len(stacks) != 1 or not isinstance(members, list):
        raise ContractError("CloudFormation stack or complete resource population is unreadable")
    item = stacks[0]
    tags = {x["Key"]: x["Value"] for x in item.get("Tags", []) if x.get("Key") in EXPECTED_TAGS}
    return {
        "stack_name": item.get("StackName"),
        "stack_id": item.get("StackId"),
        "ownership_tags": tags,
        "resources": sorted([
            {
                "logical_id": x.get("LogicalResourceId"),
                "type": x.get("ResourceType"),
                "physical_id": x.get("PhysicalResourceId"),
                "status": x.get("ResourceStatus"),
            }
            for x in members
        ], key=lambda x: (str(x["logical_id"]), str(x["type"]), str(x["physical_id"]))),
    }


def role(name: str) -> dict[str, Any]:
    data = aws("iam", "get-role", "--role-name", name)
    attached = aws("iam", "list-attached-role-policies", "--role-name", name)
    inline_names = aws("iam", "list-role-policies", "--role-name", name).get("PolicyNames")
    if not isinstance(inline_names, list):
        raise ContractError("complete inline role-policy population is unreadable")
    inline = {}
    for policy_name in inline_names:
        policy = aws("iam", "get-role-policy", "--role-name", name, "--policy-name", policy_name)
        inline[policy_name] = policy.get("PolicyDocument")
    return {
        "name": data.get("Role", {}).get("RoleName"),
        "trust": data.get("Role", {}).get("AssumeRolePolicyDocument"),
        "attached": sorted(x.get("PolicyArn") for x in attached.get("AttachedPolicies", [])),
        "inline": inline,
    }


def stack_maybe(name: str) -> dict[str, Any] | None:
    described = aws_maybe("does not exist", "cloudformation", "describe-stacks", "--region", REGION, "--stack-name", name)
    if described is None:
        return None
    return stack(name)


def role_maybe(name: str) -> dict[str, Any] | None:
    if aws_maybe("NoSuchEntity", "iam", "get-role", "--role-name", name) is None:
        return None
    return role(name)


def collect(record: dict[str, Any]) -> dict[str, Any]:
    irsa_policy = aws("iam", "get-policy", "--policy-arn", record["irsa_policy_arn"])
    version_id = irsa_policy.get("Policy", {}).get("DefaultVersionId")
    if not version_id:
        raise ContractError("IRSA policy default version is unreadable")
    policy_version = aws("iam", "get-policy-version", "--policy-arn", record["irsa_policy_arn"], "--version-id", version_id)
    entities = aws("iam", "list-entities-for-policy", "--policy-arn", record["irsa_policy_arn"])
    oidc_arn = f"arn:aws:iam::{record['account_id']}:oidc-provider/{record['oidc_issuer']}"
    oidc = aws("iam", "get-open-id-connect-provider", "--open-id-connect-provider-arn", oidc_arn)
    if not oidc:
        raise ContractError("OIDC provider is unreadable")
    roles = aws("iam", "list-roles").get("Roles")
    if not isinstance(roles, list):
        raise ContractError("complete IAM role population is unreadable")
    references = sorted(
        x.get("RoleName") for x in roles
        if record["oidc_issuer"] in json.dumps(x.get("AssumeRolePolicyDocument", {}), sort_keys=True)
    )
    listed = listed_profiles()
    profiles = []
    for name in sorted(listed):
        profile = aws("eks", "describe-fargate-profile", "--region", REGION, "--cluster-name", CLUSTER, "--fargate-profile-name", name).get("fargateProfile", {})
        profiles.append({
            "name": profile.get("fargateProfileName"),
            "describe_status": "success",
            "tags": profile.get("tags"),
            "selectors": profile.get("selectors"),
            "pod_role": str(profile.get("podExecutionRoleArn", "")).rsplit("/", 1)[-1],
        })
    return {
        "stacks": {
            "cluster_stack": stack("eksctl-eks-fargate-ops-lab-cluster"),
            "irsa_stack": stack("eksctl-eks-fargate-ops-lab-addon-iamserviceaccount-eks-fargate-ops-irsa-reader"),
        },
        "irsa_role": role(record["irsa_role_name"]),
        "pod_role": role(record["pod_execution_role_name"]),
        "irsa_policy": {
            "arn": irsa_policy.get("Policy", {}).get("Arn"),
            "document": policy_version.get("PolicyVersion", {}).get("Document"),
            "attachments": {
                "roles": sorted(x.get("RoleName") for x in entities.get("PolicyRoles", [])),
                "users": sorted(x.get("UserName") for x in entities.get("PolicyUsers", [])),
                "groups": sorted(x.get("GroupName") for x in entities.get("PolicyGroups", [])),
            },
        },
        "oidc": {"arn": oidc_arn, "referencing_roles": references},
        "profiles": profiles,
    }


def collect_restart(record: dict[str, Any], namespace_state: str, configmap_state: str, branch: str) -> dict[str, Any]:
    irsa_stack = stack_maybe("eksctl-eks-fargate-ops-lab-addon-iamserviceaccount-eks-fargate-ops-irsa-reader")
    cluster_stack = stack_maybe("eksctl-eks-fargate-ops-lab-cluster")
    irsa_role = role_maybe(record["irsa_role_name"])
    pod_role = role_maybe(record["pod_execution_role_name"]) if record.get("pod_execution_role_name") else None
    raw_policy = aws_maybe("NoSuchEntity", "iam", "get-policy", "--policy-arn", record["irsa_policy_arn"])
    policy = None
    if raw_policy is not None:
        version_id = raw_policy.get("Policy", {}).get("DefaultVersionId")
        version = aws("iam", "get-policy-version", "--policy-arn", record["irsa_policy_arn"], "--version-id", version_id)
        entities = aws("iam", "list-entities-for-policy", "--policy-arn", record["irsa_policy_arn"])
        policy_tags = aws("iam", "list-policy-tags", "--policy-arn", record["irsa_policy_arn"]).get("Tags", [])
        policy = {"arn": raw_policy.get("Policy", {}).get("Arn"), "policy_id": raw_policy.get("Policy", {}).get("PolicyId"), "ownership_tags": {x["Key"]: x["Value"] for x in policy_tags}, "document": version.get("PolicyVersion", {}).get("Document"), "attachments": {
            "roles": sorted(x.get("RoleName") for x in entities.get("PolicyRoles", [])),
            "users": sorted(x.get("UserName") for x in entities.get("PolicyUsers", [])),
            "groups": sorted(x.get("GroupName") for x in entities.get("PolicyGroups", [])),
        }}
    oidc_arn = f"arn:aws:iam::{record['account_id']}:oidc-provider/{record['oidc_issuer']}" if record.get("oidc_issuer") else None
    raw_oidc = aws_maybe("NoSuchEntity", "iam", "get-open-id-connect-provider", "--open-id-connect-provider-arn", oidc_arn) if oidc_arn else None
    oidc = None
    if raw_oidc is not None:
        roles = aws("iam", "list-roles").get("Roles", [])
        oidc = {"arn": oidc_arn, "referencing_roles": sorted(x.get("RoleName") for x in roles if record["oidc_issuer"] in json.dumps(x.get("AssumeRolePolicyDocument", {}), sort_keys=True))}
    listed = listed_profiles()
    profiles = []
    for name in sorted(listed):
        profile = aws("eks", "describe-fargate-profile", "--region", REGION, "--cluster-name", CLUSTER, "--fargate-profile-name", name).get("fargateProfile", {})
        profiles.append({"name": name, "describe_status": "success", "tags": profile.get("tags"), "selectors": profile.get("selectors"), "pod_role": str(profile.get("podExecutionRoleArn", "")).rsplit("/", 1)[-1]})
    logs = aws("logs", "describe-log-groups", "--region", REGION, "--log-group-name-prefix", record["log_group"]).get("logGroups", [])
    log_present = any(x.get("logGroupName") == record["log_group"] for x in logs)
    population = {
        "namespace": namespace_state, "logging_configmap": configmap_state,
        "irsa_stack": "present" if irsa_stack else "absent",
        "irsa_policy": "present" if policy else "absent",
        "oidc_provider": "present" if oidc else "absent",
        "pod_logging_policy": "present" if pod_role and "eks-fargate-ops-logging" in pod_role.get("inline", {}) else "absent",
        "workload_profile": "present" if "ops-workloads" in listed else "absent",
        "coredns_profile": "present" if "system-coredns" in listed else "absent",
        "cluster_stack": "present" if cluster_stack else "absent",
        "log_group": "present" if log_present else "absent",
    }
    return {"branch": branch, "population": population, "stacks": {"cluster_stack": cluster_stack, "irsa_stack": irsa_stack}, "irsa_role": irsa_role, "pod_role": pod_role, "irsa_policy": policy, "oidc": oidc, "profiles": profiles}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--namespace-state", choices=("present", "absent"), required=True)
    parser.add_argument("--configmap-state", choices=("present", "absent"), required=True)
    parser.add_argument("--branch", choices=("readable-cluster", "cluster-absent", "partial-readable-cluster", "partial-cluster-absent"), required=True)
    args = parser.parse_args()
    record = json.loads(args.record.read_text(encoding="utf-8"))
    snapshot = collect_restart(record, args.namespace_state, args.configmap_state, args.branch)
    validate_restart_preflight(record, snapshot, args.expected_account)
    args.snapshot.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS: complete read-only AWS preflight")


if __name__ == "__main__":
    main()
