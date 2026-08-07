#!/usr/bin/env bash
set -euo pipefail

MODE="${1:---plan}"
[[ "$MODE" == "--plan" || "$MODE" == "--execute" ]] || { printf 'Usage: bash cleanup.sh [--plan|--execute]\n' >&2; exit 2; }

readonly EXPECTED_REGION="ap-northeast-1"
readonly EXPECTED_CLUSTER="eks-fargate-ops-lab"
readonly EXPECTED_NAMESPACE="eks-fargate-ops"
readonly WORKLOAD_PROFILE="ops-workloads"
readonly COREDNS_PROFILE="system-coredns"
readonly LOG_GROUP="/aws/eks/eks-fargate-ops-lab/containers"
readonly IRSA_ROLE="eks-fargate-ops-irsa-reader"
readonly IRSA_POLICY="eks-fargate-ops-describe-cluster"
readonly LOGGING_POLICY="eks-fargate-ops-logging"

stop() { printf 'STOP: %s\n' "$1" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || stop "$1 is required"; }

need aws
need eksctl
need kubectl
need python
need timeout

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly START_EPOCH="$(date +%s)"
readonly CLEANUP_DEADLINE_EPOCH="${CLEANUP_DEADLINE_EPOCH:-$((START_EPOCH + 3600))}"
readonly RESIDUAL_RESERVE_SECONDS=180
readonly MUTATION_DEADLINE_EPOCH="$((CLEANUP_DEADLINE_EPOCH - RESIDUAL_RESERVE_SECONDS))"
[[ "$CLEANUP_DEADLINE_EPOCH" =~ ^[0-9]+$ && "$MUTATION_DEADLINE_EPOCH" -gt "$START_EPOCH" ]] || stop "CLEANUP_DEADLINE_EPOCH must reserve 180 seconds after mutation"
remaining_seconds() { local now; now="$(date +%s)"; (( MUTATION_DEADLINE_EPOCH > now )) || return 1; printf '%s\n' "$((MUTATION_DEADLINE_EPOCH - now))"; }
verification_seconds() { local now; now="$(date +%s)"; (( CLEANUP_DEADLINE_EPOCH > now )) || return 1; printf '%s\n' "$((CLEANUP_DEADLINE_EPOCH - now))"; }
run_residual_check() { local remaining; remaining="$(verification_seconds)" || return 1; timeout "$remaining" env TARGET_RECORD_PATH="$TARGET_RECORD_PATH" VERIFY_DEADLINE_EPOCH="$CLEANUP_DEADLINE_EPOCH" bash "$SCRIPT_DIR/verify-residuals.sh"; }
incomplete() { printf 'STOP: %s; cleanup remains incomplete.\n' "$1" >&2; run_residual_check || true; exit 1; }
run_bounded() { local remaining; remaining="$(remaining_seconds)" || incomplete "cleanup deadline reached before $1"; local label="$1"; shift; timeout "$remaining" "$@" || incomplete "$label timed out or failed"; }
bounded_read() { local destination="$1" label="$2" remaining output status; shift 2; remaining="$(remaining_seconds)" || incomplete "cleanup deadline reached before $label"; set +e; output="$(timeout "$remaining" "$@" 2>&1)"; status=$?; set -e; [[ "$status" != "124" ]] || incomplete "$label timed out"; printf -v "$destination" '%s' "$output"; return "$status"; }

