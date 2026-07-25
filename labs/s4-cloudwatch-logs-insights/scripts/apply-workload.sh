#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_external_binding
namespace_output=""
if namespace_output="$(kubectl get namespace "$NAMESPACE" -o name 2>&1)"; then
  die "The fixed namespace already exists."
elif ! grep -q 'NotFound' <<<"$namespace_output"; then
  die "Namespace check failed: $namespace_output"
fi
kubectl apply -f "$SCRIPT_DIR/../manifests/00-namespace.yaml"
apply_exact_cleanup_rbac
kubectl apply -f "$SCRIPT_DIR/../manifests/10-log-workload.yaml"
kubectl wait --for=condition=complete "job/$JOB_NAME" -n "$NAMESPACE" --timeout=5m
pod_name="$(get_exact_job_pod_name)"
rows_file="$(mktemp)"
trap 'rm -f -- "$rows_file"' EXIT
kubectl logs "$pod_name" -n "$NAMESPACE" >"$rows_file"
assert_workload_log_rows "$rows_file" "$pod_name"
printf 'Real EKS Job completed; exact owned Pod %s emitted six namespace/Pod-validated JSON rows.\n' "$pod_name"
