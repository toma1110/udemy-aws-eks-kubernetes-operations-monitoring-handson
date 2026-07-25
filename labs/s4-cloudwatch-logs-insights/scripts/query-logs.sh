#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_external_binding
evidence="$(get_evidence_directory)"
window_path="$evidence/query-window.json"
[[ -f "$window_path" ]] || die "Run publish-logs.sh first."
[[ "$(jq -r '.region' "$window_path")" == "$REGION" &&
  "$(jq -r '.log_group' "$window_path")" == "$LOG_GROUP_NAME" ]] ||
  die "Query window target mismatch."
start_epoch="$(jq -er '.start_epoch | numbers' "$window_path")"
end_epoch="$(jq -er '.end_epoch | numbers' "$window_path")"
((end_epoch > start_epoch && end_epoch - start_epoch <= 900)) ||
  die "Query window must be positive and no more than 15 minutes."
pod_name="$(get_exact_job_pod_name)"

run_bounded_query() {
  local name="$1" query_path="$2" expected_count="$3"
  local query started query_id result status decoded
  query="$(<"$query_path")"
  started="$(
    aws_json logs start-query --region "$REGION" \
      --log-group-name "$LOG_GROUP_NAME" \
      --start-time "$start_epoch" \
      --end-time "$end_epoch" \
      --query-string "$query"
  )"
  query_id="$(jq -er '.queryId | strings | select(length > 0)' <<<"$started")" ||
    die "StartQuery returned no query ID."
  result=""
  status=""
  for _ in {1..30}; do
    sleep 1
    result="$(aws_json logs get-query-results --region "$REGION" --query-id "$query_id")"
    status="$(jq -r '.status' <<<"$result")"
    [[ "$status" =~ ^(Complete|Failed|Cancelled|Timeout|Unknown)$ ]] && break
  done
  [[ "$status" == "Complete" ]] || die "$name query did not complete: $status"
  decoded="$(
    jq -c '
      [.results[] |
        reduce .[] as $cell ({};
          if ($cell.field != null and $cell.field != "@ptr")
          then .[$cell.field] = $cell.value else . end
        )
      ]
    ' <<<"$result"
  )"
  [[ "$(jq -r 'length' <<<"$decoded")" == "$expected_count" ]] ||
    die "$name query returned the wrong exact row count."
  jq -e --arg namespace "$NAMESPACE" --arg pod "$pod_name" --arg name "$name" '
    all(.[]; .namespace == $namespace and .pod == $pod and
      (if $name == "errors" then .level == "ERROR" else true end))
  ' <<<"$decoded" >/dev/null ||
    die "$name query returned a row outside the exact runtime namespace/Pod/level."
  jq -n \
    --arg name "$name" \
    --arg region "$REGION" \
    --arg log_group "$LOG_GROUP_NAME" \
    --argjson start_epoch "$start_epoch" \
    --argjson end_epoch "$end_epoch" \
    --arg status "$status" \
    --argjson statistics "$(jq -c '.statistics' <<<"$result")" \
    --argjson results "$(jq -c '.results' <<<"$result")" \
    --argjson decoded_results "$decoded" \
    '{
      schema: "udemy4-s4-live-logs-insights-evidence-v1",
      name: $name,
      region: $region,
      log_group: $log_group,
      start_epoch: $start_epoch,
      end_epoch: $end_epoch,
      status: $status,
      statistics: $statistics,
      results: $results,
      decoded_results: $decoded_results
    }' >"$evidence/$name-results.json"
}

run_bounded_query "all-events" "$SCRIPT_DIR/../queries/all-events.logs-insights" 6
run_bounded_query "errors" "$SCRIPT_DIR/../queries/errors.logs-insights" 2
printf 'Bounded Logs Insights queries returned exact 6/2 rows for namespace %s and Pod %s.\n' \
  "$NAMESPACE" "$pod_name"
