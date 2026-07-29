#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

[[ -f "${CURRENT_STS_IDENTITY_FILE:-}" ]] ||
  die "The retained current-run STS identity file is required for post-guard verification."
record_current_sts_identity

aws_zero() {
  local label="$1"
  shift
  local count
  count="$(aws "$@" --no-cli-pager --output text)"
  [[ "$count" == "0" ]] || die "$label remains after guard deletion."
}

aws_exact_not_found 'ValidationError.*does not exist' \
  cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME" ||
  die "Common stack remains after guard deletion."
aws_exact_not_found 'ResourceNotFoundException' \
  eks describe-cluster --region "$REGION" --name "$CLUSTER_NAME" ||
  die "EKS cluster remains after guard deletion."

tag_filters=(
  "Name=tag:Course,Values=C010"
  "Name=tag:WorkPackage,Values=c010-common-eks"
  "Name=tag:ManagedBy,Values=udemy4"
  "Name=tag:Purpose,Values=training"
  "Name=tag:TemplateContract,Values=$TEMPLATE_CONTRACT"
)
aws_zero "Tagged EC2 instance" ec2 describe-instances --region "$REGION" \
  --filters "${tag_filters[@]}" \
  "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down" \
  --query 'length(Reservations[].Instances[])'
aws_zero "Tagged EBS volume" ec2 describe-volumes --region "$REGION" \
  --filters "${tag_filters[@]}" --query 'length(Volumes)'
aws_zero "Tagged ENI" ec2 describe-network-interfaces --region "$REGION" \
  --filters "${tag_filters[@]}" --query 'length(NetworkInterfaces)'
aws_zero "EKS-described ENI" ec2 describe-network-interfaces --region "$REGION" \
  --filters "Name=description,Values=Amazon EKS $CLUSTER_NAME" \
  --query 'length(NetworkInterfaces)'
aws_zero "Section s4 log group" logs describe-log-groups --region "$REGION" \
  --log-group-name-prefix "/udemy4/c010/s4/20260725" \
  --query 'length(logGroups[?logGroupName==`/udemy4/c010/s4/20260725`])'
aws_zero "Cluster-prefixed log group" logs describe-log-groups --region "$REGION" \
  --log-group-name-prefix "/aws/eks/$CLUSTER_NAME/" --query 'length(logGroups)'

aws_exact_not_found 'ValidationError.*does not exist' \
  cloudformation describe-stacks --region "$REGION" --stack-name "$GUARD_STACK_NAME" ||
  die "Cleanup guard stack remains."
aws_exact_not_found 'ResourceNotFoundException' \
  scheduler get-schedule --region "$REGION" --name "$GUARD_SCHEDULE_NAME" ||
  die "Cleanup guard schedule remains."
aws_exact_not_found 'NoSuchEntity' \
  iam get-role --region "$REGION" --role-name "$GUARD_ROLE_NAME" ||
  die "Cleanup guard role remains."
aws_exact_not_found 'ResourceNotFoundException' \
  lambda get-function --region "$REGION" --function-name "$GUARD_CLEANUP_HANDLER_NAME" ||
  die "Cleanup handler function remains."
aws_exact_not_found 'NoSuchEntity' \
  iam get-role --region "$REGION" --role-name "$GUARD_CLEANUP_HANDLER_ROLE_NAME" ||
  die "Cleanup handler role remains."
aws_zero "Cleanup state machine" stepfunctions list-state-machines --region "$REGION" \
  --query "length(stateMachines[?name==\`$GUARD_STATE_MACHINE_NAME\`])"

[[ -n "${PRIVATE_EXECUTION_DIR:-}" && "$PRIVATE_EXECUTION_DIR" == /* ]] ||
  die "PRIVATE_EXECUTION_DIR must remain bound to the current run."
[[ "$(realpath "$PRIVATE_EXECUTION_DIR")" == "$(realpath "$(dirname -- "$CURRENT_STS_IDENTITY_FILE")")" ]] ||
  die "The current identity file is not in the sole run-private directory."
[[ "$(basename -- "$CURRENT_STS_IDENTITY_FILE")" == "current-sts-identity.json" ]] ||
  die "The current identity filename changed."
mapfile -d '' private_entries < <(
  find "$PRIVATE_EXECUTION_DIR" -mindepth 1 -maxdepth 1 -print0
)
((${#private_entries[@]} == 1)) ||
  die "The run-private directory contains an unexpected or orphan artifact."
[[ "$(realpath "${private_entries[0]}")" == "$(realpath "$CURRENT_STS_IDENTITY_FILE")" ]] ||
  die "The sole run-private artifact is not the current identity file."

rm -f -- "$CURRENT_STS_IDENTITY_FILE"
rmdir -- "$PRIVATE_EXECUTION_DIR"
printf 'Post-guard verification passed: current identity revalidated, all fixed residuals are zero, and the sole private identity artifact was removed.\n'