[[ "${AWS_REGION:-}" == "$EXPECTED_REGION" ]] || stop "AWS_REGION must be exactly $EXPECTED_REGION"
[[ "${AWS_DEFAULT_REGION:-}" == "$EXPECTED_REGION" ]] || stop "AWS_DEFAULT_REGION must be exactly $EXPECTED_REGION"
[[ "${CLUSTER_NAME:-}" == "$EXPECTED_CLUSTER" ]] || stop "CLUSTER_NAME must be exactly $EXPECTED_CLUSTER"
[[ "${NAMESPACE:-}" == "$EXPECTED_NAMESPACE" ]] || stop "NAMESPACE must be exactly $EXPECTED_NAMESPACE"
[[ "${EXPECTED_AWS_ACCOUNT_ID:-}" =~ ^[0-9]{12}$ ]] || stop "EXPECTED_AWS_ACCOUNT_ID must be a 12-digit value"
[[ "${CONFIRM_CLEANUP_TARGET:-}" == "DELETE $EXPECTED_CLUSTER IN $EXPECTED_REGION" ]] || stop "confirmation phrase does not match the exact target"
[[ -n "${TARGET_RECORD_PATH:-}" && -f "$TARGET_RECORD_PATH" ]] || stop "TARGET_RECORD_PATH must name the Git-external private target record"

CALLER_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" || stop "STS caller identity was not obtained"
[[ "$CALLER_ACCOUNT_ID" == "$EXPECTED_AWS_ACCOUNT_ID" ]] || stop "STS account does not match the expected account"
EXPECTED_CLUSTER_ARN="arn:aws:eks:${EXPECTED_REGION}:${CALLER_ACCOUNT_ID}:cluster/${EXPECTED_CLUSTER}"
python "$SCRIPT_DIR/runtime_contract.py" validate-record --path "$TARGET_RECORD_PATH" --expected-account "$CALLER_ACCOUNT_ID" >/dev/null || stop "private target record validation failed"
OIDC_ISSUER="$(python -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8")).get("oidc_issuer") or "")' "$TARGET_RECORD_PATH")"
POD_ROLE_NAME="$(python -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8")).get("pod_execution_role_name") or "")' "$TARGET_RECORD_PATH")"
CAPTURE_MODE="$(python -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8")).get("capture_mode","complete"))' "$TARGET_RECORD_PATH")"

CLUSTER_PRESENT="false"
if CLUSTER_LOOKUP="$(aws eks describe-cluster --region "$EXPECTED_REGION" --name "$EXPECTED_CLUSTER" --output json 2>&1)"; then
  CLUSTER_PRESENT="true"
  CLUSTER_JSON="$CLUSTER_LOOKUP"
  python -c 'import json,sys; d=json.load(sys.stdin)["cluster"]; t=d.get("tags",{}); assert d.get("arn")==sys.argv[1]; assert t.get("Course")=="c010" and t.get("Section")=="s3"; assert t.get("ManagedBy")=="learner" and t.get("Purpose")=="training"' "$EXPECTED_CLUSTER_ARN" <<<"$CLUSTER_JSON" || stop "EKS cluster ARN or ownership tags do not match"
  python -c 'import json,sys; d=json.load(sys.stdin)["cluster"]; assert d["identity"]["oidc"]["issuer"].removeprefix("https://")==sys.argv[1]' "$OIDC_ISSUER" <<<"$CLUSTER_JSON" || stop "current cluster OIDC issuer differs from the private target record"
elif grep -Fq 'ResourceNotFoundException' <<<"$CLUSTER_LOOKUP"; then
  : # The private record and current tagged stacks remain mandatory below.
else
  stop "cluster lookup failed without exact ResourceNotFoundException"
fi

if [[ "$CAPTURE_MODE" == "complete" ]]; then
  python "$SCRIPT_DIR/runtime_contract.py" verify-inputs --expected-account "$EXPECTED_AWS_ACCOUNT_ID" --actual-account "$CALLER_ACCOUNT_ID" --issuer "$OIDC_ISSUER" --pod-role "$POD_ROLE_NAME" >/dev/null || stop "complete target record lacks exact verifier inputs"
fi

if [[ "$CLUSTER_PRESENT" == "true" ]]; then
CURRENT_CONTEXT="$(kubectl config current-context 2>/dev/null)" || stop "current Kubernetes context is unreadable"
[[ "$CURRENT_CONTEXT" == "$EXPECTED_CLUSTER_ARN" ]] || stop "current Kubernetes context is not the exact intended cluster ARN"

