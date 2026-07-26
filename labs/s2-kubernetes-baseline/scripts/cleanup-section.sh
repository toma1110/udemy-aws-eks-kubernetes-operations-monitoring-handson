#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

assert_s2_target
namespace_output=""
if ! namespace_output="$(kubectl get namespace "$S2_NAMESPACE" -o json --ignore-not-found)"; then
  die "Namespace lookup failed. Absence was not proven."
fi
if [[ -n "$namespace_output" ]]; then
  assert_exact_s2_namespace "$namespace_output"
  kubectl delete namespace "$S2_NAMESPACE" --wait=true --timeout=5m
fi

verification=""
if ! verification="$(kubectl get namespace "$S2_NAMESPACE" -o json --ignore-not-found)"; then
  die "Namespace verification command failed. Absence was not proven."
fi
[[ -z "$verification" ]] ||
  die "Section namespace still exists. Do not continue to common cleanup."
printf 'Section 2 namespace cleanup verified. Continue with common cleanup.\n'
