#!/usr/bin/env python3
"""Analyze immutable synthetic Pending and CrashLoopBackOff evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_FIXTURES = ROOT / "fixtures"
EXPECTED = ROOT / "expected-results.json"


class EvidenceError(ValueError):
    """Raised when evidence is incomplete, inconsistent, or cross-bound."""


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(fixtures: Path) -> None:
    manifest = load_json(fixtures / "manifest.json")
    if manifest.get("schema") != "synthetic-pod-resource-triage-fixtures-v1":
        raise EvidenceError("unsupported fixture manifest schema")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise EvidenceError("fixture manifest has no files")
    actual_names = {
        path.name for path in fixtures.iterdir()
        if path.is_file() and path.name != "manifest.json"
    }
    if set(files) != actual_names:
        raise EvidenceError("fixture manifest population mismatch")
    for name, expected_hash in sorted(files.items()):
        path = fixtures / name
        if not path.is_file():
            raise EvidenceError(f"missing fixture: {name}")
        if sha256_file(path) != expected_hash:
            raise EvidenceError(f"fixture hash mismatch: {name}")


def require_kind(document: dict[str, Any], expected: str, fixture: str) -> None:
    if document.get("kind") != expected:
        raise EvidenceError(f"{fixture} kind must be {expected}")


def listed_items(document: dict[str, Any], kind: str, fixture: str) -> list[dict[str, Any]]:
    require_kind(document, kind, fixture)
    items = document.get("items")
    if not isinstance(items, list):
        raise EvidenceError(f"{fixture} must contain items")
    return items


def identity(document: dict[str, Any], fixture: str) -> tuple[str, str]:
    require_kind(document, "PodDescription", fixture)
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        raise EvidenceError(f"{fixture} metadata must be an object")
    namespace = metadata.get("namespace")
    name = metadata.get("name")
    if not isinstance(namespace, str) or not namespace:
        raise EvidenceError(f"{fixture} namespace must be non-empty")
    if not isinstance(name, str) or not name:
        raise EvidenceError(f"{fixture} Pod name must be non-empty")
    return namespace, name


def exact_event(
    events: list[dict[str, Any]],
    pod_identity: tuple[str, str],
    reason: str,
) -> dict[str, Any]:
    namespace, name = pod_identity
    matches = [
        item for item in events
        if item.get("involvedObject", {}).get("kind") == "Pod"
        and item.get("involvedObject", {}).get("namespace") == namespace
        and item.get("involvedObject", {}).get("name") == name
        and item.get("reason") == reason
    ]
    if len(matches) != 1:
        raise EvidenceError(f"expected one {reason} Pod event for {namespace}/{name}")
    return matches[0]


def text(fixtures: Path, name: str) -> str:
    return (fixtures / name).read_text(encoding="utf-8")


def analyze(fixtures: Path = DEFAULT_FIXTURES) -> dict[str, Any]:
    verify_manifest(fixtures)

    node_items = listed_items(load_json(fixtures / "get-nodes.json"), "NodeList", "get-nodes.json")
    pod_items = listed_items(load_json(fixtures / "get-pods.json"), "PodList", "get-pods.json")
    events = listed_items(load_json(fixtures / "events.json"), "EventList", "events.json")

    nodes: dict[str, dict[str, Any]] = {}
    for node in node_items:
        name = node.get("metadata", {}).get("name")
        if not isinstance(name, str) or not name or name in nodes:
            raise EvidenceError("Node names must be non-empty and unique")
        nodes[name] = node

    pods: dict[tuple[str, str], dict[str, Any]] = {}
    for pod in pod_items:
        metadata = pod.get("metadata", {})
        namespace = metadata.get("namespace")
        name = metadata.get("name")
        if not isinstance(namespace, str) or not namespace:
            raise EvidenceError("listed Pod namespace must be non-empty")
        if not isinstance(name, str) or not name:
            raise EvidenceError("listed Pod name must be non-empty")
        pod_identity = (namespace, name)
        if pod_identity in pods:
            raise EvidenceError(f"duplicate Pod identity: {namespace}/{name}")
        node_name = pod.get("status", {}).get("node")
        if node_name is not None and node_name not in nodes:
            raise EvidenceError(f"unknown assigned Node: {namespace}/{name}")
        pods[pod_identity] = pod

    def described(name: str) -> tuple[dict[str, Any], tuple[str, str], dict[str, Any]]:
        fixture_name = f"describe-{name}.json"
        document = load_json(fixtures / fixture_name)
        pod_identity = identity(document, fixture_name)
        if pod_identity not in pods:
            raise EvidenceError(f"described Pod absent from list: {pod_identity[0]}/{pod_identity[1]}")
        return document, pod_identity, pods[pod_identity]

    pending_capacity, capacity_id, capacity_listed = described("pending-capacity")
    capacity_event = exact_event(events, capacity_id, "FailedScheduling")
    if capacity_listed.get("status", {}).get("phase") != "Pending":
        raise EvidenceError("pending-capacity list phase mismatch")
    if pending_capacity.get("spec", {}).get("resources", {}).get("requests", {}).get("memory") != "5Gi":
        raise EvidenceError("pending-capacity memory request mismatch")
    if pending_capacity.get("status", {}).get("conditions", {}).get("PodScheduled") is not False:
        raise EvidenceError("pending-capacity lacks PodScheduled=False")
    if "Insufficient memory" not in capacity_event.get("message", ""):
        raise EvidenceError("pending-capacity event lacks memory evidence")

    pending_taint, taint_id, taint_listed = described("pending-taint")
    taint_event = exact_event(events, taint_id, "FailedScheduling")
    if taint_listed.get("status", {}).get("phase") != "Pending":
        raise EvidenceError("pending-taint list phase mismatch")
    if pending_taint.get("spec", {}).get("tolerations") != []:
        raise EvidenceError("pending-taint must have no tolerations")
    if "untolerated taint" not in taint_event.get("message", ""):
        raise EvidenceError("pending-taint event lacks taint evidence")

    pending_affinity, affinity_id, affinity_listed = described("pending-affinity")
    affinity_event = exact_event(events, affinity_id, "FailedScheduling")
    if affinity_listed.get("status", {}).get("phase") != "Pending":
        raise EvidenceError("pending-affinity list phase mismatch")
    selector = pending_affinity.get("spec", {}).get("nodeSelector", {})
    affinity = pending_affinity.get("spec", {}).get("requiredNodeAffinity", {})
    if selector.get("workload") != "gpu" or affinity.get("zone") != "ap-northeast-1c":
        raise EvidenceError("pending-affinity constraints mismatch")
    if "node affinity/selector" not in affinity_event.get("message", ""):
        raise EvidenceError("pending-affinity event lacks selector evidence")
    if any(
        node.get("metadata", {}).get("labels", {}).get("workload") == "gpu"
        and node.get("metadata", {}).get("labels", {}).get("zone") == "ap-northeast-1c"
        for node in nodes.values()
    ):
        raise EvidenceError("pending-affinity unexpectedly has a matching Node")

    crash_app, app_id, app_listed = described("crashloop-app")
    app_event = exact_event(events, app_id, "BackOff")
    app_previous = text(fixtures, "logs-crashloop-app-previous.txt")
    if app_listed.get("status", {}).get("displayStatus") != "CrashLoopBackOff":
        raise EvidenceError("crashloop-app list state mismatch")
    if crash_app.get("status", {}).get("lastState") != {"reason": "Error", "exitCode": 1}:
        raise EvidenceError("crashloop-app termination evidence mismatch")
    if "APP_MODE is missing" not in app_previous:
        raise EvidenceError("crashloop-app previous log lacks application error")

    crash_oom, oom_id, oom_listed = described("crashloop-oom")
    oom_event = exact_event(events, oom_id, "BackOff")
    oom_previous = text(fixtures, "logs-crashloop-oom-previous.txt")
    if oom_listed.get("status", {}).get("displayStatus") != "CrashLoopBackOff":
        raise EvidenceError("crashloop-oom list state mismatch")
    if crash_oom.get("status", {}).get("lastState") != {"reason": "OOMKilled", "exitCode": 137}:
        raise EvidenceError("crashloop-oom termination evidence mismatch")
    if crash_oom.get("spec", {}).get("resources", {}).get("limits", {}).get("memory") != "256Mi":
        raise EvidenceError("crashloop-oom memory limit mismatch")
    if "memory allocation failed" not in oom_previous:
        raise EvidenceError("crashloop-oom previous log lacks memory evidence")

    crash_probe, probe_id, probe_listed = described("crashloop-probe")
    probe_event = exact_event(events, probe_id, "Unhealthy")
    probe_previous = text(fixtures, "logs-crashloop-probe-previous.txt")
    if probe_listed.get("status", {}).get("displayStatus") != "CrashLoopBackOff":
        raise EvidenceError("crashloop-probe list state mismatch")
    probe = crash_probe.get("spec", {}).get("livenessProbe", {})
    if probe.get("httpGet", {}).get("path") != "/healthz":
        raise EvidenceError("crashloop-probe liveness path mismatch")
    if crash_probe.get("status", {}).get("lastState") != {"reason": "Error", "exitCode": 143}:
        raise EvidenceError("crashloop-probe termination evidence mismatch")
    if "HTTP probe failed with statuscode: 500" not in probe_event.get("message", ""):
        raise EvidenceError("crashloop-probe event lacks probe evidence")
    if "received termination signal" not in probe_previous:
        raise EvidenceError("crashloop-probe previous log lacks termination evidence")

    for document, listed, label in (
        (crash_app, app_listed, "crashloop-app"),
        (crash_oom, oom_listed, "crashloop-oom"),
        (crash_probe, probe_listed, "crashloop-probe"),
    ):
        if document.get("status", {}).get("waitingReason") != "CrashLoopBackOff":
            raise EvidenceError(f"{label} waiting reason mismatch")
        if document.get("status", {}).get("restartCount") != listed.get("status", {}).get("restarts"):
            raise EvidenceError(f"{label} restart count mismatch")

    return {
        "schema": "pod-resource-first-response-v1",
        "overview": {
            "node_count": len(nodes),
            "not_ready_nodes": sorted(
                name for name, node in nodes.items()
                if node.get("status", {}).get("ready") is not True
            ),
            "pending_pods": sorted(
                f"{namespace}/{name}" for (namespace, name), pod in pods.items()
                if pod.get("status", {}).get("phase") == "Pending"
            ),
            "crashloop_pods": sorted(
                f"{namespace}/{name}" for (namespace, name), pod in pods.items()
                if pod.get("status", {}).get("displayStatus") == "CrashLoopBackOff"
            ),
        },
        "findings": [
            {
                "pod": "training/pending-capacity",
                "category": "Pending",
                "signal": "capacity",
                "evidence": [
                    "describe: memory request 5Gi and PodScheduled=False",
                    f"event: {capacity_event['message']}",
                ],
                "initial_hypothesis": "The Pod cannot currently fit available node memory.",
                "next_check": "Compare requests with allocatable memory and currently requested workload resources.",
            },
            {
                "pod": "training/pending-taint",
                "category": "Pending",
                "signal": "taint/toleration",
                "evidence": [
                    "describe: tolerations are empty",
                    f"event: {taint_event['message']}",
                ],
                "initial_hypothesis": "The Pod does not tolerate the dedicated NoSchedule taint.",
                "next_check": "Confirm whether placement on the tainted node is intended before changing tolerations.",
            },
            {
                "pod": "training/pending-affinity",
                "category": "Pending",
                "signal": "nodeSelector/affinity",
                "evidence": [
                    "describe: nodeSelector workload=gpu",
                    "describe: required node affinity zone=ap-northeast-1c",
                    f"event: {affinity_event['message']}",
                ],
                "initial_hypothesis": "No Node satisfies both required placement constraints.",
                "next_check": "Compare intended placement with exact Node labels before changing selector or affinity.",
            },
            {
                "pod": "training/crashloop-app",
                "category": "CrashLoopBackOff",
                "signal": "application failure",
                "evidence": [
                    "describe: previous reason Error and exit code 1",
                    "previous log: required setting APP_MODE is missing",
                    f"event: {app_event['message']}",
                ],
                "initial_hypothesis": "The application exits because a required setting is absent.",
                "next_check": "Inspect the workload configuration source for APP_MODE.",
            },
            {
                "pod": "training/crashloop-oom",
                "category": "CrashLoopBackOff",
                "signal": "OOMKilled",
                "evidence": [
                    "describe: previous reason OOMKilled and exit code 137",
                    "describe: memory limit 256Mi",
                    "previous log: memory allocation failed before termination",
                    f"event: {oom_event['message']}",
                ],
                "initial_hypothesis": "The container exceeded its memory limit.",
                "next_check": "Compare pre-termination memory usage with requests and limits.",
            },
            {
                "pod": "training/crashloop-probe",
                "category": "CrashLoopBackOff",
                "signal": "liveness probe",
                "evidence": [
                    "describe: liveness path /healthz",
                    "describe: previous reason Error and exit code 143",
                    f"event: {probe_event['message']}",
                    "previous log: received termination signal",
                ],
                "initial_hypothesis": "Repeated liveness probe failures trigger container termination.",
                "next_check": "Compare probe timing and path with application startup and health behavior.",
            },
        ],
        "unsupported_causes": [
            "PVC or volume binding is not inferred because no matching evidence exists.",
            "Image pull failure is not inferred because no matching evidence exists.",
        ],
        "limitations": [
            "Synthetic local evidence demonstrates an investigation sequence, not live EKS execution.",
            "Every finding is an initial hypothesis and requires target-specific live evidence before remediation.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = analyze(args.fixtures)
        if args.check:
            if result != load_json(EXPECTED):
                print("FAIL: analysis differs from expected-results.json")
                return 1
            print("PASS: fixtures and analysis match expected-results.json")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (EvidenceError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"FAIL: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