if NAMESPACE_CHECK="$(kubectl get namespace "$EXPECTED_NAMESPACE" -o json 2>&1)"; then
  NAMESPACE_LABELS="$(python -c 'import json,sys; labels=json.load(sys.stdin).get("metadata",{}).get("labels",{}); print("{},{}".format(labels.get("course",""),labels.get("section","")))' <<<"$NAMESPACE_CHECK")"
  [[ "$NAMESPACE_LABELS" == "c010,s3" ]] || stop "namespace ownership labels do not match"
elif grep -Fq '(NotFound)' <<<"$NAMESPACE_CHECK"; then
  NAMESPACE_LABELS="absent"
else
  stop "namespace lookup failed without an exact NotFound result"
fi

PROFILE_LIST="$(aws eks list-fargate-profiles --region "$EXPECTED_REGION" --cluster-name "$EXPECTED_CLUSTER" --query 'fargateProfileNames' --output json)" || stop "Fargate Profile list failed"
python -c 'import json,sys; assert set(json.load(sys.stdin)).issubset({"ops-workloads","system-coredns"})' <<<"$PROFILE_LIST" || stop "unexpected Fargate Profile exists"

for profile in "$WORKLOAD_PROFILE" "$COREDNS_PROFILE"; do
  if grep -Fq "\"$profile\"" <<<"$PROFILE_LIST"; then
    PROFILE_JSON="$(aws eks describe-fargate-profile --region "$EXPECTED_REGION" --cluster-name "$EXPECTED_CLUSTER" --fargate-profile-name "$profile" --output json)" || stop "listed Fargate Profile describe failed"
    python -c 'import json,sys; p=json.load(sys.stdin)["fargateProfile"]; n=sys.argv[1]; e=({"namespace":"eks-fargate-ops","labels":{"compute":"ops-lab"}} if n=="ops-workloads" else {"namespace":"kube-system","labels":{"k8s-app":"kube-dns"}}); t=p.get("tags",{}); assert p.get("fargateProfileName")==n and p.get("selectors")==[e]; assert t.get("Course")=="c010" and t.get("Section")=="s3" and t.get("ManagedBy")=="learner" and t.get("Purpose")=="training"' "$profile" <<<"$PROFILE_JSON" || stop "Fargate Profile identity does not match"
  fi
done

if LOGGING_CHECK="$(kubectl get configmap aws-logging -n aws-observability -o json 2>&1)"; then
  CONFIGMAP_STATE="present"
  LOGGING_OUTPUT="$(python -c 'import json,sys; print(json.load(sys.stdin).get("data",{}).get("output.conf",""))' <<<"$LOGGING_CHECK")"
  grep -Fq "log_group_name $LOG_GROUP" <<<"$LOGGING_OUTPUT" || stop "logging ConfigMap points to a different log group"
elif grep -Fq '(NotFound)' <<<"$LOGGING_CHECK"; then
  CONFIGMAP_STATE="absent"
else
  stop "logging ConfigMap lookup failed without an exact NotFound result"
fi
if grep -Fq "\"$WORKLOAD_PROFILE\"" <<<"$PROFILE_LIST"; then
  WORKLOAD_PROFILE_JSON="$(aws eks describe-fargate-profile --region "$EXPECTED_REGION" --cluster-name "$EXPECTED_CLUSTER" --fargate-profile-name "$WORKLOAD_PROFILE" --output json)" || stop "workload Fargate Profile describe failed"
  CURRENT_POD_ROLE_NAME="$(python -c 'import json,sys; print(json.load(sys.stdin)["fargateProfile"]["podExecutionRoleArn"].rsplit("/",1)[-1])' <<<"$WORKLOAD_PROFILE_JSON")"
  [[ "$CURRENT_POD_ROLE_NAME" == "$POD_ROLE_NAME" ]] || stop "current workload Profile role differs from the private target record"
