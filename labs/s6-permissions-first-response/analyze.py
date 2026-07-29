#!/usr/bin/env python3
"""Create an account-free summary from private read-only EKS observations."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ACCOUNT_ID = re.compile(r"(?<!\d)\d{12}(?!\d)")


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def subject_matches(subject: dict[str, Any], namespace: str, name: str) -> bool:
    return (
        subject.get("kind") == "ServiceAccount"
        and subject.get("name") == name
        and subject.get("namespace") == namespace
    )


def binding_rows(document: dict[str, Any], namespace: str, name: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in document.get("items", []):
        if any(subject_matches(s, namespace, name) for s in item.get("subjects") or []):
            role_ref = item.get("roleRef") or {}
            rows.append(
                {
                    "binding_kind": str(item.get("kind", "")),
                    "binding_namespace": str((item.get("metadata") or {}).get("namespace", "")),
                    "binding_name": str((item.get("metadata") or {}).get("name", "")),
                    "role_kind": str(role_ref.get("kind", "")),
                    "role_name": str(role_ref.get("name", "")),
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            row["binding_kind"],
            row["binding_namespace"],
            row["binding_name"],
        ),
    )


def access_rows(input_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    policy_files = sorted(input_dir.glob("access-policies-*.json"))
    entry_files = sorted(input_dir.glob("access-entry-*.json"))
    policies_by_suffix = {path.stem.removeprefix("access-policies-"): path for path in policy_files}
    for path in entry_files:
        suffix = path.stem.removeprefix("access-entry-")
        entry = load_json(path).get("accessEntry") or {}
        policy_doc = (
            load_json(policies_by_suffix[suffix])
            if suffix in policies_by_suffix
            else {"associatedAccessPolicies": []}
        )
        policies = []
        for item in policy_doc.get("associatedAccessPolicies") or []:
            policy_arn = str(item.get("policyArn", ""))
            policies.append(
                {
                    "policy_name": policy_arn.rsplit("/", 1)[-1],
                    "access_scope_type": str((item.get("accessScope") or {}).get("type", "")),
                }
            )
        entries.append(
            {
                "principal_type": str(entry.get("type", "")),
                "kubernetes_group_count": len(entry.get("kubernetesGroups") or []),
                "associated_policies": sorted(
                    policies,
                    key=lambda item: (item["policy_name"], item["access_scope_type"]),
                ),
            }
        )
    return sorted(
        entries,
        key=lambda item: (
            item["principal_type"],
            json.dumps(item["associated_policies"], sort_keys=True),
        ),
    )


def pod_identity_rows(input_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(input_dir.glob("pod-identity-*.json")):
        association = load_json(path).get("association") or {}
        rows.append(
            {
                "namespace": str(association.get("namespace", "")),
                "service_account": str(association.get("serviceAccount", "")),
            }
        )
    return sorted(rows, key=lambda item: (item["namespace"], item["service_account"]))


def load_status(status_dir: Path, name: str) -> dict[str, Any]:
    path = status_dir / f"{name}.json"
    if not path.is_file():
        return {"observed": False, "reason": "status-missing"}
    document = load_json(path)
    return {
        "observed": document.get("observed") is True,
        "reason": str(document.get("reason", "invalid-status")),
    }


def detail_observation(detail: dict[str, Any]) -> dict[str, Any]:
    denied = int(detail.get("detail_access_denied_count") or 0)
    failed = int(detail.get("detail_read_failed_count") or 0)
    reasons = []
    if denied:
        reasons.append("access-denied")
    if failed:
        reasons.append("read-failed")
    return {
        "detail_failure_count": denied + failed,
        "detail_not_observed_reasons": reasons,
    }


def build_summary(
    input_dir: Path,
    namespace: str,
    service_account: str,
    status_dir: Path | None = None,
) -> dict[str, Any]:
    status_dir = status_dir or input_dir.parent / "status"
    service_account_doc = load_json(input_dir / "serviceaccount.json")
    rolebindings = load_json(input_dir / "rolebindings.json")
    clusterrolebindings = load_json(input_dir / "clusterrolebindings.json")
    annotations = (service_account_doc.get("metadata") or {}).get("annotations") or {}
    rbac = binding_rows(rolebindings, namespace, service_account)
    rbac.extend(binding_rows(clusterrolebindings, namespace, service_account))
    pod_identities = pod_identity_rows(input_dir)
    access_status = load_status(status_dir, "eks_access_list")
    pod_identity_status = load_status(status_dir, "pod_identity_list")
    access_detail_path = status_dir / "eks_access_detail.json"
    pod_detail_path = status_dir / "pod_identity_detail.json"
    access_detail = (
        load_json(access_detail_path)
        if access_detail_path.is_file()
        else {
            "listed": False,
            "entry_count": None,
            "described_count": 0,
            "policy_listed_count": 0,
            "complete": False,
        }
    )
    pod_detail = (
        load_json(pod_detail_path)
        if pod_detail_path.is_file()
        else {
            "listed": False,
            "association_count": None,
            "described_count": 0,
            "complete": False,
        }
    )
    return {
        "schema": "udemy4-c010-s6-redacted-observation-v1",
        "target": {"namespace": namespace, "service_account": service_account},
        "kubernetes_rbac": {
            "binding_count": len(rbac),
            "bindings": sorted(
                rbac,
                key=lambda row: (
                    row["binding_kind"],
                    row["binding_namespace"],
                    row["binding_name"],
                ),
            ),
        },
        "irsa_annotation": {
            "present": "eks.amazonaws.com/role-arn" in annotations,
        },
        "pod_identity": {
            "observed": pod_identity_status["observed"],
            "not_observed_reason": (
                None if pod_identity_status["observed"] else pod_identity_status["reason"]
            ),
            "complete": pod_detail.get("complete") is True,
            **detail_observation(pod_detail),
            "listed_count": pod_detail.get("association_count"),
            "described_count": int(pod_detail.get("described_count") or 0),
            "target_association_present": any(
                row["namespace"] == namespace and row["service_account"] == service_account
                for row in pod_identities
            ),
            "associations": pod_identities,
        },
        "eks_access": {
            "observed": access_status["observed"],
            "not_observed_reason": (
                None if access_status["observed"] else access_status["reason"]
            ),
            "complete": access_detail.get("complete") is True,
            **detail_observation(access_detail),
            "listed_count": access_detail.get("entry_count"),
            "described_count": int(access_detail.get("described_count") or 0),
            "policy_listed_count": int(access_detail.get("policy_listed_count") or 0),
            "entries": access_rows(input_dir),
            "interpretation": "EKS access entries authorize IAM principals to enter the cluster; they are not Pod IAM permissions.",
        },
        "interpretation": [
            "Kubernetes RBAC bindings and AWS IAM relationships are separate authorization layers.",
            "An IRSA annotation or Pod Identity association indicates a relationship, not the effective permission result.",
            "Missing monitoring data alone does not prove AccessDenied; inspect the collector, configuration, Region, and time range.",
        ],
    }


def reject_sensitive_summary(summary: dict[str, Any]) -> None:
    encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    if ACCOUNT_ID.search(encoded) or "arn:aws:iam::" in encoded:
        raise ValueError("Redacted summary contains an AWS account ID or IAM ARN.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--status", type=Path)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--service-account", required=True)
    args = parser.parse_args()
    summary = build_summary(
        args.input,
        args.namespace,
        args.service_account,
        args.status,
    )
    reject_sensitive_summary(summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
