#!/usr/bin/env bash
set -euo pipefail

readonly REGION="ap-northeast-1"
readonly STACK_NAME="udemy4-c010-common-20260724"
readonly CLUSTER_NAME="udemy4-c010-common-20260724"
readonly TEMPLATE_CONTRACT="udemy4-c010-common-eks-v2-20260724"
readonly GUARD_STACK_NAME="udemy4-c010-common-20260724-guard"
readonly GUARD_SCHEDULE_NAME="udemy4-c010-common-20260724-guard-schedule"
readonly GUARD_ROLE_NAME="udemy4-c010-common-20260724-guard-role"
readonly GUARD_CLEANUP_HANDLER_NAME="udemy4-c010-common-20260724-cleanup-handler"
readonly GUARD_CLEANUP_HANDLER_ROLE_NAME="udemy4-c010-common-20260724-cleanup-handler-role"
readonly GUARD_STATE_MACHINE_NAME="udemy4-c010-common-20260724-cleanup"
readonly GUARD_TEMPLATE_CONTRACT="udemy4-c010-cleanup-guard-v2-20260725"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  return 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is required in AWS CloudShell."
}

assert_semantic_version_at_least() {
  local actual="$1" minimum="$2" label="$3"
  [[ "$actual" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] ||
    die "$label version is not semantic: $actual"
  local actual_major="${BASH_REMATCH[1]}" actual_minor="${BASH_REMATCH[2]}" actual_patch="${BASH_REMATCH[3]}"
  [[ "$minimum" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] ||
    die "Internal minimum version is invalid: $minimum"
  local minimum_major="${BASH_REMATCH[1]}" minimum_minor="${BASH_REMATCH[2]}" minimum_patch="${BASH_REMATCH[3]}"
  ((actual_major > minimum_major ||
    (actual_major == minimum_major && actual_minor > minimum_minor) ||
    (actual_major == minimum_major && actual_minor == minimum_minor && actual_patch >= minimum_patch))) ||
    die "$label $actual is below required minimum $minimum."
}

assert_aws_cli_minimum_text() {
  local text="$1"
  [[ "$text" =~ aws-cli/([0-9]+\.[0-9]+\.[0-9]+) ]] ||
    die "AWS CLI version output is invalid: $text"
  assert_semantic_version_at_least "${BASH_REMATCH[1]}" "2.12.3" "AWS CLI"
}

assert_kubectl_minor_compatible() {
  local client="$1" cluster="$2"
  [[ "$client" =~ ^v?([0-9]+)\.([0-9]+)(\.[0-9]+)? ]] ||
    die "kubectl client version is invalid: $client"
  local client_major="${BASH_REMATCH[1]}" client_minor="${BASH_REMATCH[2]}"
  [[ "$cluster" =~ ^v?([0-9]+)\.([0-9]+)(\.[0-9]+)? ]] ||
    die "EKS cluster version is invalid: $cluster"
  local cluster_major="${BASH_REMATCH[1]}" cluster_minor="${BASH_REMATCH[2]}"
  ((client_major == cluster_major)) ||
    die "kubectl and EKS cluster major versions differ."
  local difference=$((client_minor - cluster_minor))
  ((difference >= -1 && difference <= 1)) ||
    die "kubectl client minor must be within one minor of the EKS cluster version."
}

assert_runtime_endpoint_values() {
  local private_access="$1" public_access="$2" expected_cidr="$3"
  shift 3
  [[ "$private_access" == "true" && "$public_access" == "true" ]] ||
    die "EKS private and restricted public endpoints must both be enabled."
  (($# == 1)) || die "EKS publicAccessCidrs must contain exactly one value."
  [[ "$1" == "$expected_cidr" && "$1" != "0.0.0.0/0" ]] ||
    die "EKS publicAccessCidrs must equal the exact current CloudShell CIDR and reject 0.0.0.0/0."
}

assert_current_cloudshell_cidr() {
  assert_exact_cidr
  [[ "$API_PUBLIC_ACCESS_CIDR" == */32 ]] ||
    die "CloudShell public access must use one exact IPv4 /32."
  local current_ip
  current_ip="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')" ||
    die "Could not resolve the current CloudShell public IPv4."
  [[ "$current_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ &&
    "$API_PUBLIC_ACCESS_CIDR" == "$current_ip/32" ]] ||
    die "API_PUBLIC_ACCESS_CIDR does not equal the current CloudShell public IPv4 /32."
}

aws_json() {
  aws "$@" --no-cli-pager --output json
}

aws_exact_not_found() {
  local pattern="$1"
  shift
  local output
  if output="$(aws "$@" --no-cli-pager --output json 2>&1)"; then
    return 1
  fi
  if grep -Eq "$pattern" <<<"$output" &&
    ! grep -Eqi 'AccessDenied|Unauthorized|ExpiredToken|InvalidClientToken|Throttl|timed out|Could not connect|network' <<<"$output"; then
    return 0
  fi
  die "AWS CLI failed and was not an exact not-found result: $output"
}

assert_required_account_input() {
  [[ "${AWS_ACCOUNT_ID:-}" =~ ^[0-9]{12}$ ]] ||
    die "Set AWS_ACCOUNT_ID to the exact approved 12-digit target account."
}

assert_aws_identity() {
  assert_required_account_input
  local identity actual_account region_count
  identity="$(aws_json sts get-caller-identity --region "$REGION")"
  actual_account="$(jq -er '.Account | select(test("^[0-9]{12}$"))' <<<"$identity")" ||
    die "STS did not return one exact account."
  [[ "$actual_account" == "$AWS_ACCOUNT_ID" ]] ||
    die "STS account does not equal AWS_ACCOUNT_ID."
  region_count="$(
    aws_json ec2 describe-regions --region "$REGION" --region-names "$REGION" |
      jq -er --arg region "$REGION" '[.Regions[] | select(.RegionName == $region)] | length'
  )"
  [[ "$region_count" == "1" ]] ||
    die "The fixed Region ap-northeast-1 could not be verified."
}

assert_preflight() {
  local require_kubectl="${1:-true}"
  require_command aws
  require_command jq
  require_command python3
  require_command curl
  local aws_version
  aws_version="$(aws --version 2>&1)"
  assert_aws_cli_minimum_text "$aws_version"
  if [[ "$require_kubectl" == "true" ]]; then
    require_command kubectl
    kubectl version --client --output=json |
      jq -e '.clientVersion.gitVersion | strings | length > 0' >/dev/null ||
      die "kubectl client version check failed."
  fi
  assert_aws_identity
}

assert_exact_cidr() {
  local cidr="${API_PUBLIC_ACCESS_CIDR:-}"
  [[ -n "$cidr" && "$cidr" != "0.0.0.0/0" &&
    "$cidr" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$ ]] ||
    die "Set API_PUBLIC_ACCESS_CIDR to one exact trusted IPv4 CIDR; 0.0.0.0/0 is rejected."
}

assert_deadline_contract() {
  [[ "${CLEANUP_DEADLINE_UTC:-}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] ||
    die "Set CLEANUP_DEADLINE_UTC in exact UTC form YYYY-MM-DDTHH:MM:SSZ."
  CLEANUP_DEADLINE_UTC="$CLEANUP_DEADLINE_UTC" python3 - <<'PY'
import datetime
import os

raw = os.environ["CLEANUP_DEADLINE_UTC"]
deadline = datetime.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(
    tzinfo=datetime.timezone.utc
)
now = datetime.datetime.now(datetime.timezone.utc)
delta = deadline - now
if not datetime.timedelta(minutes=15) < delta <= datetime.timedelta(hours=6):
    raise SystemExit(
        "Cleanup deadline must be more than 15 minutes and no more than 6 hours from now."
    )
PY
}

assert_selected_azs_and_capacity() {
  local az_a="${AVAILABILITY_ZONE_A:-}" az_b="${AVAILABILITY_ZONE_B:-}"
  [[ -n "$az_a" && -n "$az_b" && "$az_a" != "$az_b" ]] ||
    die "Set two distinct AVAILABILITY_ZONE_A and AVAILABILITY_ZONE_B values."
  local zones
  zones="$(aws_json ec2 describe-availability-zones --region "$REGION" --zone-names "$az_a" "$az_b")"
  [[ "$(jq -r --arg region "$REGION" '[.AvailabilityZones[] | select(.RegionName == $region and .State == "available")] | length' <<<"$zones")" == "2" ]] ||
    die "Both selected AZs must be available in ap-northeast-1."
  local az offerings
  for az in "$az_a" "$az_b"; do
    offerings="$(
      aws_json ec2 describe-instance-type-offerings --region "$REGION" \
        --location-type availability-zone \
        --filters "Name=location,Values=$az" "Name=instance-type,Values=t3.medium"
    )"
    [[ "$(jq -r '.InstanceTypeOfferings | length' <<<"$offerings")" -ge 1 ]] ||
      die "t3.medium is not offered in selected AZ $az."
  done
}

assert_eks_quota_headroom() {
  local quota clusters limit used
  quota="$(aws_json service-quotas get-service-quota --region "$REGION" --service-code eks --quota-code L-1194D53C)"
  clusters="$(aws_json eks list-clusters --region "$REGION")"
  limit="$(jq -er '.Quota.Value | numbers' <<<"$quota")"
  used="$(jq -er '.clusters | length' <<<"$clusters")"
  python3 - "$used" "$limit" <<'PY'
import sys
used, limit = int(sys.argv[1]), float(sys.argv[2])
if limit < 1 or used >= limit:
    raise SystemExit(f"No EKS cluster quota headroom remains ({used} used of {limit}).")
PY
}

assert_exact_tag_map() {
  local tags_json="$1" target="$2"
  local actual expected
  actual="$(
    jq -er '
      if (map(.Key) | length) != (map(.Key) | unique | length) then error("duplicate tag") else . end
      | sort_by(.Key) | map("\(.Key)=\(.Value)") | .[]
    ' <<<"$tags_json"
  )" || die "$target contains invalid or duplicate ownership tags."
  expected="$(
    printf '%s\n' \
      "Course=C010" \
      "ManagedBy=udemy4" \
      "Purpose=training" \
      "TemplateContract=$TEMPLATE_CONTRACT" \
      "WorkPackage=c010-common-eks" | sort
  )"
  [[ "$actual" == "$expected" ]] ||
    die "$target has unexpected or missing ownership tags."
}

assert_exact_guard_tag_map() {
  local tags_json="$1"
  local actual expected
  actual="$(
    jq -er '
      if (map(.Key) | length) != (map(.Key) | unique | length) then error("duplicate tag") else . end
      | sort_by(.Key) | map("\(.Key)=\(.Value)") | .[]
    ' <<<"$tags_json"
  )" || die "Cleanup guard contains invalid or duplicate ownership tags."
  expected="$(
    printf '%s\n' \
      "Course=C010" \
      "ManagedBy=udemy4" \
      "Purpose=training-cleanup-guard" \
      "TemplateContract=$GUARD_TEMPLATE_CONTRACT" \
      "WorkPackage=c010-common-eks" | sort
  )"
  [[ "$actual" == "$expected" ]] ||
    die "Cleanup guard stack has unexpected or missing ownership tags."
}

