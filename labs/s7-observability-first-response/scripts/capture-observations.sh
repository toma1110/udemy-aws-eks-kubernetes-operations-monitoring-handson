#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

evidence_dir="$(validate_s7_evidence_directory)"
raw="$evidence_dir/raw"
status="$evidence_dir/status"
private_log="$status/capture-private.log"
[[ -z "$(find "$raw" -mindepth 1 -maxdepth 1 ! -name cluster.json -print -quit)" ]] ||
  die "Section 7 の保存先に以前の取得ファイルが残っています。新しい S7_RUN_ID でやり直してください。"
assert_s7_target >>"$private_log" 2>&1 || {
  printf 'エラー: 対象の再確認に失敗しました。Git管理外の非公開ログを確認してください。\n' >&2
  exit 1
}

if aws_json eks describe-addon --region "$REGION" --cluster-name "$S7_CLUSTER_NAME" \
  --addon-name "$S7_ADDON_NAME" >"$raw/addon.json" 2>"$raw/addon-error-private.log"; then
  write_status "$status/addon.json" true observed
else
  if grep -Eq 'ResourceNotFoundException|No addon' "$raw/addon-error-private.log"; then
    write_status "$status/addon.json" false addon-not-found
  elif grep -Eq 'AccessDenied|Unauthorized|not authorized' "$raw/addon-error-private.log"; then
    write_status "$status/addon.json" false read-denied
  else
    write_status "$status/addon.json" false read-failed
  fi
  printf '{}\n' >"$raw/addon.json"
fi

capture_kubectl() {
  local name="$1"
  shift
  if kubectl "$@" -o json >"$raw/$name.json" 2>"$raw/$name-error-private.log"; then
    write_status "$status/$name.json" true observed
  elif grep -Eq 'NotFound|not found' "$raw/$name-error-private.log"; then
    write_status "$status/$name.json" true resource-not-found
    printf '{"items":[]}\n' >"$raw/$name.json"
  elif grep -Eq 'Forbidden|Unauthorized' "$raw/$name-error-private.log"; then
    write_status "$status/$name.json" false read-denied
    printf '{"items":[]}\n' >"$raw/$name.json"
  else
    write_status "$status/$name.json" false read-failed
    printf '{"items":[]}\n' >"$raw/$name.json"
  fi
}

capture_kubectl pods get pods -n "$S7_NAMESPACE" \
  -l app.kubernetes.io/name=cloudwatch-agent
capture_kubectl daemonsets get daemonsets -n "$S7_NAMESPACE"
capture_kubectl serviceaccounts get serviceaccounts -n "$S7_NAMESPACE"
capture_kubectl configmaps get configmaps -n "$S7_NAMESPACE"
capture_kubectl events get events -n "$S7_NAMESPACE"
capture_kubectl nodes get nodes

if jq -e '.observed == true' "$status/pods.json" >/dev/null &&
  jq -e '.items | length > 0' "$raw/pods.json" >/dev/null; then
  if kubectl logs -n "$S7_NAMESPACE" \
    -l app.kubernetes.io/name=cloudwatch-agent \
    --all-containers=true --tail=100 \
    >"$raw/agent-logs-private.txt" 2>"$raw/agent-logs-error-private.log"; then
    write_status "$status/agent-logs.json" true observed
  elif grep -Eq 'Forbidden|Unauthorized|AccessDenied|not authorized' \
    "$raw/agent-logs-error-private.log"; then
    write_status "$status/agent-logs.json" false read-denied
    : >"$raw/agent-logs-private.txt"
  else
    write_status "$status/agent-logs.json" false unavailable
    : >"$raw/agent-logs-private.txt"
  fi
elif jq -e '.observed == true' "$status/pods.json" >/dev/null; then
  write_status "$status/agent-logs.json" false no-target
  : >"$raw/agent-logs-private.txt"
else
  write_status "$status/agent-logs.json" false unavailable
  : >"$raw/agent-logs-private.txt"
fi

if aws_json cloudwatch list-metrics --region "$REGION" --namespace ContainerInsights \
  --dimensions Name=ClusterName,Value="$S7_CLUSTER_NAME" \
  >"$raw/metrics.json" 2>"$raw/metrics-error-private.log"; then
  write_status "$status/metrics.json" true observed
else
  write_status "$status/metrics.json" false read-failed
  printf '{"Metrics":[]}\n' >"$raw/metrics.json"
fi

if aws_json logs describe-log-groups --region "$REGION" \
  --log-group-name-prefix "$S7_LOG_GROUP_PREFIX" \
  >"$raw/log-groups.json" 2>"$raw/log-groups-error-private.log"; then
  write_status "$status/log-groups.json" true observed
else
  write_status "$status/log-groups.json" false read-failed
  printf '{"logGroups":[]}\n' >"$raw/log-groups.json"
fi