else
  : # An absent workload Profile is accepted only by the monotonic restart validator below.
fi
else
  NAMESPACE_LABELS="absent"
  CONFIGMAP_STATE="absent"
fi

if [[ "$CAPTURE_MODE" == "complete" ]]; then
  python "$SCRIPT_DIR/runtime_contract.py" verify-inputs --expected-account "$EXPECTED_AWS_ACCOUNT_ID" --actual-account "$CALLER_ACCOUNT_ID" --issuer "$OIDC_ISSUER" --pod-role "$POD_ROLE_NAME" >/dev/null || stop "exact verifier inputs are invalid"
fi

PREFLIGHT_SNAPSHOT="$(mktemp)"
trap 'rm -f -- "$PREFLIGHT_SNAPSHOT"' EXIT
NAMESPACE_STATE="$([[ "$NAMESPACE_LABELS" == "absent" ]] && printf absent || printf present)"
if [[ "$CAPTURE_MODE" == "partial-stack-anchor" && "$CLUSTER_PRESENT" == "true" ]]; then RESTART_BRANCH="partial-readable-cluster"; elif [[ "$CAPTURE_MODE" == "partial-stack-anchor" ]]; then RESTART_BRANCH="partial-cluster-absent"; elif [[ "$CLUSTER_PRESENT" == "true" ]]; then RESTART_BRANCH="readable-cluster"; else RESTART_BRANCH="cluster-absent"; fi
python "$SCRIPT_DIR/execute_preflight.py" --record "$TARGET_RECORD_PATH" --snapshot "$PREFLIGHT_SNAPSHOT" --expected-account "$CALLER_ACCOUNT_ID" --namespace-state "$NAMESPACE_STATE" --configmap-state "$CONFIGMAP_STATE" --branch "$RESTART_BRANCH" >/dev/null || stop "complete read-only restart preflight failed"
IRSA_DECISION="$(python "$SCRIPT_DIR/runtime_contract.py" decide-irsa-cleanup --record "$TARGET_RECORD_PATH" --snapshot "$PREFLIGHT_SNAPSHOT" --expected-account "$CALLER_ACCOUNT_ID")" || stop "final restart preflight and IRSA route decision failed"
IRSA_ACTION="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["action"])' "$IRSA_DECISION")" || stop "IRSA route decision is unreadable"
IRSA_PLAN="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["plan"])' "$IRSA_DECISION")" || stop "IRSA cleanup plan is unreadable"
CLUSTER_STACK_STATE="$(python -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["population"]["cluster_stack"])' "$PREFLIGHT_SNAPSHOT")"
printf 'PASS: complete read-only preflight for exact cleanup target\n'
printf 'PLAN: namespace %s\n' "$EXPECTED_NAMESPACE"
printf 'PLAN: logging ConfigMap aws-observability/aws-logging\n'
printf 'PLAN: %s\n' "$IRSA_PLAN"
printf 'PLAN: Fargate profiles %s, %s\n' "$WORKLOAD_PROFILE" "$COREDNS_PROFILE"
printf 'PLAN: eksctl cluster stack, VPC, and NAT resources\n'
printf 'PLAN: CloudWatch Logs group %s\n' "$LOG_GROUP"
[[ "$MODE" == "--execute" ]] || exit 0

if [[ "$CLUSTER_PRESENT" == "true" ]]; then
  if [[ "$NAMESPACE_LABELS" != "absent" ]]; then
    run_bounded "namespace deletion" kubectl delete namespace "$EXPECTED_NAMESPACE" --wait=true --timeout=10m
  fi
  if [[ -n "${LOGGING_OUTPUT:-}" ]]; then
    run_bounded "logging ConfigMap deletion" kubectl delete configmap aws-logging -n aws-observability --wait=true
  fi
fi

