#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../common-eks/scripts/common.sh
source "$SCRIPT_DIR/../../common-eks/scripts/common.sh"

readonly S7_CLUSTER_NAME="udemy4-c010-common-20260724"
readonly S7_REGION="ap-northeast-1"
readonly S7_NAMESPACE="amazon-cloudwatch"
readonly S7_ADDON_NAME="amazon-cloudwatch-observability"
readonly S7_LOG_GROUP_PREFIX="/aws/containerinsights/$S7_CLUSTER_NAME/"

assert_s7_inputs() {
  [[ "${S7_RUN_ID:-}" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$ ]] ||
    die "S7_RUN_ID must be a new UTC timestamp plus eight lowercase hex characters."
  [[ "${S7_EVIDENCE_DIR:-}" == "${PRIVATE_EXECUTION_DIR:-}/s7-observations/observations-$S7_RUN_ID" ]] ||
    die "Section 7 evidence path is not the exact governed private path."
}

validate_s7_evidence_directory() {
  assert_s7_inputs
  [[ -d "$S7_EVIDENCE_DIR" && ! -L "$S7_EVIDENCE_DIR" ]] ||
    die "Section 7 evidence directory is missing or unsafe."
  local private_real evidence_real
  private_real="$(realpath "$PRIVATE_EXECUTION_DIR")"
  evidence_real="$(realpath "$S7_EVIDENCE_DIR")"
  [[ "$evidence_real" == "$private_real/s7-observations/observations-$S7_RUN_ID" ]] ||
    die "Section 7 evidence directory escaped the governed private root."
  printf '%s\n' "$evidence_real"
}

assert_s7_target() {
  # This is deliberately the first AWS call in every Section entry point.
  # It compares current default STS bytes with the retained sole private binding.
  record_current_sts_identity
  assert_preflight true
  get_expected_stack_binding
  [[ "$REGION" == "$S7_REGION" ]] ||
    die "Section 7 requires ap-northeast-1."
  [[ "$CLUSTER_NAME" == "$S7_CLUSTER_NAME" ]] ||
    die "Common cluster name does not match the Section 7 binding."
  assert_exact_kubernetes_context
}

write_status() {
  local path="$1" observed="$2" reason="$3"
  jq -n --argjson observed "$observed" --arg reason "$reason" \
    '{observed:$observed,reason:$reason}' >"$path"
  chmod 600 "$path"
}
