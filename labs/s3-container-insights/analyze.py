#!/usr/bin/env python3
"""Compare synthetic Container Insights and kubectl observations."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "fixtures" / "scenarios.json"
DEFAULT_EXPECTED = ROOT / "expected-results.json"


class ObservationError(ValueError):
    """Raised when observations cannot be compared safely."""


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_time(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ObservationError(f"{field} must be an ISO 8601 UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ObservationError(f"{field} is not a valid timestamp") from exc


def verify_fixture(path: Path) -> None:
    manifest_path = path.parent / "manifest.json"
    manifest = load_json(manifest_path)
    if manifest.get("schema") != "s3-fixture-manifest-v1":
        raise ObservationError("unsupported fixture manifest schema")
    files = manifest.get("files")
    if files != {path.name: sha256(path)}:
        raise ObservationError("fixture population or hash mismatch")


def exact_target(value: Any, field: str) -> dict[str, str]:
    required = ("region", "cluster", "namespace", "workload", "pod", "node")
    if not isinstance(value, dict):
        raise ObservationError(f"{field} must be an object")
    if set(value) != set(required):
        raise ObservationError(f"{field} must contain the exact target fields")
    if any(not isinstance(value[item], str) or not value[item] for item in required):
        raise ObservationError(f"{field} target values must be non-empty strings")
    return value


def exact_window(value: Any, field: str) -> tuple[datetime, datetime]:
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        raise ObservationError(f"{field} must contain start and end")
    start = parse_time(value["start"], f"{field}.start")
    end = parse_time(value["end"], f"{field}.end")
    if start >= end:
        raise ObservationError(f"{field} start must be before end")
    return start, end


def analyze_case(case: dict[str, Any]) -> dict[str, Any]:
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id:
        raise ObservationError("case id must be a non-empty string")

    target = exact_target(case.get("target"), f"{case_id}.target")
    start, end = exact_window(case.get("window"), f"{case_id}.window")
    cloudwatch = case.get("cloudwatch")
    kubectl = case.get("kubectl")
    collection = case.get("collection")
    if not all(isinstance(item, dict) for item in (cloudwatch, kubectl, collection)):
        raise ObservationError(f"{case_id} observations must be objects")

    if exact_target(cloudwatch.get("target"), f"{case_id}.cloudwatch.target") != target:
        raise ObservationError(f"{case_id} CloudWatch target does not match")
    cloud_start, cloud_end = exact_window(
        cloudwatch.get("window"), f"{case_id}.cloudwatch.window"
    )
    if (cloud_start, cloud_end) != (start, end):
        raise ObservationError(f"{case_id} CloudWatch time window does not match")
    if exact_target(kubectl.get("target"), f"{case_id}.kubectl.target") != target:
        raise ObservationError(f"{case_id} kubectl target does not match")
    observed_at = parse_time(kubectl.get("observed_at"), f"{case_id}.kubectl.observed_at")
    if not start <= observed_at <= end:
        raise ObservationError(f"{case_id} kubectl observation is outside the time window")

    addon_status = collection.get("addon_status")
    controller_kind = collection.get("controller_kind")
    controller_name = collection.get("controller_name")
    desired = collection.get("desired")
    current = collection.get("current")
    ready = collection.get("ready")
    if controller_kind not in {"DaemonSet", "Deployment"}:
        raise ObservationError(f"{case_id} collection controller kind is unsupported")
    if not isinstance(controller_name, str) or not controller_name:
        raise ObservationError(f"{case_id} collection controller name is required")
    counts = (desired, current, ready)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in counts):
        raise ObservationError(f"{case_id} agent counts must be integers")
    if desired < 1 or current < 0 or ready < 0:
        raise ObservationError(f"{case_id} agent counts are invalid")
    if current > desired or ready > current:
        raise ObservationError(f"{case_id} agent readiness is invalid")
    collection_healthy = addon_status == "ACTIVE" and current == desired and ready == desired

    datapoints = cloudwatch.get("datapoints")
    if not isinstance(datapoints, list):
        raise ObservationError(f"{case_id} CloudWatch datapoints must be a list")
    signal = cloudwatch.get("signal")
    kubectl_signal = kubectl.get("signal")

    if not collection_healthy and not datapoints:
        classification = "collection_gap"
        reason = "CloudWatch data is absent while the add-on or Agent Pod is not healthy."
        next_check = "Inspect the collection path without changing the workload."
    elif collection_healthy and signal == "sustained_high_cpu" and kubectl_signal == "high_cpu":
        classification = "resource_anomaly"
        reason = "Healthy collection and aligned CloudWatch/kubectl observations both show high CPU."
        next_check = "Check workload impact and compare Pod demand with limits and Node capacity."
    else:
        classification = "inconclusive"
        reason = "The aligned observations do not support either conclusion."
        next_check = "Collect another aligned window and keep the conclusion open."

    return {
        "id": case_id,
        "classification": classification,
        "target": target,
        "window": case["window"],
        "collection_healthy": collection_healthy,
        "reason": reason,
        "next_check": next_check,
    }


def analyze(path: Path = DEFAULT_INPUT, verify_manifest: bool = True) -> dict[str, Any]:
    if verify_manifest:
        verify_fixture(path)
    document = load_json(path)
    if document.get("schema") != "s3-container-insights-comparison-v1":
        raise ObservationError("unsupported observation schema")
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ObservationError("at least one observation case is required")
    ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if len(ids) != len(cases) or len(ids) != len(set(ids)):
        raise ObservationError("case ids must be unique")
    return {"schema": "s3-analysis-v1", "results": [analyze_case(case) for case in cases]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    result = analyze(args.input)
    if args.check and result != load_json(DEFAULT_EXPECTED):
        raise ObservationError("analysis does not match expected-results.json")
    for item in result["results"]:
        print(f"{item['id']}: {item['classification']}")
    if args.output:
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"PASS: {len(result['results'])} observations written to {args.output}")
    elif args.check:
        print("PASS: observations match expected-results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