if [[ "$IRSA_ACTION" == "delete-iamserviceaccount" ]]; then
  bounded_read IRSA_ROLE_CHECK "IRSA role post-mutation lookup" aws iam get-role --role-name "$IRSA_ROLE" || incomplete "validated IRSA role became unreadable before iamserviceaccount deletion"
  run_bounded "iamserviceaccount deletion" eksctl delete iamserviceaccount --region "$EXPECTED_REGION" --cluster "$EXPECTED_CLUSTER" --namespace "$EXPECTED_NAMESPACE" --name irsa-reader --wait
elif [[ "$IRSA_ACTION" == "delete-exact-stack" ]]; then
  if [[ "$CLUSTER_PRESENT" == "true" ]] && bounded_read IRSA_ROLE_CHECK "IRSA role absence recheck" aws iam get-role --role-name "$IRSA_ROLE"; then
    incomplete "IRSA role appeared after the validated role-absent decision"
  elif [[ "$CLUSTER_PRESENT" == "true" ]] && ! grep -Fq 'NoSuchEntity' <<<"$IRSA_ROLE_CHECK"; then
    incomplete "IRSA role absence could not be reconfirmed"
  fi
  run_bounded "iamserviceaccount stack deletion request" aws cloudformation delete-stack --region "$EXPECTED_REGION" --stack-name "eksctl-${EXPECTED_CLUSTER}-addon-iamserviceaccount-${EXPECTED_NAMESPACE}-irsa-reader"
  run_bounded "iamserviceaccount stack deletion wait" aws cloudformation wait stack-delete-complete --region "$EXPECTED_REGION" --stack-name "eksctl-${EXPECTED_CLUSTER}-addon-iamserviceaccount-${EXPECTED_NAMESPACE}-irsa-reader"
fi

POLICY_ARN="arn:aws:iam::${CALLER_ACCOUNT_ID}:policy/${IRSA_POLICY}"
if bounded_read IRSA_POLICY_CHECK "IRSA policy post-mutation lookup" aws iam get-policy --policy-arn "$POLICY_ARN"; then
  bounded_read ATTACHMENTS "IRSA policy attachment post-mutation read" aws iam list-entities-for-policy --policy-arn "$POLICY_ARN" --query 'length(PolicyGroups)+length(PolicyUsers)+length(PolicyRoles)' --output text || incomplete "IAM policy attachments could not be read"
  [[ "$ATTACHMENTS" == "0" ]] || incomplete "IAM policy is still attached; do not delete it"
  run_bounded "IRSA policy deletion" aws iam delete-policy --policy-arn "$POLICY_ARN"
elif ! grep -Fq 'NoSuchEntity' <<<"$IRSA_POLICY_CHECK"; then
  incomplete "IRSA policy lookup failed without exact NoSuchEntity"
fi

if [[ "$CLUSTER_PRESENT" == "false" && "$CLUSTER_STACK_STATE" == "present" ]]; then
  run_bounded "cluster stack deletion request" aws cloudformation delete-stack --region "$EXPECTED_REGION" --stack-name "eksctl-${EXPECTED_CLUSTER}-cluster"
  run_bounded "cluster stack deletion wait" aws cloudformation wait stack-delete-complete --region "$EXPECTED_REGION" --stack-name "eksctl-${EXPECTED_CLUSTER}-cluster"
fi

OIDC_ARN="arn:aws:iam::${CALLER_ACCOUNT_ID}:oidc-provider/${OIDC_ISSUER}"
if [[ -n "$OIDC_ISSUER" ]] && bounded_read OIDC_CHECK "OIDC provider post-mutation lookup" aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN"; then
  bounded_read ROLE_POPULATION "OIDC reference post-mutation role read" aws iam list-roles --output json || incomplete "OIDC role references could not be read"
  TRUST_REFERENCES="$(python -c 'import json,sys; needle=sys.argv[1]; print(sum(needle in json.dumps(r.get("AssumeRolePolicyDocument",{}),sort_keys=True) for r in json.load(sys.stdin).get("Roles",[])))' "$OIDC_ISSUER" <<<"$ROLE_POPULATION")" || incomplete "OIDC role references could not be normalized"
  [[ "$TRUST_REFERENCES" == "0" ]] || incomplete "OIDC provider is still referenced by an IAM role"
  run_bounded "OIDC provider deletion" aws iam delete-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN"
