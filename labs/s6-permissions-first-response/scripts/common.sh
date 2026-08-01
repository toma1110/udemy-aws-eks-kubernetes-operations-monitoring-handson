#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../common-eks/scripts/common.sh
source "$SCRIPT_DIR/../../common-eks/scripts/common.sh"

readonly S6_CONTRACT="udemy4-c010-s6-observation-v1"
S6_TEMP_CANDIDATE=""
S6_CREATED_PARENT="false"

assert_dns_label() {
  local value="$1" label="$2"
  [[ "$value" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ && ${#value} -le 63 ]] ||
    die "$label must be one exact Kubernetes DNS label."
}

assert_s6_inputs() {
  [[ "${AWS_REGION:-}" == "$REGION" && "${AWS_DEFAULT_REGION:-}" == "$REGION" ]] ||
    die "AWS_REGION and AWS_DEFAULT_REGION must both equal ap-northeast-1."
  assert_dns_label "${TARGET_NAMESPACE:-}" "TARGET_NAMESPACE"
  assert_dns_label "${TARGET_SERVICE_ACCOUNT:-}" "TARGET_SERVICE_ACCOUNT"
  [[ -n "${PRIVATE_EXECUTION_DIR:-}" && -n "${CURRENT_STS_IDENTITY_FILE:-}" ]] ||
    die "Source the governed common bind-current-identity.sh first."
  [[ "$(realpath -m "$CURRENT_STS_IDENTITY_FILE")" == "$(realpath -m "$PRIVATE_EXECUTION_DIR/current-sts-identity.json")" ]] ||
    die "The governed common identity binding shape is invalid."
  [[ "${S6_RUN_ID:-}" =~ ^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$ ]] ||
    die "S6_RUN_ID must be a run-specific UTC timestamp and random suffix."
  [[ "${S6_OBSERVATION_ROOT:-}" == "$PRIVATE_EXECUTION_DIR/s6-observations" ]] ||
    die "S6_OBSERVATION_ROOT must be the Section-only child of the governed private run."
  [[ "${S6_EVIDENCE_DIR:-}" == "$S6_OBSERVATION_ROOT/observations-$S6_RUN_ID" ]] ||
    die "S6_EVIDENCE_DIR must equal the exact run-specific observation path."
}

validate_s6_evidence_directory() {
  assert_s6_inputs
  [[ -f "$CURRENT_STS_IDENTITY_FILE" && ! -L "$CURRENT_STS_IDENTITY_FILE" ]] ||
    die "The governed common current-identity binding is missing."
  [[ -d "$S6_EVIDENCE_DIR" && ! -L "$S6_EVIDENCE_DIR" ]] ||
    die "S6_EVIDENCE_DIR must be a normal directory."
  [[ -d "$S6_EVIDENCE_DIR/raw" && ! -L "$S6_EVIDENCE_DIR/raw" ]] ||
    die "S6 raw evidence path must be a normal directory."
  [[ -d "$S6_EVIDENCE_DIR/status" && ! -L "$S6_EVIDENCE_DIR/status" ]] ||
    die "S6 status path must be a normal directory."
  [[ -f "$S6_EVIDENCE_DIR/run-contract.json" ]] ||
    die "S6 run contract is missing."
  jq -e \
    --arg schema "$S6_CONTRACT" \
    --arg run_id "$S6_RUN_ID" \
    --arg evidence_dir "$S6_EVIDENCE_DIR" \
    '.schema == $schema and .run_id == $run_id and .evidence_dir == $evidence_dir' \
    "$S6_EVIDENCE_DIR/run-contract.json" >/dev/null ||
    die "S6 run contract does not match the exact run."
  local package_root evidence_real
  package_root="$(realpath "$SCRIPT_DIR/..")"
  evidence_real="$(realpath "$S6_EVIDENCE_DIR")"
  [[ "$evidence_real" != "$package_root" && "$evidence_real" != "$package_root/"* ]] ||
    die "S6_EVIDENCE_DIR must be outside the learner package."
  chmod 700 "$S6_OBSERVATION_ROOT" "$evidence_real" "$evidence_real/raw" "$evidence_real/status"
  printf '%s\n' "$evidence_real"
}

assert_private_current_identity() {
  record_current_sts_identity
}

cleanup_s6_atomic_candidate() {
  if [[ -n "$S6_TEMP_CANDIDATE" &&
    "$(realpath -m "$S6_TEMP_CANDIDATE")" == "$(realpath -m "$S6_OBSERVATION_ROOT")/.observations-${S6_RUN_ID}.tmp."* ]]; then
    rm -f -- "$S6_TEMP_CANDIDATE/run-contract.json"
    rmdir -- "$S6_TEMP_CANDIDATE/raw" "$S6_TEMP_CANDIDATE/status" 2>/dev/null || true
    rmdir -- "$S6_TEMP_CANDIDATE" 2>/dev/null || true
  fi
  if [[ "$S6_CREATED_PARENT" == "true" &&
    "$(realpath -m "$S6_OBSERVATION_ROOT")" == "$(realpath -m "$PRIVATE_EXECUTION_DIR")/s6-observations" ]]; then
    rmdir -- "$S6_OBSERVATION_ROOT" 2>/dev/null || true
  fi
}

create_s6_run_directory() {
  assert_s6_inputs
  [[ ! -e "$S6_EVIDENCE_DIR" ]] ||
    die "Run-specific evidence target already exists; stale reuse is rejected."
  if [[ ! -e "$S6_OBSERVATION_ROOT" ]]; then
    mkdir -- "$S6_OBSERVATION_ROOT"
    S6_CREATED_PARENT="true"
  fi
  [[ -d "$S6_OBSERVATION_ROOT" && ! -L "$S6_OBSERVATION_ROOT" ]] ||
    { cleanup_s6_atomic_candidate; die "Section observation root is invalid."; }
  [[ -z "$(find "$S6_OBSERVATION_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]] ||
    { cleanup_s6_atomic_candidate; die "Section observation root is not empty."; }
  [[ "${S6_TEST_FAIL_POINT:-}" != "after-parent" ]] ||
    { cleanup_s6_atomic_candidate; die "Injected failure after parent creation."; }
  S6_TEMP_CANDIDATE="$(
    mktemp -d "$S6_OBSERVATION_ROOT/.observations-${S6_RUN_ID}.tmp.XXXXXXXX"
  )" || { cleanup_s6_atomic_candidate; return 1; }
  [[ "${S6_TEST_FAIL_POINT:-}" != "after-temp" ]] ||
    { cleanup_s6_atomic_candidate; die "Injected failure after temp creation."; }
  [[ -z "$(find "$S6_TEMP_CANDIDATE" -mindepth 1 -maxdepth 1 -print -quit)" ]] ||
    { cleanup_s6_atomic_candidate; die "Temporary run sibling was not empty."; }
  mkdir -- "$S6_TEMP_CANDIDATE/raw" "$S6_TEMP_CANDIDATE/status"
  jq -n --arg schema "$S6_CONTRACT" --arg run_id "$S6_RUN_ID" \
    --arg evidence_dir "$S6_EVIDENCE_DIR" \
    '{schema:$schema,run_id:$run_id,evidence_dir:$evidence_dir}' \
    >"$S6_TEMP_CANDIDATE/run-contract.json"
  [[ "${S6_TEST_FAIL_POINT:-}" != "after-contract" ]] ||
    { cleanup_s6_atomic_candidate; die "Injected failure after contract creation."; }
  chmod 700 "$S6_TEMP_CANDIDATE" "$S6_TEMP_CANDIDATE/raw" "$S6_TEMP_CANDIDATE/status"
  chmod 600 "$S6_TEMP_CANDIDATE/run-contract.json"
  mv -Tn -- "$S6_TEMP_CANDIDATE" "$S6_EVIDENCE_DIR"
  [[ ! -e "$S6_TEMP_CANDIDATE" && -d "$S6_EVIDENCE_DIR" ]] ||
    { cleanup_s6_atomic_candidate; die "Atomic no-clobber run installation collided."; }
  S6_TEMP_CANDIDATE=""
  S6_CREATED_PARENT="false"
}

assert_s6_common_target_redacted() {
  local evidence_dir="$1" private_log="$evidence_dir/status/common-target-private.log"
  if ! {
    assert_preflight true
    assert_private_current_identity
    get_expected_stack_binding
    assert_exact_kubernetes_context
  } >"$private_log" 2>&1; then
    chmod 600 "$private_log"
    printf 'ERROR: Common EKS target validation failed. Inspect the private status log.\n' >&2
    return 1
  fi
  chmod 600 "$private_log"
}

assert_s6_target() {
  assert_s6_inputs
  local evidence_dir
  evidence_dir="$(validate_s6_evidence_directory)"
  assert_s6_common_target_redacted "$evidence_dir"
  if ! kubectl get serviceaccount "$TARGET_SERVICE_ACCOUNT" \
    -n "$TARGET_NAMESPACE" -o name >"$evidence_dir/status/serviceaccount-private.log" 2>&1; then
    chmod 600 "$evidence_dir/status/serviceaccount-private.log"
    printf 'ERROR: Exact ServiceAccount validation failed. Inspect the private status log.\n' >&2
    return 1
  fi
  chmod 600 "$evidence_dir/status/serviceaccount-private.log"
}