jq -n \
  --arg region "$REGION" \
  --arg cluster "$S7_CLUSTER_NAME" \
  --slurpfile addon_status "$status/addon.json" \
  --slurpfile addon "$raw/addon.json" \
  --slurpfile pod_status "$status/pods.json" \
  --slurpfile pods "$raw/pods.json" \
  --slurpfile ds_status "$status/daemonsets.json" \
  --slurpfile daemonsets "$raw/daemonsets.json" \
  --slurpfile node_status "$status/nodes.json" \
  --slurpfile nodes "$raw/nodes.json" \
  --slurpfile config_status "$status/configmaps.json" \
  --slurpfile configmaps "$raw/configmaps.json" \
  --slurpfile agent_log_status "$status/agent-logs.json" \
  --slurpfile metric_status "$status/metrics.json" \
  --slurpfile metrics "$raw/metrics.json" \
  --slurpfile log_status "$status/log-groups.json" \
  --slurpfile groups "$raw/log-groups.json" \
  --argjson access_denied "$(grep -Eiq "AccessDenied|not authorized" "$raw/agent-logs-private.txt" && printf true || printf false)" \
  --argjson network_error "$(grep -Eiq "timeout|timed out|no such host|connection refused|endpoint" "$raw/agent-logs-private.txt" && printf true || printf false)" \
  --argjson configuration_error "$(grep -Eiq "invalid config|configuration error|failed to parse" "$raw/agent-logs-private.txt" && printf true || printf false)" '
  ($addon[0].addon.configurationValues // "") as $configuration_text |
  ($configuration_text | fromjson? // {}) as $addon_configuration |
  {
    schema:"udemy4-c010-s7-normalized-observations-v1",
    region:$region,
    cluster:$cluster,
    addon:{
      observed:$addon_status[0].observed,
      reason:$addon_status[0].reason,
      status:($addon[0].addon.status // null),
      version:($addon[0].addon.addonVersion // null),
      health_issue_codes:[($addon[0].addon.health.issues // [])[]?.code],
      configuration_values_present:($configuration_text | length > 0)
    },
    agent_pods:{
      observed:$pod_status[0].observed,
      total:($pods[0].items | length),
      non_running:([$pods[0].items[]? | select(.status.phase != "Running")] | length),
      waiting_reasons:[
        $pods[0].items[]?.status.containerStatuses[]?.state.waiting.reason
        | select(. != null)
      ]
    },
    daemonset:{
      observed:$ds_status[0].observed,
      desired:([$daemonsets[0].items[]?.status.desiredNumberScheduled // 0] | add // 0),
      ready:([$daemonsets[0].items[]?.status.numberReady // 0] | add // 0)
    },
    node_taints_observed:$node_status[0].observed,
    metrics:{
      observed:$metric_status[0].observed,
      series_count:($metrics[0].Metrics | length)
    },
    logs:{
      observed:$log_status[0].observed,
      group_count:($groups[0].logGroups | length)
    },
    agent_logs:{
      observed:$agent_log_status[0].observed,
      reason:$agent_log_status[0].reason
    },
    configuration:{
      observed:$config_status[0].observed,
      configmap_count:($configmaps[0].items | length),
      agent_log_pipeline_config_present:any(
        $configmaps[0].items[]?.data // {} | to_entries[]?;
        (.key | test("log|fluent|otel|cwagent"; "i")) and
        (.value | type == "string" and length > 0)
      ),
      container_logs_override:
        (if $addon_status[0].observed != true then "not-observed"
         elif ($addon_configuration.containerLogs.enabled? | type) == "boolean"
         then (if $addon_configuration.containerLogs.enabled then "enabled" else "disabled" end)
         else "not-specified"
         end),
      otel_container_insights_override:
        (if $addon_status[0].observed != true then "not-observed"
         elif ($addon_configuration.otelContainerInsights.enabled? | type) == "boolean"
         then (if $addon_configuration.otelContainerInsights.enabled
               then "enabled" else "disabled" end)
         else "not-specified"
         end),
      classic_container_insights_override:
        (if $addon_status[0].observed != true then "not-observed"
         elif ($addon_configuration.containerInsights.enabled? | type) == "boolean"
         then (if $addon_configuration.containerInsights.enabled
               then "enabled" else "disabled" end)
         else "not-specified"
         end),
      legacy_enhanced_observability_override:
        (if $addon_status[0].observed != true then "not-observed"
         elif ($addon_configuration.agent.config.logs.metrics_collected.kubernetes.enhanced_container_insights? | type) == "boolean"
         then (if $addon_configuration.agent.config.logs.metrics_collected.kubernetes.enhanced_container_insights
               then "enabled" else "disabled" end)
         else "not-specified"
         end),
      effective_log_collection:
        (if $addon_status[0].observed != true then "not-observed"
         elif $addon_configuration.containerLogs.enabled? == false then "explicitly-disabled"
         elif $addon_configuration.containerLogs.enabled? == true then "explicitly-enabled-by-addon-override"
         else "not-determined"
         end)
    },
    agent_signals:{
      access_denied:$access_denied,
      network_error:$network_error,
      configuration_error:$configuration_error
    },
    live_proof:true
  }' >"$evidence_dir/normalized-observations.json"

chmod 600 "$raw"/* "$status"/* "$evidence_dir/normalized-observations.json"
printf 'Section 7 の観察結果を Git管理外の保存先へ記録しました。\n'
