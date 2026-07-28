#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_external_binding
namespace_output=""
if namespace_output="$(kubectl get namespace "$NAMESPACE" -o name 2>&1)"; then
  die "The fixed namespace already exists; do not adopt or update it."
elif ! grep -q 'NotFound' <<<"$namespace_output"; then
  die "Namespace preflight failed: $namespace_output"
fi
groups="$(aws_json logs describe-log-groups --region "$REGION" --log-group-name-prefix "$LOG_GROUP_NAME")"
[[ "$(jq -r --arg exact "$LOG_GROUP_NAME" '[.logGroups[] | select(.logGroupName == $exact)] | length' <<<"$groups")" == "0" ]] ||
  die "The fixed log group already exists; do not adopt or update it."
printf 'Section 4 preflight passed for exact Region, cluster context, and absent fixed resources.\n'
