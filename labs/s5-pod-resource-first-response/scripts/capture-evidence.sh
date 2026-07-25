#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_s5_target
assert_exact_s5_namespace "$(kubectl get namespace "$NAMESPACE" -o json)"
evidence_dir="$(get_s5_evidence_directory)"

kubectl get pods -n "$NAMESPACE" -o yaml >"$evidence_dir/pods.yaml"
kubectl get events -n "$NAMESPACE" --sort-by=.lastTimestamp >"$evidence_dir/events.txt"
kubectl describe pod udemy4-c010-s5-20260724-pending-capacity -n "$NAMESPACE" >"$evidence_dir/pending-capacity-describe.txt"
kubectl describe pod udemy4-c010-s5-20260724-crashloop-app -n "$NAMESPACE" >"$evidence_dir/crashloop-app-describe.txt"
kubectl logs udemy4-c010-s5-20260724-crashloop-app -n "$NAMESPACE" --tail=100 >"$evidence_dir/crashloop-app-current.log"
kubectl logs udemy4-c010-s5-20260724-crashloop-app -n "$NAMESPACE" --previous --tail=100 >"$evidence_dir/crashloop-app-previous.log"
kubectl describe pod udemy4-c010-s5-20260724-crashloop-memory -n "$NAMESPACE" >"$evidence_dir/crashloop-memory-describe.txt"
kubectl logs udemy4-c010-s5-20260724-crashloop-memory -n "$NAMESPACE" --previous --tail=100 >"$evidence_dir/crashloop-memory-previous.log"
kubectl get nodes -o custom-columns=NAME:.metadata.name,ALLOCATABLE_MEMORY:.status.allocatable.memory >"$evidence_dir/node-memory.txt"

printf 'Evidence captured at %s. Review before sharing; do not add it to Git.\n' "$evidence_dir"
