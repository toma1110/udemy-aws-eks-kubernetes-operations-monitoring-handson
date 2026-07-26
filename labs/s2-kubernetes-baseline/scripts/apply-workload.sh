#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

assert_s2_target
MANIFEST_DIR="$SCRIPT_DIR/../manifests"

namespace_output=""
if ! namespace_output="$(kubectl get namespace "$S2_NAMESPACE" -o json --ignore-not-found)"; then
  die "Namespace preflight failed. No workload mutation was attempted."
fi
if [[ -n "$namespace_output" ]]; then
  die "Section namespace already exists. Refusing to update or adopt it."
fi

kubectl create -f "$MANIFEST_DIR/00-namespace.yaml"
assert_exact_s2_namespace "$(kubectl get namespace "$S2_NAMESPACE" -o json)"
kubectl create -f "$MANIFEST_DIR/10-deployment.yaml"
kubectl create -f "$MANIFEST_DIR/20-service.yaml"
kubectl rollout status deployment/baseline-web -n "$S2_NAMESPACE" --timeout=5m

deployment="$(kubectl get deployment baseline-web -n "$S2_NAMESPACE" -o json)"
service="$(kubectl get service baseline-web -n "$S2_NAMESPACE" -o json)"
jq -e --arg lab "$S2_LAB" '
  .metadata.labels["udemy4.example/lab"] == $lab
  and .spec.replicas == 1
  and .status.readyReplicas == 1
' <<<"$deployment" >/dev/null || die "Baseline Deployment is not exactly ready."
jq -e --arg lab "$S2_LAB" '
  .spec.type == "ClusterIP"
  and .spec.selector["app.kubernetes.io/name"] == "baseline-web"
  and .spec.selector["udemy4.example/lab"] == $lab
' <<<"$service" >/dev/null || die "Baseline Service selector does not match."

kubectl get nodes -o wide
kubectl get deployment,service,pods -n "$S2_NAMESPACE" -o wide
