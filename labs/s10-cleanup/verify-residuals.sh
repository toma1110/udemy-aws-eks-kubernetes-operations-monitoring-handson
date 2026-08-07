#!/usr/bin/env bash
set -euo pipefail

readonly AWS_REGION="ap-northeast-1"
readonly CLUSTER_NAME="eks-fargate-ops-lab"
readonly LOG_GROUP="/aws/eks/eks-fargate-ops-lab/containers"
readonly IRSA_ROLE="eks-fargate-ops-irsa-reader"
readonly IRSA_POLICY="eks-fargate-ops-describe-cluster"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REAL_AWS="$(command -v aws)"
readonly VERIFY_DEADLINE_EPOCH="${VERIFY_DEADLINE_EPOCH:-$(( $(date +%s) + 300 ))}"
aws() { local now remaining; now="$(date +%s)"; remaining="$((VERIFY_DEADLINE_EPOCH - now))"; (( remaining > 0 )) || return 124; timeout "$remaining" "$REAL_AWS" "$@"; }

fail=0
pass() { printf 'PASS: %s\n' "$1"; }
residual() { printf 'RESIDUAL: %s\n' "$1" >&2; fail=1; }

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" || { residual "STS caller identity unreadable"; exit 1; }
[[ "$ACCOUNT_ID" =~ ^[0-9]{12}$ ]] || { residual "STS account ID malformed"; exit 1; }
[[ -n "${TARGET_RECORD_PATH:-}" && -f "$TARGET_RECORD_PATH" ]] || { residual "TARGET_RECORD_PATH must name the Git-external private target record"; exit 1; }
python "$SCRIPT_DIR/runtime_contract.py" validate-record --path "$TARGET_RECORD_PATH" --expected-account "$ACCOUNT_ID" >/dev/null 2>&1 || { residual "private target record is missing, tampered, or bound to a different STS account"; exit 1; }
EXPECTED_AWS_ACCOUNT_ID="$ACCOUNT_ID"
EXPECTED_OIDC_ISSUER="$(python -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8")).get("oidc_issuer") or "")' "$TARGET_RECORD_PATH")"
EXPECTED_POD_EXECUTION_ROLE_NAME="$(python -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8")).get("pod_execution_role_name") or "")' "$TARGET_RECORD_PATH")"
mapfile -t EXACT_STACK_IDS < <(python -c 'import json,sys; r=json.load(open(sys.argv[1],encoding="utf-8")); print("\n".join(x["stack_id"] for x in r["ownership"].values() if x))' "$TARGET_RECORD_PATH")
mapfile -t EXACT_VPC_IDS < <(python -c 'import json,sys; r=json.load(open(sys.argv[1],encoding="utf-8")); sys.stdout.write("\n".join(x["physical_id"] for x in r["ownership"]["cluster_stack"]["resources"] if x["type"]=="AWS::EC2::VPC"))' "$TARGET_RECORD_PATH")
mapfile -t EXACT_NAT_IDS < <(python -c 'import json,sys; r=json.load(open(sys.argv[1],encoding="utf-8")); sys.stdout.write("\n".join(x["physical_id"] for x in r["ownership"]["cluster_stack"]["resources"] if x["type"]=="AWS::EC2::NatGateway"))' "$TARGET_RECORD_PATH")
[[ "${#EXACT_STACK_IDS[@]}" -ge "1" ]] || { residual "private record lacks an exact stack identity anchor"; exit 1; }

if EKS_CHECK="$(aws eks describe-cluster --region "$AWS_REGION" --name "$CLUSTER_NAME" 2>&1)"; then
  residual "EKS cluster still exists"
  if PROFILE_LIST="$(aws eks list-fargate-profiles --region "$AWS_REGION" --cluster-name "$CLUSTER_NAME" --query 'fargateProfileNames' --output json 2>&1)"; then
    for profile in $(python -c 'import json,sys; print(" ".join(json.load(sys.stdin)))' <<<"$PROFILE_LIST"); do
      if PROFILE_CHECK="$(aws eks describe-fargate-profile --region "$AWS_REGION" --cluster-name "$CLUSTER_NAME" --fargate-profile-name "$profile" --output json 2>&1)"; then
        residual "Fargate Profile still exists: $profile"
        if [[ "$profile" == "ops-workloads" ]]; then
          DISCOVERED_POD_ROLE="$(python -c 'import json,sys; print(json.load(sys.stdin)["fargateProfile"]["podExecutionRoleArn"].rsplit("/",1)[-1])' <<<"$PROFILE_CHECK")"
          [[ "$DISCOVERED_POD_ROLE" == "$EXPECTED_POD_EXECUTION_ROLE_NAME" ]] || residual "workload Profile Pod Execution Role differs from ownership-proven input"
        fi
      else
        residual "listed Fargate Profile describe failed: $profile"
      fi
    done
  else
    residual "Fargate Profile list failed while cluster is readable"
  fi
