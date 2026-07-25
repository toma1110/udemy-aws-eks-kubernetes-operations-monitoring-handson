#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_external_binding
namespace_output=""
if namespace_output="$(kubectl get namespace "$NAMESPACE" -o json 2>&1)"; then
  [[ "$(jq -r '.metadata.name' <<<"$namespace_output")" == "$NAMESPACE" ]] ||
    die "Namespace identity mismatch."
  assert_exact_namespace_labels "$namespace_output" "Namespace"
  job_output=""
  if job_output="$(kubectl get job "$JOB_NAME" -n "$NAMESPACE" -o json 2>&1)"; then
    [[ "$(jq -r '.metadata.name' <<<"$job_output")" == "$JOB_NAME" &&
      "$(jq -r '.metadata.namespace' <<<"$job_output")" == "$NAMESPACE" ]] ||
      die "Job identity mismatch."
    assert_exact_namespace_labels "$job_output" "Job"
  elif ! grep -q 'NotFound' <<<"$job_output"; then
    die "Job ownership lookup failed: $job_output"
  fi
  kubectl delete namespace "$NAMESPACE" --wait=true --timeout=5m
elif ! grep -q 'NotFound' <<<"$namespace_output"; then
  die "Namespace lookup failed: $namespace_output"
fi

groups="$(aws_json logs describe-log-groups --region "$REGION" --log-group-name-prefix "$LOG_GROUP_NAME")"
exact_count="$(jq -r --arg exact "$LOG_GROUP_NAME" '[.logGroups[] | select(.logGroupName == $exact)] | length' <<<"$groups")"
((exact_count <= 1)) || die "Exact log group lookup was not unique."
if [[ "$exact_count" == "1" ]]; then
  tags="$(aws_json logs list-tags-log-group --region "$REGION" --log-group-name "$LOG_GROUP_NAME")"
  assert_exact_log_group_tags "$(jq -c '.tags' <<<"$tags")"
  aws logs delete-log-group --region "$REGION" --log-group-name "$LOG_GROUP_NAME" --no-cli-pager
fi
"$SCRIPT_DIR/verify-cleanup.sh"
