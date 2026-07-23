#!/usr/bin/env python3
"""Filter deterministic synthetic CloudWatch-style logs without AWS access."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_FIXTURE = ROOT / "fixtures" / "cloudwatch-logs.jsonl"
MANIFEST = ROOT / "fixtures" / "manifest.json"
EXPECTED = ROOT / "expected-results.json"
ERROR_LEVELS = {"ERROR", "CRITICAL", "FATAL"}


class LogDataError(ValueError):
    """Raised when synthetic evidence is malformed or inconsistent."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise LogDataError("timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LogDataError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise LogDataError(f"timestamp must include a timezone: {value}")
    return parsed.astimezone(timezone.utc)


def verify_manifest(fixture: Path = DEFAULT_FIXTURE) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema") != "synthetic-cloudwatch-logs-fixture-v1":
        raise LogDataError("unsupported fixture manifest schema")
    if fixture.resolve() == DEFAULT_FIXTURE.resolve():
        expected = manifest.get("files", {}).get(DEFAULT_FIXTURE.name)
        if not isinstance(expected, str) or sha256_file(fixture) != expected:
            raise LogDataError("fixture hash mismatch")


def load_logs(path: Path = DEFAULT_FIXTURE) -> list[dict[str, Any]]:
    verify_manifest(path)
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LogDataError(f"invalid JSON on line {line_number}") from exc
        required = {"timestamp", "namespace", "pod", "level", "message", "request_id"}
        if set(event) != required:
            raise LogDataError(f"line {line_number} must contain exactly {sorted(required)}")
        if not all(isinstance(event[key], str) and event[key] for key in required):
            raise LogDataError(f"line {line_number} fields must be non-empty strings")
        parse_timestamp(event["timestamp"])
        events.append(event)
    if not events:
        raise LogDataError("fixture contains no events")
    identities = [(event["timestamp"], event["namespace"], event["pod"], event["request_id"]) for event in events]
    if len(identities) != len(set(identities)):
        raise LogDataError("fixture contains duplicate event identities")
    return events


def filter_logs(
    events: list[dict[str, Any]],
    *,
    namespace: str | None = None,
    pod: str | None = None,
    start: str | None = None,
    end: str | None = None,
    errors_only: bool = False,
) -> dict[str, Any]:
    start_at = parse_timestamp(start) if start else None
    end_at = parse_timestamp(end) if end else None
    if start_at and end_at and start_at > end_at:
        raise LogDataError("start must not be after end")

    selected: list[dict[str, Any]] = []
    for event in events:
        event_at = parse_timestamp(event["timestamp"])
        if namespace and event["namespace"] != namespace:
            continue
        if pod and event["pod"] != pod:
            continue
        if start_at and event_at < start_at:
            continue
        if end_at and event_at > end_at:
            continue
        if errors_only and event["level"].upper() not in ERROR_LEVELS:
            continue
        selected.append(event)
    selected.sort(key=lambda item: (parse_timestamp(item["timestamp"]), item["namespace"], item["pod"]))
    return {
        "schema": "synthetic-logs-insights-result-v1",
        "query": {
            "namespace": namespace,
            "pod": pod,
            "start": start,
            "end": end,
            "errors_only": errors_only,
        },
        "count": len(selected),
        "events": selected,
    }


def check_expected() -> bool:
    events = load_logs()
    actual = {
        "namespace_pod_time": filter_logs(
            events,
            namespace="training",
            pod="checkout-7d9f",
            start="2026-07-24T10:00:00Z",
            end="2026-07-24T10:06:00Z",
        ),
        "error_timeline": filter_logs(
            events,
            namespace="training",
            start="2026-07-24T10:00:00Z",
            end="2026-07-24T10:06:00Z",
            errors_only=True,
        ),
    }
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    return actual == expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace")
    parser.add_argument("--pod")
    parser.add_argument("--start", help="ISO 8601 timestamp with timezone")
    parser.add_argument("--end", help="ISO 8601 timestamp with timezone; inclusive")
    parser.add_argument("--errors", action="store_true", help="keep ERROR/CRITICAL/FATAL")
    parser.add_argument("--check", action="store_true", help="compare both exercises with expected results")
    args = parser.parse_args()
    try:
        if args.check:
            if not check_expected():
                print("FAIL: analysis differs from expected-results.json")
                return 1
            print("PASS: fixture filters match expected-results.json")
            return 0
        result = filter_logs(
            load_logs(),
            namespace=args.namespace,
            pod=args.pod,
            start=args.start,
            end=args.end,
            errors_only=args.errors,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (LogDataError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