elif grep -Fq 'ResourceNotFoundException' <<<"$EKS_CHECK"; then
  pass "EKS cluster absent"
  pass "Fargate profiles absent with cluster"
else
  residual "EKS lookup failed without exact ResourceNotFoundException"
fi

if ROLE_CHECK="$(aws iam get-role --role-name "$IRSA_ROLE" 2>&1)"; then residual "dedicated IAM role still exists"; elif grep -Fq 'NoSuchEntity' <<<"$ROLE_CHECK"; then pass "dedicated IAM role absent"; else residual "IAM role lookup failed without exact NoSuchEntity"; fi
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${IRSA_POLICY}"
if POLICY_CHECK="$(aws iam get-policy --policy-arn "$POLICY_ARN" 2>&1)"; then residual "dedicated IAM policy still exists"; elif grep -Fq 'NoSuchEntity' <<<"$POLICY_CHECK"; then pass "dedicated IAM policy absent"; else residual "IAM policy lookup failed without exact NoSuchEntity"; fi

if [[ -n "$EXPECTED_POD_EXECUTION_ROLE_NAME" ]] && POD_ROLE_CHECK="$(aws iam get-role --role-name "$EXPECTED_POD_EXECUTION_ROLE_NAME" 2>&1)"; then
  residual "ownership-proven Pod Execution Role still exists"
  if POD_INLINE_CHECK="$(aws iam get-role-policy --role-name "$EXPECTED_POD_EXECUTION_ROLE_NAME" --policy-name eks-fargate-ops-logging 2>&1)"; then residual "Pod Execution Role inline logging policy still exists"; elif grep -Fq 'NoSuchEntity' <<<"$POD_INLINE_CHECK"; then pass "Pod Execution Role inline logging policy absent"; else residual "Pod Execution Role inline policy lookup failed"; fi
elif [[ -n "$EXPECTED_POD_EXECUTION_ROLE_NAME" ]] && grep -Fq 'NoSuchEntity' <<<"$POD_ROLE_CHECK"; then
  pass "ownership-proven Pod Execution Role and inline logging policy absent"
elif [[ -n "$EXPECTED_POD_EXECUTION_ROLE_NAME" ]]; then
  residual "Pod Execution Role lookup failed without exact NoSuchEntity"
fi

if [[ -n "${EXPECTED_OIDC_ISSUER:-}" ]]; then
  OIDC_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${EXPECTED_OIDC_ISSUER}"
  if OIDC_CHECK="$(aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" 2>&1)"; then residual "cluster OIDC provider still exists"; elif grep -Fq 'NoSuchEntity' <<<"$OIDC_CHECK"; then pass "cluster OIDC provider absent"; else residual "OIDC lookup failed without exact NoSuchEntity"; fi
else
  residual "EXPECTED_OIDC_ISSUER is required to prove OIDC provider absence"
fi

LOG_COUNT="$(aws logs describe-log-groups --region "$AWS_REGION" --log-group-name-prefix "$LOG_GROUP" --query "length(logGroups[?logGroupName=='${LOG_GROUP}'])" --output text 2>/dev/null)" || { residual "CloudWatch Logs lookup failed"; LOG_COUNT="error"; }
[[ "$LOG_COUNT" == "0" ]] && pass "CloudWatch log group absent" || residual "CloudWatch log group still exists or count is indeterminate"

for stack_id in "${EXACT_STACK_IDS[@]}"; do
  if EXACT_STACK_CHECK="$(aws cloudformation describe-stacks --region "$AWS_REGION" --stack-name "$stack_id" 2>&1)"; then residual "recorded exact CloudFormation stack remains: $stack_id"; elif grep -Fq 'does not exist' <<<"$EXACT_STACK_CHECK"; then pass "recorded exact CloudFormation stack absent"; else residual "recorded exact CloudFormation stack lookup unreadable"; fi
