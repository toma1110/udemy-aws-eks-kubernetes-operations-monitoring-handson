#!/usr/bin/env python3
"""Pure fail-closed guards used by the learner cleanup scripts."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ACCOUNT = re.compile(r"^[0-9]{12}$")
OIDC = re.compile(r"^oidc\.eks\.ap-northeast-1\.amazonaws\.com/id/[A-Z0-9]+$")
ROLE = re.compile(r"^[A-Za-z0-9+=,.@_-]{1,64}$")
EXPECTED_TAGS = {"Course": "c010", "Section": "s3", "ManagedBy": "learner", "Purpose": "training"}
EXPECTED_PROFILES = {"ops-workloads", "system-coredns"}
CLUSTER_STACK_TYPES = {
    "AWS::EKS::Cluster", "AWS::EC2::VPC", "AWS::EC2::Subnet", "AWS::EC2::Route",
    "AWS::EC2::RouteTable", "AWS::EC2::SubnetRouteTableAssociation", "AWS::EC2::NatGateway",
    "AWS::EC2::EIP", "AWS::EC2::InternetGateway", "AWS::EC2::VPCGatewayAttachment",
    "AWS::EC2::SecurityGroup", "AWS::EC2::SecurityGroupIngress", "AWS::EC2::SecurityGroupEgress",
    "AWS::IAM::Role", "AWS::IAM::OIDCProvider",
}


class ContractError(ValueError):
    pass


def verify_inputs(expected_account: str, actual_account: str, issuer: str, pod_role: str) -> None:
    if not ACCOUNT.fullmatch(expected_account) or actual_account != expected_account:
        raise ContractError("expected and actual AWS account must be the same 12-digit value")
    if not OIDC.fullmatch(issuer):
        raise ContractError("exact EKS OIDC issuer captured before cluster deletion is required")
    if not ROLE.fullmatch(pod_role):
        raise ContractError("exact ownership-proven Pod Execution Role name is required")


def validate_profile_results(list_succeeded: bool, listed: list[str], describes: dict[str, Any]) -> None:
    if not list_succeeded:
        raise ContractError("Fargate Profile absence requires a successful list operation")
    if not set(listed).issubset(EXPECTED_PROFILES):
        raise ContractError("unexpected Fargate Profile exists")
    for name in listed:
        result = describes.get(name)
        if not isinstance(result, dict) or result.get("status") != "success":
            raise ContractError(f"listed Fargate Profile {name} must have a successful describe")


def validate_record(record: dict[str, Any], expected_account: str) -> None:
    partial = record.get("schema") == "c010-s3-cleanup-target-v2" and record.get("capture_mode") == "partial-stack-anchor"
    expected_keys = {
        "schema", "account_id", "region", "cluster_name", "cluster_arn", "namespace",
        "ownership_tags", "oidc_issuer", "pod_execution_role_name", "irsa_role_name",
        "irsa_policy_arn", "log_group", "ownership",
    }
    if partial:
        expected_keys.add("capture_mode")
        expected_keys.add("partial_policy_identity")
    if set(record) != expected_keys:
        raise ContractError("private target record keys are missing or tampered")
    exact = {
        "account_id": expected_account,
        "region": "ap-northeast-1",
        "cluster_name": "eks-fargate-ops-lab",
        "cluster_arn": f"arn:aws:eks:ap-northeast-1:{expected_account}:cluster/eks-fargate-ops-lab",
        "namespace": "eks-fargate-ops",
        "irsa_role_name": "eks-fargate-ops-irsa-reader",
        "irsa_policy_arn": f"arn:aws:iam::{expected_account}:policy/eks-fargate-ops-describe-cluster",
        "log_group": "/aws/eks/eks-fargate-ops-lab/containers",
    }
    if record.get("schema") not in {"c010-s3-cleanup-target-v1", "c010-s3-cleanup-target-v2"}:
        raise ContractError("private target record schema is not supported")
    if any(record.get(key) != value for key, value in exact.items()):
        raise ContractError("private target record does not match the exact cleanup target")
    if record.get("ownership_tags") != EXPECTED_TAGS:
        raise ContractError("private target record ownership tags do not match")
    if partial:
        if record.get("oidc_issuer") is not None and not OIDC.fullmatch(record["oidc_issuer"]):
            raise ContractError("partial record OIDC identity is invalid")
        if record.get("pod_execution_role_name") is not None and not ROLE.fullmatch(record["pod_execution_role_name"]):
            raise ContractError("partial record Pod role identity is invalid")
    else:
        verify_inputs(expected_account, expected_account, record.get("oidc_issuer", ""), record.get("pod_execution_role_name", ""))
    ownership = record.get("ownership")
    if not isinstance(ownership, dict):
        raise ContractError("current tagged CloudFormation stack and resource inventory are required")
    cluster_stack = ownership.get("cluster_stack")
    irsa_stack = ownership.get("irsa_stack")
    for stack, expected_name in (
        (cluster_stack, "eksctl-eks-fargate-ops-lab-cluster"),
        (irsa_stack, "eksctl-eks-fargate-ops-lab-addon-iamserviceaccount-eks-fargate-ops-irsa-reader"),
    ):
        if partial and expected_name.endswith("irsa-reader") and stack is None:
            continue
        if not isinstance(stack, dict) or stack.get("stack_name") != expected_name:
            raise ContractError("exact ownership stack is required")
        if not stack.get("stack_id", "").startswith(f"arn:aws:cloudformation:ap-northeast-1:{expected_account}:stack/{expected_name}/"):
            raise ContractError("ownership stack ARN does not match")
        if stack.get("ownership_tags") != EXPECTED_TAGS or not isinstance(stack.get("resources"), list):
            raise ContractError("ownership stack tags and resource population are required")
        for resource in stack["resources"]:
            if (
                not isinstance(resource, dict)
                or not all(isinstance(resource.get(key), str) and resource[key] for key in ("logical_id", "type", "physical_id", "status"))
                or resource["status"] not in ({"CREATE_IN_PROGRESS", "CREATE_COMPLETE", "UPDATE_COMPLETE", "CREATE_FAILED", "DELETE_FAILED"} if partial else {"CREATE_COMPLETE", "UPDATE_COMPLETE"})
            ):
                raise ContractError("stack resource population contains unreadable or failed members")
    oidc_arn = f"arn:aws:iam::{expected_account}:oidc-provider/{record['oidc_issuer']}" if record.get("oidc_issuer") else None
    cluster_resources = {(x["type"], x["physical_id"]) for x in cluster_stack["resources"]}
    irsa_resources = {(x["type"], x["physical_id"]) for x in irsa_stack["resources"]} if irsa_stack else set()
    if len({x["logical_id"] for x in cluster_stack["resources"]}) != len(cluster_stack["resources"]):
        raise ContractError("cluster stack contains duplicate logical IDs")
    if any(x["type"] not in CLUSTER_STACK_TYPES for x in cluster_stack["resources"]):
        raise ContractError("cluster stack contains an unexpected resource type")
    expected_roles = {record["pod_execution_role_name"]} if record.get("pod_execution_role_name") else set()
    if {x["physical_id"] for x in cluster_stack["resources"] if x["type"] == "AWS::IAM::Role"} != expected_roles:
        raise ContractError("cluster stack IAM role population is not exact")
    stack_oidc = {x["physical_id"] for x in cluster_stack["resources"] if x["type"] == "AWS::IAM::OIDCProvider"}
    if stack_oidc and stack_oidc != ({oidc_arn} if oidc_arn else set()):
        raise ContractError("optional cluster-stack OIDC population conflicts with the exact cluster issuer")
    vpc_ids = [x["physical_id"] for x in cluster_stack["resources"] if x["type"] == "AWS::EC2::VPC"]
    nat_ids = [x["physical_id"] for x in cluster_stack["resources"] if x["type"] == "AWS::EC2::NatGateway"]
    if (not partial and (len(vpc_ids) != 1 or not nat_ids)) or len(vpc_ids) > 1 or any(not re.fullmatch(r"vpc-[0-9a-f]+", value) for value in vpc_ids) or len(nat_ids) != len(set(nat_ids)) or any(not re.fullmatch(r"nat-[0-9a-f]+", value) for value in nat_ids):
        raise ContractError("cluster stack exact VPC/NAT physical identity population is required")
    if irsa_stack and (len({x["logical_id"] for x in irsa_stack["resources"]}) != len(irsa_stack["resources"]) or any(x["type"] != "AWS::IAM::Role" for x in irsa_stack["resources"])):
        raise ContractError("iamserviceaccount stack logical-ID/type population is not exact")
    if not partial and ("AWS::IAM::Role", record["pod_execution_role_name"]) not in cluster_resources:
        raise ContractError("Pod Execution Role is not a proven cluster-stack resource")
    if not partial and ("AWS::IAM::Role", record["irsa_role_name"]) not in irsa_resources:
        raise ContractError("IRSA role is not a proven iamserviceaccount-stack resource")


def _one_statement(document: dict[str, Any]) -> dict[str, Any]:
    if set(document) != {"Version", "Statement"} or document.get("Version") != "2012-10-17":
        raise ContractError("policy or trust document must have only the exact supported Version and Statement keys")
    statements = document.get("Statement")
    if not isinstance(statements, list) or len(statements) != 1 or not isinstance(statements[0], dict):
        raise ContractError("policy or trust document must contain exactly one statement")
    return statements[0]


def _require_presence(flag: str, value: Any, label: str) -> bool:
    present = value is not None
    if (flag == "present") != present:
        raise ContractError(f"{label} presence flag and raw object disagree")
    return present


def _validate_irsa_role(role: Any, record: dict[str, Any], account: str, flag: str) -> None:
    if not _require_presence(flag, role, "IRSA role"):
        return
    issuer = record.get("oidc_issuer")
    oidc_arn = f"arn:aws:iam::{account}:oidc-provider/{issuer}"
    if role.get("name") != record["irsa_role_name"] or role.get("attached") != [record["irsa_policy_arn"]] or role.get("inline") != {}:
        raise ContractError("IRSA role policy population is not exact")
    statement = _one_statement(role.get("trust", {}))
    expected = {"Effect": "Allow", "Principal": {"Federated": oidc_arn}, "Action": "sts:AssumeRoleWithWebIdentity", "Condition": {"StringEquals": {f"{issuer}:aud": "sts.amazonaws.com", f"{issuer}:sub": "system:serviceaccount:eks-fargate-ops:irsa-reader"}}}
    if statement != expected:
        raise ContractError("IRSA trust Effect, Principal, Action, Condition, or fields are not exact")


def _validate_pod_role(role: Any, record: dict[str, Any], account: str, role_flag: str, inline_flag: str) -> None:
    if not _require_presence(role_flag, role, "Pod Execution Role"):
        if inline_flag != "absent":
            raise ContractError("Pod inline policy cannot be present without its role")
        return
    if role.get("name") != record.get("pod_execution_role_name") or role.get("attached") != ["arn:aws:iam::aws:policy/AmazonEKSFargatePodExecutionRolePolicy"]:
        raise ContractError("Pod Execution Role identity or managed attachments are not exact")
    statement = _one_statement(role.get("trust", {}))
    if statement.get("Effect") != "Allow" or statement.get("Principal") != {"Service": "eks-fargate-pods.amazonaws.com"} or statement.get("Action") != "sts:AssumeRole" or set(statement) - {"Effect", "Principal", "Action", "Condition"}:
        raise ContractError("Pod trust Effect, Principal, Action, or fields are not exact")
    allowed_conditions = ({}, {"ArnLike": {"aws:SourceArn": record["cluster_arn"]}}, {"ArnLike": {"aws:SourceArn": record["cluster_arn"]}, "StringEquals": {"aws:SourceAccount": account}})
    if statement.get("Condition", {}) not in allowed_conditions:
        raise ContractError("Pod trust Condition is not exact")
    inline = role.get("inline", {})
    expected_names = {"eks-fargate-ops-logging"} if inline_flag == "present" else set()
    if set(inline) != expected_names:
        raise ContractError("Pod inline presence flag and raw policy disagree")
    if expected_names:
        actual = _one_statement(inline["eks-fargate-ops-logging"])
        expected = {"Sid": "WriteDedicatedTrainingLogGroup", "Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:DescribeLogStreams", "logs:PutLogEvents"], "Resource": "arn:aws:logs:ap-northeast-1:*:log-group:/aws/eks/eks-fargate-ops-lab/containers:*"}
        if actual != expected:
            raise ContractError("Pod inline policy differs from the Section 3 template")


def _validate_profiles(profiles: Any, record: dict[str, Any], population: dict[str, str]) -> None:
    expected_names = {name for name, stage in (("ops-workloads", "workload_profile"), ("system-coredns", "coredns_profile")) if population[stage] == "present"}
    if not isinstance(profiles, list) or {x.get("name") for x in profiles} != expected_names or len(profiles) != len(expected_names):
        raise ContractError("Profile flags and exact raw population disagree or include an unexpected Profile")
    for item in profiles:
        expected_selector = ({"namespace": "eks-fargate-ops", "labels": {"compute": "ops-lab"}} if item["name"] == "ops-workloads" else {"namespace": "kube-system", "labels": {"k8s-app": "kube-dns"}})
        if item.get("tags") != EXPECTED_TAGS or item.get("describe_status") != "success" or item.get("selectors") != [expected_selector]:
            raise ContractError("Profile tag, selector, or describe population is not exact")
        if item["name"] == "ops-workloads" and item.get("pod_role") != record.get("pod_execution_role_name"):
            raise ContractError("workload Profile role is not exact")


def _validate_partial_population(branch: str, population: dict[str, str]) -> None:
    if set(population) != set(RESTART_STAGES) or any(value not in {"present", "absent"} for value in population.values()):
        raise ContractError("partial restart population is incomplete or unreadable")
    if branch == "partial-readable-cluster":
        def state(*present: str) -> dict[str, str]:
            value = {name: "absent" for name in RESTART_STAGES}; value.update({name: "present" for name in present}); return value
        creation = [
            state("cluster_stack"),
            state("workload_profile", "cluster_stack"),
            state("workload_profile", "coredns_profile", "cluster_stack"),
            state("namespace", "workload_profile", "coredns_profile", "cluster_stack"),
            state("namespace", "workload_profile", "coredns_profile", "cluster_stack", "log_group"),
            state("namespace", "pod_logging_policy", "workload_profile", "coredns_profile", "cluster_stack", "log_group"),
            state("namespace", "logging_configmap", "pod_logging_policy", "workload_profile", "coredns_profile", "cluster_stack", "log_group"),
            state("namespace", "logging_configmap", "oidc_provider", "pod_logging_policy", "workload_profile", "coredns_profile", "cluster_stack", "log_group"),
            state("namespace", "logging_configmap", "irsa_policy", "oidc_provider", "pod_logging_policy", "workload_profile", "coredns_profile", "cluster_stack", "log_group"),
            state("namespace", "logging_configmap", "irsa_stack", "irsa_policy", "oidc_provider", "pod_logging_policy", "workload_profile", "coredns_profile", "cluster_stack", "log_group"),
        ]
        cleanup = []
        for present in (
            ("logging_configmap", "irsa_stack", "irsa_policy", "oidc_provider", "pod_logging_policy", "workload_profile", "coredns_profile", "cluster_stack", "log_group"),
            ("irsa_stack", "irsa_policy", "oidc_provider", "pod_logging_policy", "workload_profile", "coredns_profile", "cluster_stack", "log_group"),
            ("irsa_policy", "oidc_provider", "pod_logging_policy", "workload_profile", "coredns_profile", "cluster_stack", "log_group"),
            ("oidc_provider", "pod_logging_policy", "workload_profile", "coredns_profile", "cluster_stack", "log_group"),
            ("pod_logging_policy", "workload_profile", "coredns_profile", "cluster_stack", "log_group"),
            ("workload_profile", "coredns_profile", "cluster_stack", "log_group"),
            ("coredns_profile", "cluster_stack", "log_group"), ("cluster_stack", "log_group"), ("log_group",), (),
        ):
            cleanup.append(state(*present))
        if population not in creation + cleanup:
            raise ContractError("partial readable population is not an allowed Section 3 creation or cleanup boundary")
        return
    if branch != "partial-cluster-absent":
        raise ContractError("partial record requires an explicit current-cluster branch")
    def absent_state(*present: str) -> dict[str, str]:
        value = {name: "absent" for name in RESTART_STAGES}; value.update({name: "present" for name in present}); return value
    allowed = [
        absent_state("cluster_stack"),
        absent_state("irsa_stack", "irsa_policy", "oidc_provider", "pod_logging_policy", "cluster_stack", "log_group"),
        absent_state("irsa_policy", "oidc_provider", "pod_logging_policy", "cluster_stack", "log_group"),
        absent_state("oidc_provider", "pod_logging_policy", "cluster_stack", "log_group"),
        absent_state("log_group"), absent_state(),
    ]
    if population not in allowed:
        raise ContractError("partial cluster-absent population is not an allowed creation or cleanup boundary")


RESTART_STAGES = (
    "namespace", "logging_configmap", "irsa_stack", "irsa_policy", "oidc_provider",
    "pod_logging_policy", "workload_profile", "coredns_profile", "cluster_stack", "log_group",
)


def validate_restart_population(population: dict[str, Any], branch: str = "readable-cluster") -> int:
    """Return the first present stage; only an absent prefix followed by a present suffix is valid."""
    if set(population) != set(RESTART_STAGES):
        raise ContractError("restart population is incomplete or contains an unexpected member")
    values = [population[name] for name in RESTART_STAGES]
    if any(value not in ("present", "absent") for value in values):
        raise ContractError("restart population contains an unreadable state")
    if branch == "readable-cluster":
        first_present = next((i for i, value in enumerate(values) if value == "present"), len(values))
        if any(value == "absent" for value in values[first_present:]):
            raise ContractError("cleanup stages were skipped or observed in reverse order")
        return first_present
    if branch != "cluster-absent":
        raise ContractError("restart branch is unreadable")
    base = {name: "absent" for name in RESTART_STAGES}
    allowed = []
    for present in (
        ("irsa_stack", "irsa_policy", "oidc_provider", "pod_logging_policy", "cluster_stack", "log_group"),
        ("irsa_policy", "oidc_provider", "pod_logging_policy", "cluster_stack", "log_group"),
        ("irsa_policy", "log_group"),
        ("log_group",),
        (),
    ):
        state = dict(base)
        state.update({name: "present" for name in present})
        allowed.append(state)
    if population not in allowed:
        raise ContractError("cluster-absent cleanup stages were skipped, reversed, or ambiguous")
    return allowed.index(population)


def validate_restart_preflight(record: dict[str, Any], snapshot: dict[str, Any], expected_account: str) -> int:
    validate_record(record, expected_account)
    if record.get("capture_mode") == "partial-stack-anchor":
        branch = snapshot.get("branch")
        population = snapshot.get("population", {})
        _validate_partial_population(branch, population)
        stacks = snapshot.get("stacks", {})
        if stacks.get("cluster_stack") != (record["ownership"]["cluster_stack"] if population["cluster_stack"] == "present" else None):
            raise ContractError("partial cluster stack population differs from the exact anchor")
        if stacks.get("irsa_stack") != (record["ownership"]["irsa_stack"] if population["irsa_stack"] == "present" else None):
            raise ContractError("partial IRSA stack population differs from the exact anchor")
        policy = snapshot.get("irsa_policy")
        captured_irsa_resources = (record["ownership"].get("irsa_stack") or {}).get("resources", [])
        captured_irsa_role = any(x.get("logical_id") == "Role1" and x.get("type") == "AWS::IAM::Role" and x.get("physical_id") == record["irsa_role_name"] for x in captured_irsa_resources)
        expected_irsa_role_flag = "present" if population["irsa_stack"] == "present" and captured_irsa_role else "absent"
        if population["irsa_policy"] == "present":
            identity = record.get("partial_policy_identity")
            if not isinstance(identity, dict) or set(identity) != {"policy_id", "ownership_tags"} or identity.get("ownership_tags") != EXPECTED_TAGS:
                raise ContractError("partial same-name policy lacks captured immutable identity and ownership tags; hand off to the owner")
            allowed_roles = [record["irsa_role_name"]] if expected_irsa_role_flag == "present" else []
            if not isinstance(policy, dict) or policy.get("arn") != record["irsa_policy_arn"] or policy.get("policy_id") != identity["policy_id"] or policy.get("ownership_tags") != EXPECTED_TAGS or policy.get("attachments") != {"roles": allowed_roles, "users": [], "groups": []}:
                raise ContractError("partial IRSA policy identity or attachments are ambiguous")
            if _one_statement(policy.get("document", {})) != {"Sid": "DescribeDedicatedTrainingCluster", "Effect": "Allow", "Action": "eks:DescribeCluster", "Resource": "arn:aws:eks:ap-northeast-1:*:cluster/eks-fargate-ops-lab"}:
                raise ContractError("partial IRSA policy document is not exact")
        elif policy is not None:
            raise ContractError("partial IRSA policy presence is inconsistent")
        _validate_irsa_role(snapshot.get("irsa_role"), record, expected_account, expected_irsa_role_flag)
        oidc = snapshot.get("oidc")
        if _require_presence(population["oidc_provider"], oidc, "OIDC provider"):
            expected_oidc_arn = f"arn:aws:iam::{expected_account}:oidc-provider/{record['oidc_issuer']}" if record.get("oidc_issuer") else None
            expected_refs = [record["irsa_role_name"]] if expected_irsa_role_flag == "present" else []
            if oidc != {"arn": expected_oidc_arn, "referencing_roles": expected_refs}:
                raise ContractError("partial OIDC identity or referencing roles drifted from the stack anchor")
        pod_flag = "present" if record.get("pod_execution_role_name") and population["cluster_stack"] == "present" else "absent"
        _validate_pod_role(snapshot.get("pod_role"), record, expected_account, pod_flag, population["pod_logging_policy"])
        _validate_profiles(snapshot.get("profiles"), record, population)
        return 0
    boundary = validate_restart_population(snapshot.get("population", {}), snapshot.get("branch", ""))
    population = snapshot["population"]
    stacks = snapshot.get("stacks", {})
    for key, stage in (("irsa_stack", "irsa_stack"), ("cluster_stack", "cluster_stack")):
        expected = record["ownership"][key] if population[stage] == "present" else None
        if stacks.get(key) != expected:
            raise ContractError("current stack population is absent out of order or differs from the exact captured population")

    issuer = record["oidc_issuer"]
    oidc_arn = f"arn:aws:iam::{expected_account}:oidc-provider/{issuer}"
    irsa = snapshot.get("irsa_role")
    _validate_irsa_role(irsa, record, expected_account, population["irsa_stack"])

    policy = snapshot.get("irsa_policy")
    if population["irsa_policy"] == "present":
        expected_roles = [record["irsa_role_name"]] if population["irsa_stack"] == "present" else []
        if not isinstance(policy, dict) or policy.get("arn") != record["irsa_policy_arn"] or policy.get("attachments") != {"roles": expected_roles, "users": [], "groups": []}:
            raise ContractError("present IRSA policy identity or attachments are not exact")
        if _one_statement(policy.get("document", {})) != {"Sid": "DescribeDedicatedTrainingCluster", "Effect": "Allow", "Action": "eks:DescribeCluster", "Resource": "arn:aws:eks:ap-northeast-1:*:cluster/eks-fargate-ops-lab"}:
            raise ContractError("present IRSA policy document is not exact")
    elif policy is not None:
        raise ContractError("IRSA policy remains after its deletion stage")

    oidc = snapshot.get("oidc")
    if population["oidc_provider"] == "present":
        expected_refs = [record["irsa_role_name"]] if population["irsa_stack"] == "present" else []
        if oidc != {"arn": oidc_arn, "referencing_roles": expected_refs}:
            raise ContractError("present OIDC identity or reference population is not exact")
    elif oidc is not None:
        raise ContractError("OIDC provider remains after its deletion stage")

    pod = snapshot.get("pod_role")
    _validate_pod_role(pod, record, expected_account, population["cluster_stack"], population["pod_logging_policy"])
    _validate_profiles(snapshot.get("profiles"), record, population)
    return boundary


def validate_execute_preflight(record: dict[str, Any], snapshot: dict[str, Any], expected_account: str) -> None:
    validate_record(record, expected_account)
    if snapshot.get("stacks") != record.get("ownership"):
        raise ContractError("current stack population differs from the captured ownership population")
    cluster_arn = record["cluster_arn"]
    issuer = record["oidc_issuer"]
    oidc_arn = f"arn:aws:iam::{expected_account}:oidc-provider/{issuer}"

    irsa = snapshot.get("irsa_role", {})
    if irsa.get("name") != record["irsa_role_name"] or irsa.get("attached") != [record["irsa_policy_arn"]] or irsa.get("inline") != {}:
        raise ContractError("IRSA role policy population is not exact")
    trust = _one_statement(irsa.get("trust", {}))
    expected_conditions = {
        "StringEquals": {
            f"{issuer}:aud": "sts.amazonaws.com",
            f"{issuer}:sub": "system:serviceaccount:eks-fargate-ops:irsa-reader",
        }
    }
    if trust != {"Effect": "Allow", "Principal": {"Federated": oidc_arn}, "Action": "sts:AssumeRoleWithWebIdentity", "Condition": expected_conditions}:
        raise ContractError("IRSA trust contains an extra or unexpected principal, action, statement, or condition")

    pod = snapshot.get("pod_role", {})
    if pod.get("name") != record["pod_execution_role_name"] or pod.get("attached") != ["arn:aws:iam::aws:policy/AmazonEKSFargatePodExecutionRolePolicy"]:
        raise ContractError("Pod Execution Role attached population is not exact")
    pod_trust = _one_statement(pod.get("trust", {}))
    if pod_trust.get("Effect") != "Allow" or pod_trust.get("Principal") != {"Service": "eks-fargate-pods.amazonaws.com"} or pod_trust.get("Action") != "sts:AssumeRole" or set(pod_trust) - {"Effect", "Principal", "Action", "Condition"}:
        raise ContractError("Pod Execution Role trust contains an extra principal, action, or field")
    conditions = pod_trust.get("Condition", {})
    if conditions not in ({}, {"ArnLike": {"aws:SourceArn": cluster_arn}}, {"ArnLike": {"aws:SourceArn": cluster_arn}, "StringEquals": {"aws:SourceAccount": expected_account}}):
        raise ContractError("Pod Execution Role trust conditions are not exact")
    inline = pod.get("inline", {})
    if set(inline) - {"eks-fargate-ops-logging"}:
        raise ContractError("Pod Execution Role inline population is unexpected")
    if inline:
        logging_statement = _one_statement(inline["eks-fargate-ops-logging"])
        expected_logging = {
            "Sid": "WriteDedicatedTrainingLogGroup",
            "Effect": "Allow",
            "Action": ["logs:CreateLogStream", "logs:DescribeLogStreams", "logs:PutLogEvents"],
            "Resource": "arn:aws:logs:ap-northeast-1:*:log-group:/aws/eks/eks-fargate-ops-lab/containers:*",
        }
        if logging_statement != expected_logging:
            raise ContractError("Pod Execution Role inline policy document is not exact")

    policy = snapshot.get("irsa_policy", {})
    if policy.get("arn") != record["irsa_policy_arn"] or policy.get("attachments") != {"roles": [record["irsa_role_name"]], "users": [], "groups": []}:
        raise ContractError("IRSA policy is not bound only to the proven IRSA role")
    policy_statement = _one_statement(policy.get("document", {}))
    if policy_statement != {"Sid": "DescribeDedicatedTrainingCluster", "Effect": "Allow", "Action": "eks:DescribeCluster", "Resource": "arn:aws:eks:ap-northeast-1:*:cluster/eks-fargate-ops-lab"}:
        raise ContractError("IRSA policy document is not exact")

    oidc = snapshot.get("oidc", {})
    if oidc != {"arn": oidc_arn, "referencing_roles": [record["irsa_role_name"]]}:
        raise ContractError("OIDC provider references are not exact")
    profiles = snapshot.get("profiles")
    if not isinstance(profiles, list) or {x.get("name") for x in profiles} - EXPECTED_PROFILES:
        raise ContractError("Fargate Profile population is unexpected")
    for item in profiles:
        if item.get("tags") != EXPECTED_TAGS or item.get("describe_status") != "success":
            raise ContractError("Fargate Profile ownership or describe status is not exact")
        if item.get("name") == "ops-workloads" and item.get("pod_role") != record["pod_execution_role_name"]:
            raise ContractError("workload Profile role is not ownership-bound")
        expected_selector = ({"namespace": "eks-fargate-ops", "labels": {"compute": "ops-lab"}}
                             if item.get("name") == "ops-workloads"
                             else {"namespace": "kube-system", "labels": {"k8s-app": "kube-dns"}})
        if item.get("selectors") != [expected_selector]:
            raise ContractError("Fargate Profile selector is not exact")


def decide_irsa_cleanup(record: dict[str, Any], snapshot: dict[str, Any], expected_account: str) -> dict[str, str]:
    """Return the deterministic IRSA action only after the restart contract passes."""
    validate_restart_preflight(record, snapshot, expected_account)
    if snapshot["population"]["irsa_stack"] == "absent":
        return {"action": "none", "plan": "IRSA stack and role are already absent"}
    if snapshot["branch"] in {"readable-cluster", "partial-readable-cluster"} and snapshot.get("irsa_role") is not None:
        return {"action": "delete-iamserviceaccount", "plan": "delete exact iamserviceaccount through eksctl"}
    return {"action": "delete-exact-stack", "plan": "delete exact captured iamserviceaccount CloudFormation stack"}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    verify = sub.add_parser("verify-inputs")
    verify.add_argument("--expected-account", required=True)
    verify.add_argument("--actual-account", required=True)
    verify.add_argument("--issuer", required=True)
    verify.add_argument("--pod-role", required=True)
    record = sub.add_parser("validate-record")
    record.add_argument("--path", type=Path, required=True)
    record.add_argument("--expected-account", required=True)
    preflight = sub.add_parser("validate-preflight")
    preflight.add_argument("--record", type=Path, required=True)
    preflight.add_argument("--snapshot", type=Path, required=True)
    preflight.add_argument("--expected-account", required=True)
    restart = sub.add_parser("validate-restart")
    restart.add_argument("--record", type=Path, required=True)
    restart.add_argument("--snapshot", type=Path, required=True)
    restart.add_argument("--expected-account", required=True)
    decision = sub.add_parser("decide-irsa-cleanup")
    decision.add_argument("--record", type=Path, required=True)
    decision.add_argument("--snapshot", type=Path, required=True)
    decision.add_argument("--expected-account", required=True)
    args = parser.parse_args()
    if args.action == "verify-inputs":
        verify_inputs(args.expected_account, args.actual_account, args.issuer, args.pod_role)
    elif args.action == "validate-record":
        validate_record(json.loads(args.path.read_text(encoding="utf-8")), args.expected_account)
    elif args.action == "validate-preflight":
        validate_execute_preflight(json.loads(args.record.read_text(encoding="utf-8")), json.loads(args.snapshot.read_text(encoding="utf-8")), args.expected_account)
    elif args.action == "validate-restart":
        validate_restart_preflight(json.loads(args.record.read_text(encoding="utf-8")), json.loads(args.snapshot.read_text(encoding="utf-8")), args.expected_account)
    else:
        value = decide_irsa_cleanup(json.loads(args.record.read_text(encoding="utf-8")), json.loads(args.snapshot.read_text(encoding="utf-8")), args.expected_account)
        print(json.dumps(value, sort_keys=True))
        return
    print("PASS: runtime cleanup identity contract")


if __name__ == "__main__":
    main()
