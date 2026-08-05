#!/usr/bin/env python3
"""Perform deterministic, AWS-free validation of the Section 3 package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class ContractError(ValueError):
    pass


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def validate() -> None:
    readme = read("README.md")
    cluster = read("templates/cluster.yaml")
    app = read("templates/application.yaml")
    irsa_check = read("templates/irsa-check.yaml")
    logging = read("templates/logging.yaml")
    rbac = read("templates/rbac.yaml")
    policy = json.loads(read("templates/pod-execution-logging-policy.json"))
    irsa_policy = json.loads(read("templates/irsa-policy.json"))

    required_readme = (
        "AWS CloudShell", "専用の非本番", "MAX_MINUTES=\"90\"",
        "aws sts get-caller-identity", "kubectl config current-context",
        "s10-l1-cleanup", "正常値", "復旧値",
        "AWS上の実行結果はこの教材には含まれません",
        "aws --version", "eksctl version", "kubectl version --client",
        "Python 3.11", "canonical固定名", "CoreDNS", "0.215.0以上",
        "aws iam get-role --role-name eks-fargate-ops-irsa-reader",
        "NoSuchEntity", "NAMESPACE_CHECK", "(NotFound)",
        "fargate-getting-started.html",
    )
    missing = [value for value in required_readme if value not in readme]
    if missing:
        raise ContractError(f"README is missing safety terms: {missing}")
    if "0.0.0.0/0" in cluster:
        raise ContractError("cluster template must not declare a world-open CIDR")
    for value in ("eks-fargate-ops-lab", "ap-northeast-1", "gateway: Single", "name: ops-workloads", "namespace: eks-fargate-ops", "compute: ops-lab", "name: system-coredns", "namespace: kube-system", "k8s-app: kube-dns"):
        if value not in cluster:
            raise ContractError(f"cluster template is missing {value}")
    for value in ("APP_MODE: baseline", "compute: ops-lab", "readinessProbe:", "livenessProbe:", "secretKeyRef:", "level=INFO app=baseline-app"):
        if value not in app:
            raise ContractError(f"application template is missing {value}")
    for value in ("name: irsa-describe-cluster", "serviceAccountName: irsa-reader", "compute: ops-lab", "aws-cli:2.27.49", "describe-cluster", "eks-fargate-ops-lab"):
        if value not in irsa_check:
            raise ContractError(f"IRSA check template is missing {value}")
    if "aws-observability" not in logging or "[OUTPUT]" not in logging:
        raise ContractError("logging template is incomplete")
    if "[INPUT]" in logging or "[SERVICE]" in logging:
        raise ContractError("Fargate logging template contains a forbidden section")
    if "verbs: [\"get\", \"list\"]" not in rbac or "delete" in rbac:
        raise ContractError("RBAC baseline is not read-only")
    actions = policy["Statement"][0]["Action"]
    expected = {"logs:CreateLogStream", "logs:DescribeLogStreams", "logs:PutLogEvents"}
    if set(actions) != expected:
        raise ContractError("logging policy actions changed")
    if policy["Statement"][0]["Resource"] != "arn:aws:logs:ap-northeast-1:*:log-group:/aws/eks/eks-fargate-ops-lab/containers:*":
        raise ContractError("logging policy is not scoped to the training log group")
    statement = irsa_policy["Statement"][0]
    if statement["Action"] != "eks:DescribeCluster" or statement["Resource"] != "arn:aws:eks:ap-northeast-1:*:cluster/eks-fargate-ops-lab":
        raise ContractError("IRSA policy is not scoped to the dedicated training cluster read")
    if "2つのprivate subnet" in readme:
        raise ContractError("README must inspect actual eksctl subnet topology, not assert a fixed count")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    validate()
    print("PASS: Section 3 templates satisfy the local safety contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
