#!/usr/bin/env python3
"""Capture a complete or ownership-anchored partial cleanup target record."""
import argparse
import json
import os
import subprocess
from pathlib import Path

REGION = "ap-northeast-1"
CLUSTER = "eks-fargate-ops-lab"
TAGS = {"Course": "c010", "Section": "s3", "ManagedBy": "learner", "Purpose": "training"}
IRSA_ROLE_LOGICAL_ID = "Role1"
IRSA_ROLE_NAME = "eks-fargate-ops-irsa-reader"
SUCCESSFUL_RESOURCE_STATES = {"CREATE_COMPLETE", "UPDATE_COMPLETE"}

def aws(*args, absent=()):
    process = subprocess.run(["aws", *args, "--output", "json"], text=True, capture_output=True)
    if process.returncode:
        if any(marker in process.stderr for marker in absent):
            return None
        raise SystemExit("STOP: read-only target capture failed")
    return json.loads(process.stdout)

def stack(name, optional=False):
    described = aws("cloudformation", "describe-stacks", "--region", REGION, "--stack-name", name, absent=("does not exist",) if optional else ())
    if described is None:
        return None
    members = aws("cloudformation", "list-stack-resources", "--region", REGION, "--stack-name", name)["StackResourceSummaries"]
    item = described["Stacks"][0]
    resources = [{"logical_id": x["LogicalResourceId"], "type": x["ResourceType"], "physical_id": x.get("PhysicalResourceId"), "status": x["ResourceStatus"]} for x in members]
    return {"stack_name": item["StackName"], "stack_id": item["StackId"], "ownership_tags": {x["Key"]: x["Value"] for x in item.get("Tags", []) if x["Key"] in TAGS}, "resources": sorted(resources, key=lambda x: (x["logical_id"], x["type"], str(x["physical_id"])))}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("account")
    args = parser.parse_args()
    cluster_stack = stack(f"eksctl-{CLUSTER}-cluster")
    irsa_stack = stack(f"eksctl-{CLUSTER}-addon-iamserviceaccount-eks-fargate-ops-irsa-reader", optional=True)
    cluster = aws("eks", "describe-cluster", "--region", REGION, "--name", CLUSTER, absent=("ResourceNotFoundException",))
    profile = None if cluster is None else aws("eks", "describe-fargate-profile", "--region", REGION, "--cluster-name", CLUSTER, "--fargate-profile-name", "ops-workloads", absent=("ResourceNotFoundException",))
    resources = cluster_stack["resources"]
    roles = [x["physical_id"] for x in resources if x["type"] == "AWS::IAM::Role"]
    oidcs = [x["physical_id"] for x in resources if x["type"] == "AWS::IAM::OIDCProvider"]
    irsa_role_complete = irsa_stack is not None and any(
        resource.get("logical_id") == IRSA_ROLE_LOGICAL_ID
        and resource.get("type") == "AWS::IAM::Role"
        and resource.get("physical_id") == IRSA_ROLE_NAME
        and resource.get("status") in SUCCESSFUL_RESOURCE_STATES
        for resource in irsa_stack["resources"]
    )
    complete = cluster is not None and profile is not None and irsa_role_complete
    issuer = cluster["cluster"]["identity"]["oidc"]["issuer"].removeprefix("https://") if cluster is not None else (oidcs[0].split("oidc-provider/", 1)[1] if len(oidcs) == 1 else None)
    if cluster is not None:
        exact_oidc_arn = f"arn:aws:iam::{args.account}:oidc-provider/{issuer}"
        aws("iam", "get-open-id-connect-provider", "--open-id-connect-provider-arn", exact_oidc_arn)
    pod_role = profile["fargateProfile"]["podExecutionRoleArn"].rsplit("/", 1)[-1] if complete else (roles[0] if len(roles) == 1 else None)
    record = {"schema": "c010-s3-cleanup-target-v1" if complete else "c010-s3-cleanup-target-v2", "account_id": args.account, "region": REGION, "cluster_name": CLUSTER, "cluster_arn": f"arn:aws:eks:{REGION}:{args.account}:cluster/{CLUSTER}", "namespace": "eks-fargate-ops", "ownership_tags": TAGS, "oidc_issuer": issuer, "pod_execution_role_name": pod_role, "irsa_role_name": IRSA_ROLE_NAME, "irsa_policy_arn": f"arn:aws:iam::{args.account}:policy/eks-fargate-ops-describe-cluster", "log_group": f"/aws/eks/{CLUSTER}/containers", "ownership": {"cluster_stack": cluster_stack, "irsa_stack": irsa_stack}}
    if not complete:
        record["capture_mode"] = "partial-stack-anchor"
        policy = aws("iam", "get-policy", "--policy-arn", record["irsa_policy_arn"], absent=("NoSuchEntity",))
        policy_tags = None if policy is None else aws("iam", "list-policy-tags", "--policy-arn", record["irsa_policy_arn"]).get("Tags", [])
        tags = {} if policy_tags is None else {x["Key"]: x["Value"] for x in policy_tags}
        record["partial_policy_identity"] = ({"policy_id": policy["Policy"]["PolicyId"], "ownership_tags": TAGS} if policy is not None and tags == TAGS else None)
    args.path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.chmod(args.path, 0o600)

if __name__ == "__main__":
    main()