get_expected_guard_binding() {
  assert_aws_identity
  local stacks stack_id status tags outputs prefix
  stacks="$(aws_json cloudformation describe-stacks --region "$REGION" --stack-name "$GUARD_STACK_NAME")"
  [[ "$(jq -r '.Stacks | length' <<<"$stacks")" == "1" ]] ||
    die "Expected exactly one fixed cleanup guard stack."
  stack_id="$(jq -er '.Stacks[0].StackId' <<<"$stacks")"
  status="$(jq -er '.Stacks[0].StackStatus' <<<"$stacks")"
  prefix="arn:aws:cloudformation:$REGION:$AWS_ACCOUNT_ID:stack/$GUARD_STACK_NAME/"
  [[ "$stack_id" == "$prefix"* && "$status" == "CREATE_COMPLETE" ]] ||
    die "Cleanup guard stack ID, account, Region, name, or status mismatch."
  tags="$(jq -c '.Stacks[0].Tags' <<<"$stacks")"
  assert_exact_guard_tag_map "$tags"
  outputs="$(jq -c '.Stacks[0].Outputs | map({(.OutputKey): .OutputValue}) | add' <<<"$stacks")"
  [[ "$(jq -r 'keys | length' <<<"$outputs")" == "8" &&
    "$(jq -r '.TargetStackName' <<<"$outputs")" == "$STACK_NAME" &&
    "$(jq -r '.Region' <<<"$outputs")" == "$REGION" &&
    "$(jq -r '.TemplateContract' <<<"$outputs")" == "$GUARD_TEMPLATE_CONTRACT" &&
    "$(jq -r '.ScheduleName' <<<"$outputs")" == "$GUARD_SCHEDULE_NAME" &&
    "$(jq -r '.RoleName' <<<"$outputs")" == "$GUARD_ROLE_NAME" &&
    "$(jq -r '.CleanupRoleArn' <<<"$outputs")" == "arn:aws:iam::$AWS_ACCOUNT_ID:role/$GUARD_CLEANUP_HANDLER_ROLE_NAME" &&
    "$(jq -r '.HandlerFunctionName' <<<"$outputs")" == "$GUARD_CLEANUP_HANDLER_NAME" &&
    "$(jq -r '.StateMachineArn' <<<"$outputs")" == "arn:aws:states:$REGION:$AWS_ACCOUNT_ID:stateMachine:$GUARD_STATE_MACHINE_NAME" ]] ||
    die "Cleanup guard output binding mismatch."
  GUARD_STACK_ID="$stack_id"
  GUARD_STATE_MACHINE_ARN="$(jq -r '.StateMachineArn' <<<"$outputs")"
  export GUARD_STACK_ID GUARD_STATE_MACHINE_ARN
}

