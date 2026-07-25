#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_s5_target
namespace_output=""
if namespace_output="$(kubectl get namespace "$NAMESPACE" -o name 2>&1)"; then
  die "The fixed Section 5 namespace already exists."
elif ! grep -q 'NotFound' <<<"$namespace_output"; then
  die "Namespace preflight failed: $namespace_output"
fi

kubectl apply -f "$SCRIPT_DIR/../manifests/00-namespace.yaml"
assert_exact_s5_namespace "$(kubectl get namespace "$NAMESPACE" -o json)"
kubectl apply -f "$SCRIPT_DIR/../manifests/10-pending-capacity.yaml"
kubectl apply -f "$SCRIPT_DIR/../manifests/20-crashloop-app.yaml"
kubectl apply -f "$SCRIPT_DIR/../manifests/30-crashloop-memory.yaml"
kubectl get pods -n "$NAMESPACE" -o wide
