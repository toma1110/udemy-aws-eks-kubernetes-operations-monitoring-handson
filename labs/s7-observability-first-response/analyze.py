#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

ACCOUNT_ID = re.compile(r"(?<!\d)\d{12}(?!\d)")
IAM_ARN = re.compile(r"arn:aws(?:-[a-z]+)?:iam::")


def load_document(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("input must be a JSON object")
    return document


def require_bool(obj: dict, key: str) -> bool:
    value = obj.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be boolean")
    return value


def require_choice(obj: dict, key: str, choices: set[str]) -> str:
    value = obj.get(key)
    if value not in choices:
        raise ValueError(f"{key} must be one of {sorted(choices)}")
    return value


def build_summary(document: dict) -> dict:
    if document.get("schema") != "udemy4-c010-s7-normalized-observations-v1":
        raise ValueError("unsupported observation schema")
    if document.get("region") != "ap-northeast-1":
        raise ValueError("observation Region is not ap-northeast-1")
    if document.get("cluster") != "udemy4-c010-common-20260724":
        raise ValueError("observation cluster does not match the common binding")

    addon = document.get("addon", {})
    pods = document.get("agent_pods", {})
    daemonset = document.get("daemonset", {})
    metrics = document.get("metrics", {})
    logs = document.get("logs", {})
    agent_logs = document.get("agent_logs", {})
    signals = document.get("agent_signals", {})
    configuration = document.get("configuration", {})
    for name, value in (
        ("addon", addon),
        ("agent_pods", pods),
        ("daemonset", daemonset),
        ("metrics", metrics),
        ("logs", logs),
        ("agent_logs", agent_logs),
        ("agent_signals", signals),
        ("configuration", configuration),
    ):
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be an object")

    addon_observed = require_bool(addon, "observed")
    pod_observed = require_bool(pods, "observed")
    ds_observed = require_bool(daemonset, "observed")
    metrics_observed = require_bool(metrics, "observed")
    logs_observed = require_bool(logs, "observed")
    agent_logs_observed = require_bool(agent_logs, "observed")
    agent_logs_reason = require_choice(
        agent_logs,
        "reason",
        {"observed", "unavailable", "read-denied", "no-target"},
    )
    if agent_logs_observed != (agent_logs_reason == "observed"):
        raise ValueError("agent_logs observed and reason contradict")
    if not agent_logs_observed and any(
        bool(signals.get(name, False))
        for name in ("access_denied", "network_error", "configuration_error")
    ):
        raise ValueError("unobserved agent logs cannot contain derived signals")
    container_logs_override = require_choice(
        configuration,
        "container_logs_override",
        {"enabled", "disabled", "not-specified", "not-observed"},
    )
    otel_container_insights_override = require_choice(
        configuration,
        "otel_container_insights_override",
        {"enabled", "disabled", "not-specified", "not-observed"},
    )
    classic_container_insights_override = require_choice(
        configuration,
        "classic_container_insights_override",
        {"enabled", "disabled", "not-specified", "not-observed"},
    )
    legacy_enhanced_observability_override = require_choice(
        configuration,
        "legacy_enhanced_observability_override",
        {"enabled", "disabled", "not-specified", "not-observed"},
    )
    expected_effective_log_collection = {
        "enabled": "explicitly-enabled-by-addon-override",
        "disabled": "explicitly-disabled",
        "not-specified": "not-determined",
        "not-observed": "not-observed",
    }[container_logs_override]
    if configuration.get("effective_log_collection") != expected_effective_log_collection:
        raise ValueError(
            "effective_log_collection contradicts container_logs_override"
        )
    otel_effective = {
        "enabled": "explicitly-enabled",
        "disabled": "explicitly-disabled",
        "not-specified": "disabled-by-default",
        "not-observed": "not-observed",
    }[otel_container_insights_override]
    classic_effective = {
        "enabled": "explicitly-enabled",
        "disabled": "explicitly-disabled",
        "not-specified": "default-dependent",
        "not-observed": "not-observed",
    }[classic_container_insights_override]
    legacy_effective = {
        "enabled": "explicitly-enabled",
        "disabled": "explicitly-disabled",
        "not-specified": "default-dependent",
        "not-observed": "not-observed",
    }[legacy_enhanced_observability_override]
    if otel_effective == "explicitly-enabled":
        if classic_effective == "explicitly-enabled":
            configured_mode_signal = "dual-publish-configured"
        elif classic_effective == "explicitly-disabled":
            configured_mode_signal = "otel-only-configured"
        else:
            configured_mode_signal = "otel-enabled-classic-default-dependent"
    elif classic_effective == "explicitly-enabled":
        configured_mode_signal = "classic-only-configured"
    elif (
        classic_effective == "default-dependent"
        and legacy_effective == "explicitly-enabled"
    ):
        configured_mode_signal = "legacy-classic-configured"
    elif (
        classic_effective == "explicitly-disabled"
        and otel_effective in {"explicitly-disabled", "disabled-by-default"}
    ):
        configured_mode_signal = "both-root-pipelines-disabled"
    elif "not-observed" in {otel_effective, classic_effective, legacy_effective}:
        configured_mode_signal = "not-observed"
    else:
        configured_mode_signal = "default-dependent"

    next_checks = []
    if not addon_observed:
        next_checks.append(
            "confirm-read-permission"
            if addon.get("reason") == "read-denied"
            else "confirm-addon-installation"
        )
    elif addon.get("status") != "ACTIVE":
        next_checks.append("inspect-addon-health")
    if pod_observed and (
        pods.get("non_running", 0) > 0 or pods.get("waiting_reasons", [])
    ):
        next_checks.append("inspect-pod-status-events-and-previous-logs")
    if ds_observed and daemonset.get("desired") != daemonset.get("ready"):
        next_checks.append("inspect-node-taints-capacity-and-tolerations")
    if not agent_logs_observed:
        next_checks.append(
            {
                "read-denied": "confirm-agent-log-read-permission",
                "no-target": "confirm-agent-log-target",
                "unavailable": "retry-agent-log-capture",
            }[agent_logs_reason]
        )
    else:
        if signals.get("access_denied"):
            next_checks.append("inspect-iam-or-pod-identity")
        if signals.get("network_error"):
            next_checks.append("inspect-dns-egress-or-cloudwatch-endpoint")
    if not metrics_observed:
        next_checks.append("confirm-metric-read-permission")
    elif metrics.get("series_count", 0) == 0:
        next_checks.append("inspect-enhanced-observability-and-time-range")
    if not logs_observed:
        next_checks.append("confirm-log-group-read-permission")
    elif logs.get("group_count", 0) == 0:
        next_checks.append("inspect-region-agent-log-configuration-and-iam")
    if container_logs_override == "disabled":
        next_checks.append("inspect-agent-log-collection-configuration")

    summary = {
        "schema": "udemy4-c010-s7-diagnostic-summary-v1",
        "region": document["region"],
        "cluster": document["cluster"],
        "addon": {
            "observed": addon_observed,
            "reason": addon.get("reason"),
            "status": addon.get("status"),
            "version": addon.get("version"),
            "health_issue_codes": sorted(set(addon.get("health_issue_codes", []))),
            "configuration_values_present": bool(
                addon.get("configuration_values_present", False)
            ),
        },
        "agent_pods": {
            "observed": pod_observed,
            "total": int(pods.get("total", 0)),
            "non_running": int(pods.get("non_running", 0)),
            "waiting_reasons": sorted(set(pods.get("waiting_reasons", []))),
        },
        "daemonset": {
            "observed": ds_observed,
            "desired": int(daemonset.get("desired", 0)),
            "ready": int(daemonset.get("ready", 0)),
        },
        "node_taints_observed": require_bool(document, "node_taints_observed"),
        "metrics": {
            "observed": metrics_observed,
            "series_count": int(metrics.get("series_count", 0)),
        },
        "logs": {
            "observed": logs_observed,
            "group_count": int(logs.get("group_count", 0)),
        },
        "agent_logs": {
            "observed": agent_logs_observed,
            "reason": agent_logs_reason,
        },
        "configuration": {
            "observed": require_bool(configuration, "observed"),
            "configmap_count": int(configuration.get("configmap_count", 0)),
            "agent_log_pipeline_config_present": bool(
                configuration.get("agent_log_pipeline_config_present", False)
            ),
            "container_logs_override": container_logs_override,
            "otel_container_insights_override": otel_container_insights_override,
            "classic_container_insights_override": classic_container_insights_override,
            "legacy_enhanced_observability_override": (
                legacy_enhanced_observability_override
            ),
            "effective_log_collection": expected_effective_log_collection,
            "approach_interpretation": {
                "otel": otel_effective,
                "classic_root": classic_effective,
                "legacy_nested": legacy_effective,
                "configured_mode_signal": configured_mode_signal,
            },
        },
        "agent_signals": {
            "access_denied": bool(signals.get("access_denied", False)),
            "network_error": bool(signals.get("network_error", False)),
            "configuration_error": bool(signals.get("configuration_error", False)),
        },
        "next_checks": list(dict.fromkeys(next_checks)),
        "live_proof": bool(document.get("live_proof", False)),
    }
    reject_sensitive(summary)
    return summary


def reject_sensitive(document: dict) -> None:
    encoded = json.dumps(document, ensure_ascii=False)
    if ACCOUNT_ID.search(encoded) or IAM_ARN.search(encoded):
        raise ValueError("summary contains an AWS account ID or IAM ARN")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    summary = build_summary(load_document(args.input))
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
