#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_preflight true
get_expected_stack_binding
assert_exact_kubernetes_context
aws_json cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_ID"
aws_json eks describe-cluster --region "$REGION" --name "$CLUSTER_NAME"
aws_json eks list-nodegroups --region "$REGION" --cluster-name "$CLUSTER_NAME"
kubectl get nodes -o wide