assert_exact_eks_cluster_tags() {
  local tags_object="$1" stack_id="$2"
  local actual expected
  actual="$(jq -r 'to_entries | sort_by(.key) | map("\(.key)=\(.value)") | .[]' <<<"$tags_object")"
  expected="$(
    printf '%s\n' \
      "Course=C010" \
      "ManagedBy=udemy4" \
      "Purpose=training" \
      "TemplateContract=$TEMPLATE_CONTRACT" \
      "WorkPackage=c010-common-eks" \
      "aws:cloudformation:logical-id=EksCluster" \
      "aws:cloudformation:stack-id=$stack_id" \
      "aws:cloudformation:stack-name=$STACK_NAME" | sort
  )"
  [[ "$actual" == "$expected" ]] ||
    die "EKS cluster has unexpected or missing ownership/system tags."
}

assert_failed_stack_document() {
  local stacks_json="$1"
  python3 - "$stacks_json" "$AWS_ACCOUNT_ID" "$REGION" "$STACK_NAME" "$TEMPLATE_CONTRACT" <<'PY' ||
import ipaddress
import json
import re
import sys

document = json.loads(sys.argv[1])
account, region, name, contract = sys.argv[2:]
stacks = document.get("Stacks")
if not isinstance(stacks, list) or len(stacks) != 1:
    raise SystemExit(1)
stack = stacks[0]
prefix = f"arn:aws:cloudformation:{region}:{account}:stack/{name}/"
if (
    stack.get("StackName") != name
    or not stack.get("StackId", "").startswith(prefix)
    or stack.get("StackStatus") != "ROLLBACK_COMPLETE"
):
    raise SystemExit(1)

expected_tags = {
    "Course": "C010",
    "ManagedBy": "udemy4",
    "Purpose": "training",
    "TemplateContract": contract,
    "WorkPackage": "c010-common-eks",
}
tags = stack.get("Tags")
if not isinstance(tags, list) or len(tags) != len(expected_tags):
    raise SystemExit(1)
tag_map = {}
for item in tags:
    if set(item) != {"Key", "Value"} or item["Key"] in tag_map:
        raise SystemExit(1)
    tag_map[item["Key"]] = item["Value"]
if tag_map != expected_tags:
    raise SystemExit(1)

parameters = stack.get("Parameters")
if not isinstance(parameters, list) or len(parameters) != 9:
    raise SystemExit(1)
parameter_map = {}
for item in parameters:
    if set(item) != {"ParameterKey", "ParameterValue"} or item["ParameterKey"] in parameter_map:
        raise SystemExit(1)
    parameter_map[item["ParameterKey"]] = item["ParameterValue"]
fixed = {
    "ClusterName": name,
    "CourseTag": "C010",
    "ManagedByTag": "udemy4",
    "PurposeTag": "training",
    "TemplateContractTag": contract,
    "WorkPackageTag": "c010-common-eks",
}
if set(parameter_map) != {
    "ApiPublicAccessCidr",
    "AvailabilityZoneA",
    "AvailabilityZoneB",
    *fixed,
}:
    raise SystemExit(1)
if any(parameter_map[key] != value for key, value in fixed.items()):
    raise SystemExit(1)
cidr = ipaddress.ip_network(parameter_map["ApiPublicAccessCidr"], strict=False)
if cidr.version != 4 or str(cidr) == "0.0.0.0/0":
    raise SystemExit(1)
az_a = parameter_map["AvailabilityZoneA"]
az_b = parameter_map["AvailabilityZoneB"]
if az_a == az_b or not all(re.fullmatch(r"ap-northeast-1[a-z]", az) for az in (az_a, az_b)):
    raise SystemExit(1)
print(stack["StackId"])
PY
    die "Failed-create stack account, Region, name, ARN, status, tags, or parameters mismatch."
}

