#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_external_binding
evidence="$(get_evidence_directory)"
groups="$(aws_json logs describe-log-groups --region "$REGION" --log-group-name-prefix "$LOG_GROUP_NAME")"
[[ "$(jq -r --arg exact "$LOG_GROUP_NAME" '[.logGroups[] | select(.logGroupName == $exact)] | length' <<<"$groups")" == "0" ]] ||
  die "The fixed log group already exists; this script never adopts or updates it."

pod_name="$(get_exact_job_pod_name)"
rows_file="$evidence/workload-log-rows.jsonl"
kubectl logs "$pod_name" -n "$NAMESPACE" >"$rows_file"
assert_workload_log_rows "$rows_file" "$pod_name"
events_path="$evidence/put-log-events.json"
jq -R -s '
  split("\n")
  | map(select(length > 0) |
      {timestamp: ((fromjson.timestamp | fromdateiso8601) * 1000), message: .})
' "$rows_file" >"$events_path"

aws logs create-log-group --region "$REGION" --log-group-name "$LOG_GROUP_NAME" --no-cli-pager
aws logs tag-log-group --region "$REGION" --log-group-name "$LOG_GROUP_NAME" \
  --tags '{"Course":"C010","ManagedBy":"udemy4","Purpose":"training","Section":"s4"}' \
  --no-cli-pager
aws logs put-retention-policy --region "$REGION" --log-group-name "$LOG_GROUP_NAME" \
  --retention-in-days 1 --no-cli-pager
aws logs create-log-stream --region "$REGION" --log-group-name "$LOG_GROUP_NAME" \
  --log-stream-name "$LOG_STREAM_NAME" --no-cli-pager
put_response="$(
  aws_json logs put-log-events --region "$REGION" \
    --log-group-name "$LOG_GROUP_NAME" \
    --log-stream-name "$LOG_STREAM_NAME" \
    --log-events "file://$events_path"
)"
jq -e '(has("rejectedLogEventsInfo") | not) or (.rejectedLogEventsInfo == null)' <<<"$put_response" >/dev/null ||
  die "PutLogEvents rejected one or more events."
jq . <<<"$put_response" >"$evidence/put-log-events-response.json"

readback=""
for _ in {1..15}; do
  readback="$(
    aws_json logs get-log-events --region "$REGION" \
      --log-group-name "$LOG_GROUP_NAME" \
      --log-stream-name "$LOG_STREAM_NAME" \
      --start-from-head
  )"
  [[ "$(jq -r '.events | length' <<<"$readback")" == "6" ]] && break
  sleep 1
done
[[ "$(jq -r '.events | length' <<<"$readback")" == "6" ]] ||
  die "CloudWatch readback did not return exactly six events."
diff -u \
  <(sort "$rows_file") \
  <(jq -r '.events[].message' <<<"$readback" | sort) >/dev/null ||
  die "CloudWatch readback messages differ from the six Job log lines."
jq . <<<"$readback" >"$evidence/get-log-events-readback.json"

read -r start_epoch end_epoch < <(
  jq -r '[.[].timestamp] | "\(min / 1000 - 120 | floor) \(max / 1000 + 120 | floor)"' "$events_path"
)
((end_epoch > start_epoch && end_epoch - start_epoch <= 900)) ||
  die "Generated query range must be positive and no more than 15 minutes."
jq -n \
  --arg region "$REGION" \
  --arg log_group "$LOG_GROUP_NAME" \
  --argjson start_epoch "$start_epoch" \
  --argjson end_epoch "$end_epoch" \
  '{
    schema: "udemy4-s4-query-window-v1",
    region: $region,
    log_group: $log_group,
    start_epoch: $start_epoch,
    end_epoch: $end_epoch,
    max_range_seconds: 900
  }' >"$evidence/query-window.json"
printf 'PutLogEvents accepted six events; exact readback and bounded query window were saved locally.\n'
