#!/usr/bin/env python3
"""Analyze immutable synthetic Kubernetes evidence without a cluster."""

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
    """Raised when the fixture set is incomplete or inconsistent."""


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
    if manifest.get("schema") != "synthetic-kubernetes-fixtures-v1":
        raise EvidenceError("unsupported fixture manifest schema")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise EvidenceError("fixture manifest has no files")
    for name, expected_hash in sorted(files.items()):
        path = fixtures / name
        if not path.is_file():
            raise EvidenceError(f"missing fixture: {name}")
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise EvidenceError(f"fixture hash mismatch: {name}")


def items_by_name(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = document.get("items")
    if not isinstance(items, list):
        raise EvidenceError("list fixture must contain items")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        name = item.get("metadata", {}).get("name")
        if not isinstance(name, str) or not name or name in result:
            raise EvidenceError("fixture item names must be non-empty and unique")
        result[name] = item
    return result


def require_kind(document: dict[str, Any], expected: str, fixture_name: str) -> None:
    if document.get("kind") != expected:
        raise EvidenceError(f"{fixture_name} kind must be {expected}")


def pod_identity(document: dict[str, Any], fixture_name: str) -> tuple[str, str]:
    require_kind(document, "PodDescription", fixture_name)
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        raise EvidenceError(f"{fixture_name} metadata must be an object")
    name = metadata.get("name")
    namespace = metadata.get("namespace")
    if not isinstance(name, str) or not name:
        raise EvidenceError(f"{fixture_name} Pod name must be non-empty")
    if not isinstance(namespace, str) or not namespace:
        raise EvidenceError(f"{fixture_name} namespace must be non-empty")
    return namespace, name


def require_listed_pod(
    pods: dict[tuple[str, str], dict[str, Any]],
    identity: tuple[str, str],
    fixture_name: str,
) -> dict[str, Any]:
    if identity not in pods:
        namespace, name = identity
        raise EvidenceError(
            f"{fixture_name} target {namespace}/{name} is absent from get-pods"
        )
    return pods[identity]


def event_for(
    events: list[dict[str, Any]],
    identity: tuple[str, str],
    reason: str,
) -> dict[str, Any]:
    namespace, pod_name = identity
    matches = [
        event
        for event in events
        if event.get("involvedObject", {}).get("kind") == "Pod"
        and event.get("involvedObject", {}).get("namespace") == namespace
        and event.get("involvedObject", {}).get("name") == pod_name
        and event.get("reason") == reason
    ]
    if len(matches) != 1:
        raise EvidenceError(f"expected one {reason} Pod event for {namespace}/{pod_name}")
    return matches[0]


def analyze(fixtures: Path = DEFAULT_FIXTURES) -> dict[str, Any]:
    verify_manifest(fixtures)
    nodes_doc = load_json(fixtures / "get-nodes.json")
    namespaces_doc = load_json(fixtures / "get-namespaces.json")
    pods_doc = load_json(fixtures / "get-pods.json")
    require_kind(nodes_doc, "NodeList", "get-nodes.json")
    require_kind(namespaces_doc, "NamespaceList", "get-namespaces.json")
    require_kind(pods_doc, "PodList", "get-pods.json")
    nodes = items_by_name(nodes_doc)
    namespaces = items_by_name(namespaces_doc)
    pod_items = pods_doc.get("items")
    if not isinstance(pod_items, list):
        raise EvidenceError("get-pods.json must contain items")
    pods: dict[tuple[str, str], dict[str, Any]] = {}
    for pod in pod_items:
        metadata = pod.get("metadata", {})
        name = metadata.get("name")
        namespace = metadata.get("namespace")
        if not isinstance(name, str) or not name:
            raise EvidenceError("listed Pod name must be non-empty")
        if not isinstance(namespace, str) or not namespace:
            raise EvidenceError("listed Pod namespace must be non-empty")
        if namespace not in namespaces:
            raise EvidenceError(f"listed Pod namespace is absent: {namespace}")
        identity = (namespace, name)
        if identity in pods:
            raise EvidenceError(f"duplicate listed Pod identity: {namespace}/{name}")
        node = pod.get("status", {}).get("node")
        if node is not None and node not in nodes:
            raise EvidenceError(f"listed Pod node is absent: {namespace}/{name} -> {node}")
        pods[identity] = pod
    events_doc = load_json(fixtures / "events.json")
    require_kind(events_doc, "EventList", "events.json")
    events = events_doc.get("items")
    if not isinstance(events, list):
        raise EvidenceError("events fixture must contain items")

    not_ready = sorted(
        name
        for name, node in nodes.items()
        if node.get("status", {}).get("ready") is not True
    )
    abnormal = sorted(
        f"{namespace}/{name}"
        for (namespace, name), pod in pods.items()
        if pod.get("status", {}).get("phase") != "Running"
        or pod.get("status", {}).get("displayStatus") != "Running"
        or pod.get("status", {}).get("restarts", 0) > 0
    )

    pending = load_json(fixtures / "describe-pending-api.json")
    pending_identity = pod_identity(pending, "describe-pending-api.json")
    pending_pod = require_listed_pod(pods, pending_identity, "describe-pending-api.json")
    pending_event = event_for(events, pending_identity, "FailedScheduling")
    if pending_pod.get("status", {}).get("phase") != "Pending":
        raise EvidenceError("Pending Pod list state mismatch")
    if "Insufficient memory" not in pending_event.get("message", ""):
        raise EvidenceError("Pending evidence lacks memory scheduling message")

    crash = load_json(fixtures / "describe-crashloop-worker.json")
    crash_identity = pod_identity(crash, "describe-crashloop-worker.json")
    crash_pod = require_listed_pod(pods, crash_identity, "describe-crashloop-worker.json")
    crash_event = event_for(events, crash_identity, "BackOff")
    crash_current = (fixtures / "logs-crashloop-worker-current.txt").read_text(encoding="utf-8")
    crash_previous = (fixtures / "logs-crashloop-worker-previous.txt").read_text(encoding="utf-8")
    if crash.get("status", {}).get("displayStatus") != "CrashLoopBackOff":
        raise EvidenceError("CrashLoopBackOff describe state mismatch")
    if crash_pod.get("status", {}).get("displayStatus") != "CrashLoopBackOff":
        raise EvidenceError("CrashLoopBackOff Pod list state mismatch")
    if crash_pod.get("status", {}).get("restarts") != crash.get("status", {}).get("restartCount"):
        raise EvidenceError("CrashLoopBackOff restart count mismatch")
    if "APP_MODE is missing" not in crash_previous:
        raise EvidenceError("CrashLoopBackOff previous log lacks expected setting error")
    if "starting worker" not in crash_current:
        raise EvidenceError("CrashLoopBackOff current log lacks startup record")

    oom = load_json(fixtures / "describe-oom-reporter.json")
    oom_identity = pod_identity(oom, "describe-oom-reporter.json")
    oom_pod = require_listed_pod(pods, oom_identity, "describe-oom-reporter.json")
    oom_previous = (fixtures / "logs-oom-reporter-previous.txt").read_text(encoding="utf-8")
    if oom.get("status", {}).get("lastState", {}).get("reason") != "OOMKilled":
        raise EvidenceError("OOM describe evidence lacks OOMKilled")
    if oom_pod.get("status", {}).get("phase") != oom.get("status", {}).get("phase"):
        raise EvidenceError("OOM Pod phase mismatch")
    if oom_pod.get("status", {}).get("restarts") != oom.get("status", {}).get("restartCount"):
        raise EvidenceError("OOM restart count mismatch")
    if "memory pressure increased before termination" not in oom_previous:
        raise EvidenceError("OOM previous log lacks memory-pressure record")

    pending_namespace, pending_name = pending_identity
    crash_namespace, crash_name = crash_identity
    oom_namespace, oom_name = oom_identity

    return {
        "schema": "kubernetes-initial-triage-result-v1",
        "cluster_overview": {
            "node_count": len(nodes),
            "not_ready_nodes": not_ready,
            "namespace_count": len(namespaces),
            "pod_count": len(pods),
            "abnormal_candidates": abnormal,
        },
        "findings": [
            {
                "pod": pending_name,
                "namespace": pending_namespace,
                "category": "Pending",
                "evidence": [
                    "get-pods: phase Pending",
                    f"describe: PodScheduled={pending['status']['conditions']['PodScheduled']}",
                    f"event: {pending_event['reason']} / {pending_event['message']}",
                ],
                "initial_hypothesis": "Requested memory exceeds currently schedulable node capacity.",
                "next_check": "Compare Pod memory requests with allocatable node memory and other workloads.",
            },
            {
                "pod": crash_name,
                "namespace": crash_namespace,
                "category": "CrashLoopBackOff",
                "evidence": [
                    f"describe: waiting reason {crash['status']['waitingReason']}",
                    "current log: starting worker",
                    "previous log: required setting APP_MODE is missing",
                    f"event: {crash_event['reason']} / {crash_event['message']}",
                ],
                "initial_hypothesis": "The container exits during startup because a required setting is missing.",
                "next_check": "Check the workload configuration that should supply APP_MODE.",
            },
            {
                "pod": oom_name,
                "namespace": oom_namespace,
                "category": "OOMKilled",
                "evidence": [
                    f"get-pods: restarts {oom_pod['status']['restarts']}",
                    f"describe: last reason {oom['status']['lastState']['reason']}",
                    f"describe: memory limit {oom['spec']['resources']['limits']['memory']}",
                    "previous log: memory pressure increased before termination",
                ],
                "initial_hypothesis": "The container previously reached its memory limit.",
                "next_check": "Compare memory usage with requests and limits before changing resources.",
            },
        ],
        "limitations": [
            "Synthetic evidence supports initial triage practice, not a live-cluster diagnosis.",
            "Findings are hypotheses and require live metrics or configuration evidence before remediation.",
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
            expected = load_json(EXPECTED)
            if result != expected:
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