get_failed_stack_binding() {
  local stacks="$1" stack_id
  assert_aws_identity
  stack_id="$(assert_failed_stack_document "$stacks")"
  aws_exact_not_found 'ResourceNotFoundException' \
    eks describe-cluster --region "$REGION" --name "$CLUSTER_NAME" ||
    die "ROLLBACK_COMPLETE recovery requires the exact EKS cluster to be absent."
  STACK_ID="$stack_id"
  printf -v FAILED_CREATE_RECOVERY_GATE_PASSED '%s|%s|%s|%s' \
    "$AWS_ACCOUNT_ID" "$REGION" "$STACK_ID" "ROLLBACK_COMPLETE"
  export STACK_ID FAILED_CREATE_RECOVERY_GATE_PASSED
}

get_expected_stack_binding() {
  assert_aws_identity
  assert_current_cloudshell_cidr
  local stacks stack_id tags outputs prefix cluster expected_arn expected_cidr
  stacks="$(aws_json cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_NAME")"
  [[ "$(jq -r '.Stacks | length' <<<"$stacks")" == "1" ]] ||
    die "Expected exactly one fixed CloudFormation stack."
  stack_id="$(jq -er '.Stacks[0].StackId' <<<"$stacks")"
  prefix="arn:aws:cloudformation:$REGION:$AWS_ACCOUNT_ID:stack/$STACK_NAME/"
  [[ "$stack_id" == "$prefix"* ]] ||
    die "Stack ID, account, Region, or name mismatch."
  tags="$(jq -c '.Stacks[0].Tags' <<<"$stacks")"
  assert_exact_tag_map "$tags" "CloudFormation stack"
  outputs="$(jq -c '.Stacks[0].Outputs | map({(.OutputKey): .OutputValue}) | add' <<<"$stacks")"
  [[ "$(jq -r '.ClusterName' <<<"$outputs")" == "$CLUSTER_NAME" &&
    "$(jq -r '.Region' <<<"$outputs")" == "$REGION" &&
    "$(jq -r '.TemplateContract' <<<"$outputs")" == "$TEMPLATE_CONTRACT" ]] ||
    die "Stack output binding mismatch."
  [[ "$(jq -r '[.Stacks[0].Outputs[] | select(.OutputKey == "CleanupRbacManifest")] | length' <<<"$stacks")" == "1" ]] ||
    die "Stack must expose exactly one CleanupRbacManifest output."
  CLEANUP_RBAC_MANIFEST="$(
    jq -er '.Stacks[0].Outputs[] | select(.OutputKey == "CleanupRbacManifest") | .OutputValue | select(length > 0)' <<<"$stacks"
  )" || die "Stack CleanupRbacManifest output is empty."
  [[ "$(jq -r '[.Stacks[0].Outputs[] | select(.OutputKey == "ApiPublicAccessCidr")] | length' <<<"$stacks")" == "1" ]] ||
    die "Stack must expose exactly one ApiPublicAccessCidr output."
  expected_cidr="$(jq -er '.Stacks[0].Outputs[] | select(.OutputKey == "ApiPublicAccessCidr") | .OutputValue' <<<"$stacks")"
  [[ "$expected_cidr" == "$API_PUBLIC_ACCESS_CIDR" && "$expected_cidr" != "0.0.0.0/0" ]] ||
    die "Stack ApiPublicAccessCidr does not equal the exact current CloudShell CIDR."
  cluster="$(aws_json eks describe-cluster --region "$REGION" --name "$CLUSTER_NAME")"
  expected_arn="arn:aws:eks:$REGION:$AWS_ACCOUNT_ID:cluster/$CLUSTER_NAME"
  [[ "$(jq -r '.cluster.name' <<<"$cluster")" == "$CLUSTER_NAME" &&
    "$(jq -r '.cluster.arn' <<<"$cluster")" == "$expected_arn" ]] ||
    die "EKS cluster ARN ownership mismatch."
  mapfile -t runtime_cidrs < <(jq -er '.cluster.resourcesVpcConfig.publicAccessCidrs[]' <<<"$cluster")
  assert_runtime_endpoint_values \
    "$(jq -r '.cluster.resourcesVpcConfig.endpointPrivateAccess' <<<"$cluster")" \
    "$(jq -r '.cluster.resourcesVpcConfig.endpointPublicAccess' <<<"$cluster")" \
    "$expected_cidr" \
    "${runtime_cidrs[@]}"
  assert_kubectl_minor_compatible \
    "$(kubectl version --client --output=json | jq -er '.clientVersion.gitVersion')" \
    "$(jq -er '.cluster.version' <<<"$cluster")"
  assert_exact_eks_cluster_tags "$(jq -c '.cluster.tags' <<<"$cluster")" "$stack_id"
  STACK_ID="$stack_id"
  CLUSTER_ARN="$expected_arn"
  export STACK_ID CLUSTER_ARN CLEANUP_RBAC_MANIFEST
}

