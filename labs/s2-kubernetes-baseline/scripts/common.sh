#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../common-eks/scripts/common.sh
source "$SCRIPT_DIR/../../common-eks/scripts/common.sh"

readonly S2_NAMESPACE="udemy4-c010-s2-baseline"
readonly S2_LAB="s2-baseline"
S2_REPOSITORY_ROOT=""
S2_COMMON_FOUNDATION_COMMIT=""
S2_COMMON_FOUNDATION_TREE=""

assert_s2_public_binding() {
  local binding package_root common_path
  binding="$SCRIPT_DIR/../common-foundation.binding.json"
  [[ -f "$binding" && ! -L "$binding" ]] || die "Exact s2 common-foundation binding is missing."
  S2_COMMON_FOUNDATION_COMMIT="$(jq -er '.common_foundation_commit | select(test("^[0-9a-f]{40}$"))' "$binding")"
  S2_COMMON_FOUNDATION_TREE="$(jq -er '.common_foundation_tree_oid | select(test("^[0-9a-f]{40}$"))' "$binding")"
  common_path="$(jq -er '.common_foundation_path | select(. == "labs/common-eks")' "$binding")"
  package_root="$(realpath "$SCRIPT_DIR/..")"
  S2_REPOSITORY_ROOT="$(realpath "$package_root/../..")"
  [[ "$(git -C "$S2_REPOSITORY_ROOT" rev-parse "$S2_COMMON_FOUNDATION_COMMIT:$common_path")" == "$S2_COMMON_FOUNDATION_TREE" ]] ||
    die "Bound common base tree does not match."
  [[ "$(git -C "$S2_REPOSITORY_ROOT" rev-parse "HEAD:$common_path")" == "$S2_COMMON_FOUNDATION_TREE" ]] ||
    die "Current checkout changed the bound common foundation tree."
}

assert_s2_target() {
  [[ "${AWS_EXECUTION_ENV:-}" == *CloudShell* || "${CLOUDSHELL:-}" == "true" ]] ||
    die "AWS CloudShell environment required."
  [[ "${AWS_REGION:-${AWS_DEFAULT_REGION:-}}" == "ap-northeast-1" ]] ||
    die "AWS Region must be exact ap-northeast-1."
  command -v aws >/dev/null
  command -v kubectl >/dev/null
  command -v jq >/dev/null
  command -v git >/dev/null
  command -v sha256sum >/dev/null
  [[ "$HOME" = /* && -d "$HOME" ]] || die "CloudShell HOME is invalid."
  df -Pk "$HOME" >/dev/null || die "CloudShell HOME capacity could not be read."
  assert_s2_public_binding
  assert_preflight true
  get_expected_stack_binding
  assert_exact_kubernetes_context
}

assert_exact_s2_namespace() {
  local object="$1"
  jq -e --arg namespace "$S2_NAMESPACE" --arg lab "$S2_LAB" '
    .metadata.name == $namespace
    and .metadata.labels["app.kubernetes.io/part-of"] == "udemy4-c010"
    and .metadata.labels["app.kubernetes.io/managed-by"] == "udemy4"
    and .metadata.labels["udemy4.example/course"] == "C010"
    and .metadata.labels["udemy4.example/lab"] == $lab
    and .metadata.labels["udemy4.example/purpose"] == "training"
  ' <<<"$object" >/dev/null || die "Section 2 namespace identity or ownership labels do not match."
}

get_s2_evidence_directory() {
  [[ -n "${EVIDENCE_DIR:-}" && "$EVIDENCE_DIR" == "$HOME/"* ]] ||
    die "Set EVIDENCE_DIR to an absolute path below CloudShell HOME."
  mkdir -p -- "$EVIDENCE_DIR"
  [[ -d "$EVIDENCE_DIR" && ! -L "$EVIDENCE_DIR" ]] ||
    die "EVIDENCE_DIR must be a normal directory."
  local package_root evidence_real
  package_root="$(realpath "$SCRIPT_DIR/..")"
  evidence_real="$(realpath "$EVIDENCE_DIR")"
  [[ "$evidence_real" != "$package_root" && "$evidence_real" != "$package_root/"* ]] ||
    die "EVIDENCE_DIR must be outside the learner package."
  printf '%s\n' "$evidence_real"
}
