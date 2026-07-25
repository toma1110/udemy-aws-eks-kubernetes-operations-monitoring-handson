#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_s5_target
namespace_output=""
if namespace_output="$(kubectl get namespace "$NAMESPACE" -o json 2>&1)"; then
  assert_exact_s5_namespace "$namespace_output"
  kubectl delete namespace "$NAMESPACE" --wait=true --timeout=5m
elif ! grep -q 'NotFound' <<<"$namespace_output"; then
  die "Namespace lookup failed: $namespace_output"
fi

verification=""
if verification="$(kubectl get namespace "$NAMESPACE" -o name 2>&1)"; then
  die "Section namespace still exists. Do not continue to common cleanup."
elif ! grep -q 'NotFound' <<<"$verification"; then
  die "Namespace verification failed and was not an exact NotFound result: $verification"
fi
printf 'Section namespace cleanup verified.\n'