assert_exact_kubernetes_context() {
  local expected="arn:aws:eks:$REGION:$AWS_ACCOUNT_ID:cluster/$CLUSTER_NAME"
  local actual
  actual="$(kubectl config current-context)"
  [[ "$actual" == "$expected" ]] ||
    die "Current kubectl context must equal the exact expected EKS cluster ARN."
}

section_s4_cleanup_gate_binding() {
  printf '%s|%s|%s|%s|%s|%s\n' \
    "$AWS_ACCOUNT_ID" "$REGION" "$CLUSTER_NAME" "$API_PUBLIC_ACCESS_CIDR" \
    "udemy4-s4-logs" "/udemy4/c010/s4/20260725"
}

require_section_s4_cleanup_gate() {
  local expected
  printf -v expected '%s|%s|%s|%s|%s|%s' \
    "$AWS_ACCOUNT_ID" "$REGION" "$CLUSTER_NAME" "$API_PUBLIC_ACCESS_CIDR" \
    "udemy4-s4-logs" "/udemy4/c010/s4/20260725"
  [[ "${SECTION_S4_CLEANUP_GATE_PASSED:-}" == "$expected" ]] ||
    die "Exact Section s4 namespace/Job/log-group residual gate must pass in this delete process."
}

require_common_cleanup_gate() {
  if [[ -n "${FAILED_CREATE_RECOVERY_GATE_PASSED:-}" ]]; then
    local expected
    printf -v expected '%s|%s|%s|%s' \
      "$AWS_ACCOUNT_ID" "$REGION" "$STACK_ID" "ROLLBACK_COMPLETE"
    [[ "$FAILED_CREATE_RECOVERY_GATE_PASSED" == "$expected" ]] ||
      die "Failed-create cleanup gate does not match the exact rollback stack binding."
    return
  fi
  require_section_s4_cleanup_gate
}

