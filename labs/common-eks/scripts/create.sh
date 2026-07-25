#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

"$SCRIPT_DIR/preflight.sh"

schedule_expression="at(${CLEANUP_DEADLINE_UTC%Z})"
aws cloudformation create-stack \
  --region "$REGION" \
  --stack-name "$GUARD_STACK_NAME" \
  --template-body "file://$SCRIPT_DIR/../cleanup-guard.yaml" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
  "ParameterKey=AccountId,ParameterValue=$AWS_ACCOUNT_ID" \
  "ParameterKey=CleanupScheduleExpression,ParameterValue=$schedule_expression" \
  --tags \
  "Key=Course,Value=C010" \
  "Key=WorkPackage,Value=c010-common-eks" \
  "Key=ManagedBy,Value=udemy4" \
  "Key=Purpose,Value=training-cleanup-guard" \
  "Key=TemplateContract,Value=$GUARD_TEMPLATE_CONTRACT" \
  --no-cli-pager >/dev/null
aws cloudformation wait stack-create-complete \
  --region "$REGION" --stack-name "$GUARD_STACK_NAME" --no-cli-pager
get_expected_guard_binding

# Atomic create refuses an existing fixed stack. Only recover-cidr.sh may update it.
common_create_result=""
if ! common_create_result="$(
  aws cloudformation create-stack \
    --region "$REGION" \
    --stack-name "$STACK_NAME" \
    --template-body "file://$SCRIPT_DIR/../template.yaml" \
    --capabilities CAPABILITY_IAM \
    --parameters \
    "ParameterKey=ApiPublicAccessCidr,ParameterValue=$API_PUBLIC_ACCESS_CIDR" \
    "ParameterKey=AvailabilityZoneA,ParameterValue=$AVAILABILITY_ZONE_A" \
    "ParameterKey=AvailabilityZoneB,ParameterValue=$AVAILABILITY_ZONE_B" \
    --tags \
    "Key=Course,Value=C010" \
    "Key=WorkPackage,Value=c010-common-eks" \
    "Key=ManagedBy,Value=udemy4" \
    "Key=Purpose,Value=training" \
    "Key=TemplateContract,Value=$TEMPLATE_CONTRACT" \
    --no-cli-pager 2>&1
)"; then
  if grep -q "AlreadyExistsException" <<<"$common_create_result"; then
    die "The fixed common stack already exists; refusing to update or adopt it. Use status/delete, or the owned recover-cidr path only for CIDR drift."
  else
    die "Atomic common stack creation failed: $common_create_result"
  fi
fi
aws cloudformation wait stack-create-complete \
  --region "$REGION" --stack-name "$STACK_NAME" --no-cli-pager

get_expected_stack_binding
aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER_NAME" --no-cli-pager >/dev/null
assert_exact_kubernetes_context
apply_exact_cluster_cleanup_rbac
kubectl wait --for=condition=Ready nodes --all --timeout=10m
printf 'Create and ownership binding completed. Guard %s remains active until verified cleanup; deadline %s.\n' \
  "$GUARD_STACK_ID" "$CLEANUP_DEADLINE_UTC"
