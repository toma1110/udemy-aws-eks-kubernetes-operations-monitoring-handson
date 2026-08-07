#!/usr/bin/env python3
"""AWS-free validation of the Section 10 cleanup package."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def validate() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    cleanup = (ROOT / "cleanup.sh").read_text(encoding="utf-8")
    verify = (ROOT / "verify-residuals.sh").read_text(encoding="utf-8")
    required_readme = (
        "AWS CloudShell", "s10-l1-cleanup", "共有resource", "部分作成",
        "EXPECTED_AWS_ACCOUNT_ID", "CONFIRM_CLEANUP_TARGET", "--plan", "--execute",
        "EKS", "Fargate", "IAM", "CloudWatch Logs", "VPC", "NAT Gateway",
        "cleanup-record.md", "capture-target-record.sh", "execute_preflight.py", "TARGET_RECORD_PATH",
        "CLEANUP_DEADLINE_EPOCH", "60分",
    )
    missing = [term for term in required_readme if term not in readme]
    if missing:
        raise ValueError(f"README missing required terms: {missing}")

    gates = (
        "aws sts get-caller-identity", "EXPECTED_CLUSTER_ARN=", "describe-cluster",
        "current-context", "namespace ownership labels", "list-fargate-profiles",
        "logging ConfigMap points to a different log group", "PASS: complete read-only preflight for exact cleanup target",
    )
    for gate in gates:
        if gate not in cleanup:
            raise ValueError(f"cleanup identity gate missing: {gate}")
    mutation = "kubectl delete namespace"
    if cleanup.index("PASS: complete read-only preflight for exact cleanup target") > cleanup.index(mutation):
        raise ValueError("mutation occurs before exact target verification")

    order = (
        "kubectl delete namespace", "kubectl delete configmap", "eksctl delete iamserviceaccount",
        "aws iam delete-policy", "aws iam delete-open-id-connect-provider",
        "aws iam delete-role-policy", "aws eks delete-fargate-profile",
        "eksctl delete cluster", "aws logs delete-log-group",
    )
    positions = [cleanup.index(term) for term in order]
    if positions != sorted(positions):
        raise ValueError("cleanup command order changed")

    for forbidden in ("delete-vpc", "delete-nat-gateway", "kubectl delete namespace aws-observability"):
        if forbidden in cleanup:
            raise ValueError(f"broad/shared deletion is forbidden: {forbidden}")
    for service in ("describe-cluster", "list-fargate-profiles", "describe-fargate-profile", "get-role", "get-role-policy", "get-policy", "get-open-id-connect-provider", "describe-log-groups", "list-stacks", "describe-vpcs", "describe-nat-gateways"):
        if service not in verify:
            raise ValueError(f"residual check missing: {service}")
    for term in ("listed Fargate Profile describe failed", "TARGET_RECORD_PATH", "execute_preflight.py", "decide-irsa-cleanup", "remaining_seconds", "run_bounded", "run_residual_check"):
        if term not in cleanup:
            raise ValueError(f"cleanup safety contract missing: {term}")
    inventory = json.loads((ROOT / "package-inventory.json").read_text(encoding="utf-8"))
    cache_dirs = [p for p in ROOT.rglob("__pycache__") if p.is_dir()]
    if cache_dirs:
        raise ValueError("generated __pycache__ directories are forbidden package artifacts")
    actual = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in ROOT.rglob("*") if p.is_file() and p.name != "package-inventory.json"
    }
    if inventory.get("schema") != "s10-cleanup-package-inventory-v2" or inventory.get("files") != actual:
        raise ValueError("package inventory does not match current bytes")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.parse_args()
    validate()
    print("PASS: Section 10 cleanup package satisfies the local safety contract")


if __name__ == "__main__":
    main()
