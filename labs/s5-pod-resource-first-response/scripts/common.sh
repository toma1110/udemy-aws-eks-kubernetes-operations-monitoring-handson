#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../common-eks/scripts/common.sh
source "$SCRIPT_DIR/../../common-eks/scripts/common.sh"

readonly NAMESPACE="udemy4-c010-s5-20260724"

assert_s5_target() {
  assert_preflight
  get_expected_stack_binding
  assert_exact_kubernetes_context
}

assert_exact_s5_namespace() {
  local object="$1"
  jq -e --arg namespace "$NAMESPACE" '
    .metadata.name == $namespace
    and .metadata.labels == {
      "app.kubernetes.io/part-of": "udemy4-c010",
      "app.kubernetes.io/managed-by": "udemy4",
      "kubernetes.io/metadata.name": $namespace,
      "udemy4.example/course": "C010",
      "udemy4.example/purpose": "training",
      "udemy4.example/work-package": "issue-31"
    }
  ' <<<"$object" >/dev/null ||
    die "Section 5 namespace identity or ownership labels do not match."
}

get_s5_evidence_directory() {
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
