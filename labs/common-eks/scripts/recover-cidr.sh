#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_preflight true
get_expected_guard_binding

current_ip="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')" ||
  die "Could not resolve the current CloudShell public IPv4."
[[ "$current_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] ||
  die "Current CloudShell public address is not one IPv4 value."
new_cidr="$current_ip/32"
[[ "$new_cidr" != "0.0.0.0/0" ]] || die "World-open CIDR is forbidden."

stacks="$(aws_json cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME")"
[[ "$(jq -r '.Stacks | length' <<<"$stacks")" == "1" ]] ||
  die "Expected exactly one fixed common stack."
stack_id="$(jq -er '.Stacks[0].StackId' <<<"$stacks")"
stack_prefix="arn:aws:cloudformation:$REGION:$AWS_ACCOUNT_ID:stack/$STACK_NAME/"
stack_status="$(jq -er '.Stacks[0].StackStatus' <<<"$stacks")"
[[ "$stack_id" == "$stack_prefix"* &&
  "$stack_status" =~ ^(CREATE_COMPLETE|UPDATE_COMPLETE)$ ]] ||
  die "Common stack account, Region, name, or stable lifecycle binding mismatch."
assert_exact_tag_map "$(jq -c '.Stacks[0].Tags' <<<"$stacks")" "CloudFormation stack"

[[ "$(jq -r '[.Stacks[0].Outputs[] | select(.OutputKey == "ApiPublicAccessCidr")] | length' <<<"$stacks")" == "1" ]] ||
  die "Stack must expose exactly one ApiPublicAccessCidr output."
old_cidr="$(jq -er '.Stacks[0].Outputs[] | select(.OutputKey == "ApiPublicAccessCidr") | .OutputValue' <<<"$stacks")"
[[ "$old_cidr" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/32$ && "$old_cidr" != "0.0.0.0/0" ]] ||
  die "Existing stack CIDR is not one exact non-world IPv4 /32."

cluster="$(aws_json eks describe-cluster --region "$REGION" --name "$CLUSTER_NAME")"
expected_arn="arn:aws:eks:$REGION:$AWS_ACCOUNT_ID:cluster/$CLUSTER_NAME"
[[ "$(jq -r '.cluster.arn' <<<"$cluster")" == "$expected_arn" &&
  "$(jq -r '.cluster.status' <<<"$cluster")" == "ACTIVE" ]] ||
  die "Exact common EKS cluster binding is not ACTIVE."
runtime_cidrs="$(jq -c '.cluster.resourcesVpcConfig.publicAccessCidrs' <<<"$cluster")"
[[ "$(jq -r 'length' <<<"$runtime_cidrs")" == "1" &&
  "$(jq -r '.[0]' <<<"$runtime_cidrs")" == "$old_cidr" &&
  "$(jq -r '.[0]' <<<"$runtime_cidrs")" != "0.0.0.0/0" &&
  "$(jq -r '.cluster.resourcesVpcConfig.endpointPrivateAccess' <<<"$cluster")" == "true" &&
  "$(jq -r '.cluster.resourcesVpcConfig.endpointPublicAccess' <<<"$cluster")" == "true" ]] ||
  die "Existing runtime endpoint does not match the exact stack CIDR/private-public contract."
assert_exact_eks_cluster_tags "$(jq -c '.cluster.tags' <<<"$cluster")" "$stack_id"

mapfile -t parameter_keys < <(jq -r '.Stacks[0].Parameters[].ParameterKey' <<<"$stacks" | sort)
expected_parameter_keys="$(
  printf '%s\n' \
    ApiPublicAccessCidr AvailabilityZoneA AvailabilityZoneB ClusterName \
    CourseTag ManagedByTag PurposeTag TemplateContractTag WorkPackageTag | sort
)"
[[ "$(printf '%s\n' "${parameter_keys[@]}")" == "$expected_parameter_keys" ]] ||
  die "Common stack parameter set mismatch; recovery will not adopt or widen it."

export API_PUBLIC_ACCESS_CIDR="$new_cidr"
if [[ "$new_cidr" != "$old_cidr" ]]; then
  parameters=()
  for key in "${parameter_keys[@]}"; do
    if [[ "$key" == "ApiPublicAccessCidr" ]]; then
      parameters+=("ParameterKey=$key,ParameterValue=$new_cidr")
    else
      parameters+=("ParameterKey=$key,UsePreviousValue=true")
    fi
  done
  aws cloudformation update-stack \
    --region "$REGION" \
    --stack-name "$stack_id" \
    --use-previous-template \
    --capabilities CAPABILITY_IAM \
    --parameters "${parameters[@]}" \
    --tags \
    "Key=Course,Value=C010" \
    "Key=WorkPackage,Value=c010-common-eks" \
    "Key=ManagedBy,Value=udemy4" \
    "Key=Purpose,Value=training" \
    "Key=TemplateContract,Value=$TEMPLATE_CONTRACT" \
    --no-cli-pager >/dev/null
  aws cloudformation wait stack-update-complete \
    --region "$REGION" --stack-name "$stack_id" --no-cli-pager
fi

aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER_NAME" --no-cli-pager >/dev/null
get_expected_stack_binding
assert_exact_kubernetes_context
printf 'Recovered exact CloudShell endpoint binding: %s -> %s; private access remains enabled.\n' \
  "$old_cidr" "$new_cidr"
