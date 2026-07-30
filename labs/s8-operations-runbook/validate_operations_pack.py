#!/usr/bin/env python3
"""Validate the deterministic Section 8 learner artifacts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path


PLACEHOLDER = re.compile(r"<[^>\n]+>")
ACCOUNT_ID = re.compile(r"(?<!\d)\d{12}(?!\d)")
ARN = re.compile(r"\barn:(?:aws|aws-cn|aws-us-gov):")

RUNBOOK_SECTIONS = (
    "基本情報",
    "観察した事実",
    "まだ分からないこと",
    "仮説",
    "次の安全な確認",
    "エスカレーション条件",
    "コストとcleanup",
)

CLEANUP_ORDER = (
    "section-specific-resources",
    "services-and-ingresses",
    "managed-nodes-and-fargate",
    "common-cluster-stack",
    "fixed-residual-verification",
    "cleanup-guard-last",
)

RESIDUAL_CHECKS = {
    "eks",
    "ec2",
    "ebs",
    "eni",
    "load-balancers",
    "cloudwatch",
    "cloudformation",
}


def _parse_utc(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a UTC timestamp")
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYY-MM-DDTHH:MM:SSZ") from exc
    if parsed.tzinfo is not None:
        raise ValueError(f"{field} must use the literal Z form")


def validate_runbook(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for section in RUNBOOK_SECTIONS:
        if f"## {section}" not in text:
            raise ValueError(f"missing runbook section: {section}")
    if PLACEHOLDER.search(text):
        raise ValueError("runbook still contains a placeholder")
    if ACCOUNT_ID.search(text) or ARN.search(text):
        raise ValueError("runbook contains an account ID or ARN")
    for label in (
        "記録時刻:",
        "症状:",
        "影響範囲:",
        "変更承認者:",
        "Pod:",
        "Node:",
        "Event:",
        "Log / Metric:",
        "権限:",
        "所有権を確認した方法:",
        "削除順序:",
        "残存確認:",
    ):
        if label not in text:
            raise ValueError(f"missing runbook field: {label}")


def validate_inventory(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "c010-s8-cost-cleanup-inventory-v1":
        raise ValueError("unexpected inventory schema")
    if data.get("region") != "ap-northeast-1":
        raise ValueError("inventory Region must be ap-northeast-1")
    _parse_utc(data.get("observed_at"), "observed_at")
    _parse_utc(data.get("official_pricing_checked_at"), "official_pricing_checked_at")
    if not isinstance(data.get("live_aws_execution"), bool):
        raise ValueError("live_aws_execution must be boolean")

    resources = data.get("resources")
    if not isinstance(resources, list) or not resources:
        raise ValueError("inventory must contain at least one resource")
    for index, resource in enumerate(resources):
        if not isinstance(resource, dict):
            raise ValueError(f"resource {index} must be an object")
        required = {
            "resource_type",
            "resource_name",
            "ownership",
            "cost_driver",
            "deletion_authorized",
            "decision",
        }
        if set(resource) != required:
            raise ValueError(f"resource {index} fields do not match the contract")
        if any(
            not isinstance(resource[field], str) or not resource[field].strip()
            for field in required - {"deletion_authorized"}
        ):
            raise ValueError(f"resource {index} has an empty text field")
        if not isinstance(resource["deletion_authorized"], bool):
            raise ValueError(f"resource {index} deletion_authorized must be boolean")
        unknown = resource["ownership"] == "unknown" or resource["cost_driver"] == "unknown"
        if unknown and (
            resource["deletion_authorized"]
            or resource["decision"] != "do-not-delete-in-this-lab"
        ):
            raise ValueError(f"resource {index} permits unsafe deletion")

    if tuple(data.get("cleanup_order", [])) != CLEANUP_ORDER:
        raise ValueError("cleanup order is incomplete or reordered")
    if set(data.get("residual_checks", [])) != RESIDUAL_CHECKS:
        raise ValueError("residual checks are incomplete")
    if data.get("unknown_cost_or_ownership_action") != "stop-and-escalate":
        raise ValueError("unknown cost or ownership must stop and escalate")

    encoded = json.dumps(data, ensure_ascii=False)
    if ACCOUNT_ID.search(encoded) or ARN.search(encoded):
        raise ValueError("inventory contains an account ID or ARN")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("runbook", "inventory"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        if args.kind == "runbook":
            validate_runbook(args.path)
            print("PASS: runbook contract is complete")
        else:
            validate_inventory(args.path)
            print("PASS: cost and cleanup inventory is safe")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