elif [[ -n "$OIDC_ISSUER" ]] && ! grep -Fq 'NoSuchEntity' <<<"$OIDC_CHECK"; then
  incomplete "OIDC provider lookup failed without exact NoSuchEntity"
fi

if [[ "$CLUSTER_PRESENT" == "true" ]]; then
  if bounded_read LOGGING_POLICY_CHECK "Pod role inline policy post-mutation lookup" aws iam get-role-policy --role-name "$POD_ROLE_NAME" --policy-name "$LOGGING_POLICY"; then
    run_bounded "Pod Execution Role inline policy deletion" aws iam delete-role-policy --role-name "$POD_ROLE_NAME" --policy-name "$LOGGING_POLICY"
  elif ! grep -Fq 'NoSuchEntity' <<<"$LOGGING_POLICY_CHECK"; then
    incomplete "Pod Execution Role inline policy lookup failed without exact NoSuchEntity"
  fi
else
  if [[ -n "$POD_ROLE_NAME" ]] && bounded_read POD_ROLE_CHECK "Pod role post-stack lookup" aws iam get-role --role-name "$POD_ROLE_NAME" --output json; then
    incomplete "recorded Pod Execution Role remains after ownership-proven cluster stack deletion"
  elif [[ -n "$POD_ROLE_NAME" ]] && ! grep -Fq 'NoSuchEntity' <<<"$POD_ROLE_CHECK"; then
    incomplete "partial Pod Execution Role lookup failed without exact NoSuchEntity"
  fi
fi

if [[ "$CLUSTER_PRESENT" == "true" ]]; then
for profile in "$WORKLOAD_PROFILE" "$COREDNS_PROFILE"; do
  if grep -Fq "\"$profile\"" <<<"$PROFILE_LIST"; then
    run_bounded "Fargate Profile deletion request" aws eks delete-fargate-profile --region "$EXPECTED_REGION" --cluster-name "$EXPECTED_CLUSTER" --fargate-profile-name "$profile" >/dev/null
    while true; do
      if bounded_read PROFILE_WAIT "Fargate Profile post-mutation polling read" aws eks describe-fargate-profile --region "$EXPECTED_REGION" --cluster-name "$EXPECTED_CLUSTER" --fargate-profile-name "$profile"; then
        run_bounded "Fargate Profile deletion polling interval" sleep 15
      elif grep -Fq 'ResourceNotFoundException' <<<"$PROFILE_WAIT"; then
        break
      else
        incomplete "Fargate Profile deletion could not be proven by exact ResourceNotFoundException"
      fi
    done
  fi
done

run_bounded "eksctl cluster deletion" eksctl delete cluster --region "$EXPECTED_REGION" --name "$EXPECTED_CLUSTER" --wait
fi
bounded_read LOG_COUNT "CloudWatch log group post-mutation lookup" aws logs describe-log-groups --region "$EXPECTED_REGION" --log-group-name-prefix "$LOG_GROUP" --query "length(logGroups[?logGroupName=='${LOG_GROUP}'])" --output text || incomplete "CloudWatch log group lookup failed"
if [[ "$LOG_COUNT" == "1" ]]; then
  run_bounded "CloudWatch log group deletion" aws logs delete-log-group --region "$EXPECTED_REGION" --log-group-name "$LOG_GROUP"
elif [[ "$LOG_COUNT" != "0" ]]; then
  incomplete "CloudWatch log group exact count is indeterminate"
fi

run_residual_check
