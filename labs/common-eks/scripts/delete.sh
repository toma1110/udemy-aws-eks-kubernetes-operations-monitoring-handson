#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_preflight false
if ! aws_exact_not_found 'ValidationError.*does not exist' \
  cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME"; then
  stacks="$(aws_json cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME")"
  status="$(jq -er '.Stacks[0].StackStatus' <<<"$stacks")"
  if [[ "$status" == "ROLLBACK_COMPLETE" ]]; then
    get_failed_stack_binding "$stacks"
  else
    assert_preflight true
    get_expected_stack_binding
    assert_section_s4_residuals_absent
  fi
  aws cloudformation delete-stack --region "$REGION" --stack-name "$STACK_ID" --no-cli-pager
  aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$STACK_ID" --no-cli-pager
fi
# Keep either the normal Section gate or the exact ROLLBACK_COMPLETE/cluster-
# absent gate in this process through residual checks and guard removal.
# shellcheck source=verify-cleanup.sh
source "$SCRIPT_DIR/verify-cleanup.sh"
