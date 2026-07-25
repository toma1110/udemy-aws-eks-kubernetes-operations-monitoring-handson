#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  # shellcheck source=common.sh
  source "$SCRIPT_DIR/common.sh"
  die "verify-cleanup.sh must only be sourced by delete.sh after an exact normal or failed-create cleanup gate passes."
fi
require_common_cleanup_gate
failures=()

# The normal path carries its Namespace/Job gate. The failed-create path proves
# ROLLBACK_COMPLETE plus cluster absence without kubectl. CloudWatch remains
# independently queryable in both paths.
[[ "$(aws_json logs describe-log-groups --region "$REGION" \
  --log-group-name-prefix "/udemy4/c010/s4/20260725" |
  jq '[.logGroups[] | select(.logGroupName == "/udemy4/c010/s4/20260725")] | length')" == "0" ]] ||
  failures+=("Section s4 log group remains")

if ! aws_exact_not_found 'ValidationError.*does not exist' \
  cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME"; then
  failures+=("CloudFormation stack still exists")
fi
if ! aws_exact_not_found 'ResourceNotFoundException' \
  eks describe-cluster --region "$REGION" --name "$CLUSTER_NAME"; then
  failures+=("EKS cluster still exists")
fi

tag_filters=(
  "Name=tag:Course,Values=C010"
  "Name=tag:WorkPackage,Values=c010-common-eks"
  "Name=tag:ManagedBy,Values=udemy4"
  "Name=tag:Purpose,Values=training"
  "Name=tag:TemplateContract,Values=$TEMPLATE_CONTRACT"
)
[[ "$(aws_json ec2 describe-instances --region "$REGION" --filters \
  "${tag_filters[@]}" "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down" |
  jq '[.Reservations[].Instances[]] | length')" == "0" ]] ||
  failures+=("Tagged EC2 instances remain")
[[ "$(aws_json ec2 describe-volumes --region "$REGION" --filters "${tag_filters[@]}" |
  jq '.Volumes | length')" == "0" ]] ||
  failures+=("Tagged EBS volumes remain")
[[ "$(aws_json ec2 describe-network-interfaces --region "$REGION" --filters "${tag_filters[@]}" |
  jq '.NetworkInterfaces | length')" == "0" ]] ||
  failures+=("Tagged ENIs remain")
[[ "$(aws_json ec2 describe-network-interfaces --region "$REGION" \
  --filters "Name=description,Values=Amazon EKS $CLUSTER_NAME" |
  jq '.NetworkInterfaces | length')" == "0" ]] ||
  failures+=("EKS-described ENIs remain")
[[ "$(aws_json logs describe-log-groups --region "$REGION" \
  --log-group-name-prefix "/aws/eks/$CLUSTER_NAME/" |
  jq '.logGroups | length')" == "0" ]] ||
  failures+=("Cluster-prefixed CloudWatch log groups remain")

if ((${#failures[@]})); then
  die "Cleanup verification failed closed: $(IFS='; '; printf '%s' "${failures[*]}")"
fi

# The guard is removed last, only after every chargeable-residual query passes.
get_expected_guard_binding
schedule="$(aws_json scheduler get-schedule --region "$REGION" --name "$GUARD_SCHEDULE_NAME")"
[[ "$(jq -r '.Name' <<<"$schedule")" == "$GUARD_SCHEDULE_NAME" &&
  "$(jq -r '.State' <<<"$schedule")" == "ENABLED" &&
  "$(jq -r '.Target.RoleArn' <<<"$schedule")" == "arn:aws:iam::$AWS_ACCOUNT_ID:role/$GUARD_ROLE_NAME" &&
  "$(jq -r '.Target.Arn' <<<"$schedule")" == "$GUARD_STATE_MACHINE_ARN" &&
  "$(jq -r '.Target.Input' <<<"$schedule")" == '{"contract":"udemy4-c010-deadline-cleanup-v2"}' ]] ||
  die "Cleanup guard schedule binding mismatch."
aws cloudformation delete-stack --region "$REGION" --stack-name "$GUARD_STACK_ID" --no-cli-pager
aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$GUARD_STACK_ID" --no-cli-pager

aws_exact_not_found 'ValidationError.*does not exist' \
  cloudformation describe-stacks --region "$REGION" --stack-name "$GUARD_STACK_NAME" ||
  die "Cleanup guard stack still exists."
aws_exact_not_found 'ResourceNotFoundException' \
  scheduler get-schedule --region "$REGION" --name "$GUARD_SCHEDULE_NAME" ||
  die "Cleanup guard schedule still exists."
aws_exact_not_found 'NoSuchEntity' \
  iam get-role --region "$REGION" --role-name "$GUARD_ROLE_NAME" ||
  die "Cleanup guard role still exists."
aws_exact_not_found 'ResourceNotFoundException' \
  lambda get-function --region "$REGION" --function-name "$GUARD_CLEANUP_HANDLER_NAME" ||
  die "Cleanup handler function still exists."
aws_exact_not_found 'StateMachineDoesNotExist' \
  stepfunctions describe-state-machine --region "$REGION" --state-machine-arn "$GUARD_STATE_MACHINE_ARN" ||
  die "Cleanup state machine still exists."
aws_exact_not_found 'NoSuchEntity' \
  iam get-role --region "$REGION" --role-name "$GUARD_CLEANUP_HANDLER_ROLE_NAME" ||
  die "Cleanup handler role still exists."

printf 'Cleanup verified: chargeable residuals are absent and the exact guard was removed last.\n'