done
STACK_COUNT="$(aws cloudformation list-stacks --region "$AWS_REGION" --stack-status-filter CREATE_IN_PROGRESS CREATE_FAILED CREATE_COMPLETE ROLLBACK_IN_PROGRESS ROLLBACK_FAILED ROLLBACK_COMPLETE DELETE_IN_PROGRESS DELETE_FAILED UPDATE_IN_PROGRESS UPDATE_COMPLETE_CLEANUP_IN_PROGRESS UPDATE_COMPLETE UPDATE_FAILED UPDATE_ROLLBACK_IN_PROGRESS UPDATE_ROLLBACK_FAILED UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS UPDATE_ROLLBACK_COMPLETE REVIEW_IN_PROGRESS IMPORT_IN_PROGRESS IMPORT_COMPLETE IMPORT_ROLLBACK_IN_PROGRESS IMPORT_ROLLBACK_FAILED IMPORT_ROLLBACK_COMPLETE --query "length(StackSummaries[?starts_with(StackName, 'eksctl-${CLUSTER_NAME}-')])" --output text 2>/dev/null)" || { residual "CloudFormation broad discovery failed"; STACK_COUNT="error"; }
[[ "$STACK_COUNT" == "0" ]] && pass "active eksctl CloudFormation stacks absent" || residual "active or failed eksctl CloudFormation stack remains"

for vpc_id in "${EXACT_VPC_IDS[@]}"; do
  if EXACT_VPC_CHECK="$(aws ec2 describe-vpcs --region "$AWS_REGION" --vpc-ids "$vpc_id" 2>&1)"; then residual "recorded exact VPC remains: $vpc_id"; elif grep -Eq 'InvalidVpcID.NotFound|does not exist' <<<"$EXACT_VPC_CHECK"; then pass "recorded exact VPC absent"; else residual "recorded exact VPC lookup unreadable"; fi
done
for nat_id in "${EXACT_NAT_IDS[@]}"; do
  if EXACT_NAT_CHECK="$(aws ec2 describe-nat-gateways --region "$AWS_REGION" --nat-gateway-ids "$nat_id" --output json 2>&1)"; then
    EXACT_NAT_COUNT="$(python -c 'import json,sys; print(len(json.load(sys.stdin).get("NatGateways",[])))' <<<"$EXACT_NAT_CHECK")" || { residual "recorded exact NAT result unreadable"; continue; }
    [[ "$EXACT_NAT_COUNT" == "0" ]] && pass "recorded exact NAT Gateway absent" || residual "recorded exact NAT Gateway remains: $nat_id"
  elif grep -Eq 'NatGatewayNotFound|does not exist' <<<"$EXACT_NAT_CHECK"; then pass "recorded exact NAT Gateway absent"; else residual "recorded exact NAT Gateway lookup unreadable"; fi
done
VPC_IDS="$(aws ec2 describe-vpcs --region "$AWS_REGION" --filters "Name=tag:alpha.eksctl.io/cluster-name,Values=$CLUSTER_NAME" --query 'Vpcs[].VpcId' --output text 2>/dev/null)" || { residual "VPC broad discovery failed"; VPC_IDS="error"; }
if [[ -z "$VPC_IDS" ]]; then NAT_COUNT="0"; else NAT_COUNT="$(aws ec2 describe-nat-gateways --region "$AWS_REGION" --filter "Name=vpc-id,Values=$VPC_IDS" "Name=state,Values=pending,available,deleting,failed" --query 'length(NatGateways)' --output text 2>/dev/null)" || { residual "NAT Gateway lookup failed"; NAT_COUNT="error"; }; fi
[[ -z "$VPC_IDS" ]] && VPC_COUNT="0" || VPC_COUNT="1"
if [[ "$VPC_COUNT" == "0" && "$NAT_COUNT" == "0" ]]; then pass "tagged VPC and NAT Gateway resources absent"; else residual "tagged VPC or NAT Gateway resource remains"; fi

if [[ "$fail" == "0" ]]; then
  pass "no billable training resource residual was detected"
else
  printf 'STOP: cleanup is incomplete; record each residual and its owner.\n' >&2
  exit 1
fi
