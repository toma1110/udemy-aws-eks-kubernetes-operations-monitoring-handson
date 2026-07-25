#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_preflight true
assert_exact_cidr
assert_deadline_contract
assert_selected_azs_and_capacity
assert_eks_quota_headroom

aws_json cloudformation validate-template --region "$REGION" \
  --template-body "file://$SCRIPT_DIR/../template.yaml" >/dev/null
aws_json cloudformation validate-template --region "$REGION" \
  --template-body "file://$SCRIPT_DIR/../cleanup-guard.yaml" >/dev/null

if ! aws_exact_not_found 'ValidationError.*does not exist' \
  cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME"; then
  die "The fixed stack already exists. Creation is rejected; use status/delete after ownership binding."
fi
if ! aws_exact_not_found 'ValidationError.*does not exist' \
  cloudformation describe-stacks --region "$REGION" --stack-name "$GUARD_STACK_NAME"; then
  die "The fixed cleanup guard stack already exists. Creation is rejected; use delete after exact binding."
fi

printf 'Preflight passed for absent fixed stacks, exact account, %s, selected AZs, quota, and deadline %s.\n' \
  "$REGION" "$CLEANUP_DEADLINE_UTC"