assert_section_s4_residuals_absent() {
  assert_exact_kubernetes_context
  local output
  if output="$(kubectl get namespace udemy4-s4-logs -o name 2>&1)"; then
    die "Section s4 namespace remains; run Section cleanup before common cleanup."
  elif ! grep -q 'NotFound' <<<"$output"; then
    die "Section s4 namespace residual check failed: $output"
  fi
  if output="$(kubectl get job s4-log-generator -n udemy4-s4-logs -o name 2>&1)"; then
    die "Section s4 Job remains; run Section cleanup before common cleanup."
  elif ! grep -q 'NotFound' <<<"$output"; then
    die "Section s4 Job residual check failed: $output"
  fi
  local groups
  groups="$(aws_json logs describe-log-groups --region "$REGION" --log-group-name-prefix "/udemy4/c010/s4/20260725")"
  [[ "$(jq -r '[.logGroups[] | select(.logGroupName == "/udemy4/c010/s4/20260725")] | length' <<<"$groups")" == "0" ]] ||
    die "Section s4 log group remains; run Section cleanup before common cleanup."
  printf -v SECTION_S4_CLEANUP_GATE_PASSED '%s|%s|%s|%s|%s|%s' \
    "$AWS_ACCOUNT_ID" "$REGION" "$CLUSTER_NAME" "$API_PUBLIC_ACCESS_CIDR" \
    "udemy4-s4-logs" "/udemy4/c010/s4/20260725"
  export SECTION_S4_CLEANUP_GATE_PASSED
}
