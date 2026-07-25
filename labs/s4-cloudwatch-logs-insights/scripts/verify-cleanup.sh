#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_external_binding
failures=()
namespace_output=""
if namespace_output="$(kubectl get namespace "$NAMESPACE" -o name 2>&1)"; then
  failures+=("Section namespace remains")
elif ! grep -q 'NotFound' <<<"$namespace_output"; then
  die "Namespace residual check failed: $namespace_output"
fi
groups="$(aws_json logs describe-log-groups --region "$REGION" --log-group-name-prefix "$LOG_GROUP_NAME")"
[[ "$(jq -r --arg exact "$LOG_GROUP_NAME" '[.logGroups[] | select(.logGroupName == $exact)] | length' <<<"$groups")" == "0" ]] ||
  failures+=("Section log group remains")
if ((${#failures[@]})); then
  die "Cleanup verification failed closed: $(IFS='; '; printf '%s' "${failures[*]}")"
fi
printf 'Section cleanup verified: namespace, Job, and fixed CloudWatch log group are absent.\n'
