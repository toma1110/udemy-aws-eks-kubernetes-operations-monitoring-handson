#!/usr/bin/env bash
set -euo pipefail

readonly REGION="ap-northeast-1"
readonly CLUSTER_NAME="udemy4-c010-common-20260724"
readonly TEMPLATE_CONTRACT="udemy4-c010-common-eks-v2-20260724"
readonly NAMESPACE="udemy4-s4-logs"
readonly JOB_NAME="s4-log-generator"
readonly LOG_GROUP_NAME="/udemy4/c010/s4/20260725"
readonly LOG_STREAM_NAME="sample-workload"

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
  [[ "${API_PUBLIC_ACCESS_CIDR:-}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/32$ &&
    "$API_PUBLIC_ACCESS_CIDR" != "0.0.0.0/0" ]] ||
    die "Set API_PUBLIC_ACCESS_CIDR to the exact current CloudShell IPv4 /32."
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

record_current_sts_identity() {
  local identity_file="${CURRENT_STS_IDENTITY_FILE:-}"
  [[ "$identity_file" == /* ]] || {
    die "Set CURRENT_STS_IDENTITY_FILE to an absolute run-private path outside Git."
    return 1
  }
  local private_dir
  private_dir="$(dirname -- "$identity_file")"
  [[ -d "$private_dir" ]] || {
    die "The current-run private identity directory must already exist."
    return 1
  }
  if git -C "$private_dir" rev-parse --show-toplevel >/dev/null 2>&1; then
    die "Current STS identity evidence must remain outside every Git worktree."
    return 1
  fi
  local identity temporary
  identity="$(aws_json sts get-caller-identity)" || {
    die "Current default CloudShell STS identity could not be obtained."
    return 1
  }
  jq -e '
    . as $identity |
    (keys | sort) == ["Account", "Arn", "UserId"] and
    ($identity.Account | type == "string" and test("^[0-9]{12}$")) and
    ($identity.Arn | type == "string" and
      test("^arn:[^:]+:(iam|sts)::[0-9]{12}:.+$")) and
    (($identity.Arn | capture("^arn:[^:]+:(?:iam|sts)::(?<account>[0-9]{12}):").account)
      == $identity.Account) and
    ($identity.UserId | type == "string" and length > 0)
  ' <<<"$identity" >/dev/null || {
    die "Current default CloudShell STS identity is invalid."
    return 1
  }
  temporary="${identity_file}.tmp.$$"
  (umask 077; jq -S . <<<"$identity" >"$temporary") || {
    rm -f -- "$temporary"
    die "Current STS identity evidence could not be written."
    return 1
  }
  if [[ -f "$identity_file" ]]; then
    cmp -s -- "$identity_file" "$temporary" || {
      rm -f -- "$temporary"
      die "Current default STS identity changed within this run."
      return 1
    }
    rm -f -- "$temporary"
    return 0
  fi
  mv -f -- "$temporary" "$identity_file" || {
    rm -f -- "$temporary"
    die "Current STS identity evidence could not be finalized."
    return 1
  }
}

assert_exact_stack_tags() {
  local tags_json="$1"
  python3 - "$tags_json" "$TEMPLATE_CONTRACT" <<'PY' ||
import json
import sys

items = json.loads(sys.argv[1])
if (
    not isinstance(items, list)
    or len(items) != 5
    or any(
        not isinstance(item, dict)
        or set(item) != {"Key", "Value"}
        or not isinstance(item["Key"], str)
        or not isinstance(item["Value"], str)
        for item in items
    )
):
    raise SystemExit(1)
actual = {item["Key"]: item["Value"] for item in items}
expected = {
    "Course": "C010",
    "ManagedBy": "udemy4",
    "Purpose": "training",
    "TemplateContract": sys.argv[2],
    "WorkPackage": "c010-common-eks",
}
if len(actual) != len(items) or actual != expected:
    raise SystemExit(1)
PY
    die "Common stack has unexpected or missing ownership tags."
}

assert_exact_eks_tags() {
  local tags_object="$1" stack_id="$2"
  python3 - \
    "$tags_object" \
    "$stack_id" \
    "$CLUSTER_NAME" \
    "$TEMPLATE_CONTRACT" <<'PY' ||
import json
import sys

items = json.loads(sys.argv[1])
if not isinstance(items, dict) or not all(
    isinstance(key, str) and isinstance(value, str) for key, value in items.items()
):
    raise SystemExit(1)
expected = {
    "Course": "C010",
    "ManagedBy": "udemy4",
    "Purpose": "training",
    "TemplateContract": sys.argv[4],
    "WorkPackage": "c010-common-eks",
    "aws:cloudformation:logical-id": "EksCluster",
    "aws:cloudformation:stack-id": sys.argv[2],
    "aws:cloudformation:stack-name": sys.argv[3],
}
if items != expected:
    raise SystemExit(1)
PY
    die "EKS cluster contains invalid ownership tags."
}

assert_fixed_stack_outputs() {
  local outputs="$1"
  python3 - "$outputs" "$CLUSTER_NAME" "$REGION" "$TEMPLATE_CONTRACT" <<'PY' ||
import json
import sys

items = json.loads(sys.argv[1])
expected = {
    "ClusterName": sys.argv[2],
    "Region": sys.argv[3],
    "TemplateContract": sys.argv[4],
}
for key, value in expected.items():
    matches = [
        item for item in items
        if isinstance(item, dict) and item.get("OutputKey") == key
    ]
    if len(matches) != 1 or matches[0].get("OutputValue") != value:
        raise SystemExit(1)
PY
    die "Common stack fixed ClusterName, Region, or TemplateContract output binding mismatch."
}

assert_external_binding() {
  require_command aws
  require_command kubectl
  require_command jq
  require_command python3
  require_command curl
  local aws_version
  aws_version="$(aws --version 2>&1)"
  assert_aws_cli_minimum_text "$aws_version"
  kubectl version --client --output=json |
    jq -e '.clientVersion.gitVersion | strings | length > 0' >/dev/null ||
    die "kubectl client version check failed."
  [[ "${AWS_REGION:-}" == "$REGION" && "${AWS_DEFAULT_REGION:-}" == "$REGION" ]] ||
    die "Set AWS_REGION and AWS_DEFAULT_REGION to ap-northeast-1."
  assert_current_cloudshell_cidr
  local cluster cluster_arn context stacks expected_cidr stack_id
  cluster="$(aws_json eks describe-cluster --region "$REGION" --name "$CLUSTER_NAME")"
  cluster_arn="$(jq -er '.cluster.arn' <<<"$cluster")"
  [[ "$cluster_arn" =~ ^arn:[^:]+:eks:$REGION:[^:]+:cluster/$CLUSTER_NAME$ &&
    "$(jq -r '.cluster.status' <<<"$cluster")" == "ACTIVE" ]] ||
    die "Exact common EKS cluster binding is not ACTIVE."
  stacks="$(aws_json cloudformation describe-stacks --region "$REGION" --stack-name "$CLUSTER_NAME")"
  stack_id="$(jq -er '.Stacks[0].StackId' <<<"$stacks")"
  [[ "$(jq -r '.Stacks | length' <<<"$stacks")" == "1" &&
    "$stack_id" =~ ^arn:[^:]+:cloudformation:$REGION:[^:]+:stack/$CLUSTER_NAME/.+$ ]] ||
    die "Exact common CloudFormation stack binding mismatch."
  assert_exact_stack_tags "$(jq -c '.Stacks[0].Tags' <<<"$stacks")"
  assert_fixed_stack_outputs "$(jq -c '.Stacks[0].Outputs' <<<"$stacks")"
  assert_exact_eks_tags "$(jq -c '.cluster.tags' <<<"$cluster")" "$stack_id"
  [[ "$(jq -r '[.Stacks[0].Outputs[] | select(.OutputKey == "CleanupRbacManifest")] | length' <<<"$stacks")" == "1" ]] ||
    die "Common stack must expose exactly one CleanupRbacManifest output."
  CLEANUP_RBAC_MANIFEST="$(
    jq -er '.Stacks[0].Outputs[] | select(.OutputKey == "CleanupRbacManifest") | .OutputValue | select(length > 0)' <<<"$stacks"
  )" || die "Common stack CleanupRbacManifest output is empty."
  export CLEANUP_RBAC_MANIFEST
  [[ "$(jq -r '[.Stacks[0].Outputs[] | select(.OutputKey == "ApiPublicAccessCidr")] | length' <<<"$stacks")" == "1" ]] ||
    die "Stack must expose exactly one ApiPublicAccessCidr output."
  expected_cidr="$(jq -er '.Stacks[0].Outputs[] | select(.OutputKey == "ApiPublicAccessCidr") | .OutputValue' <<<"$stacks")"
  [[ "$expected_cidr" == "$API_PUBLIC_ACCESS_CIDR" && "$expected_cidr" != "0.0.0.0/0" ]] ||
    die "Stack ApiPublicAccessCidr does not equal the exact current CloudShell CIDR."
  mapfile -t runtime_cidrs < <(jq -er '.cluster.resourcesVpcConfig.publicAccessCidrs[]' <<<"$cluster")
  assert_runtime_endpoint_values \
    "$(jq -r '.cluster.resourcesVpcConfig.endpointPrivateAccess' <<<"$cluster")" \
    "$(jq -r '.cluster.resourcesVpcConfig.endpointPublicAccess' <<<"$cluster")" \
    "$expected_cidr" \
    "${runtime_cidrs[@]}"
  assert_kubectl_minor_compatible \
    "$(kubectl version --client --output=json | jq -er '.clientVersion.gitVersion')" \
    "$(jq -er '.cluster.version' <<<"$cluster")"
  context="$(kubectl config current-context)"
  [[ "$context" == "$cluster_arn" ]] ||
    die "kubectl context must equal the exact common cluster ARN."
}

assert_exact_cleanup_rbac() {
  local namespace role role_binding cluster_role cluster_role_binding
  namespace="$(kubectl get namespace "$NAMESPACE" -o json)"
  role="$(kubectl get role udemy4-s4-cleanup-job -n "$NAMESPACE" -o json)"
  role_binding="$(kubectl get rolebinding udemy4-s4-cleanup-job -n "$NAMESPACE" -o json)"
  cluster_role="$(kubectl get clusterrole udemy4-c010-s4-cleanup-namespace -o json)"
  cluster_role_binding="$(kubectl get clusterrolebinding udemy4-c010-s4-cleanup-namespace -o json)"

  jq -e '
    .metadata.name == "udemy4-s4-logs"
    and .metadata.labels == {
      "course": "c010",
      "section": "s4",
      "managed-by": "udemy4",
      "kubernetes.io/metadata.name": "udemy4-s4-logs"
    }
  ' <<<"$namespace" >/dev/null ||
    die "Cleanup Namespace ownership labels are not exact."
  jq -e '
    .metadata.name == "udemy4-s4-cleanup-job"
    and .metadata.namespace == "udemy4-s4-logs"
    and (.rules | length) == 1
    and .rules[0].apiGroups == ["batch"]
    and .rules[0].resources == ["jobs"]
    and .rules[0].resourceNames == ["s4-log-generator"]
    and (.rules[0].verbs | sort) == ["delete", "get"]
  ' <<<"$role" >/dev/null ||
    die "Cleanup Job Role is not limited to the exact resourceName and verbs."
  jq -e '
    .metadata.name == "udemy4-s4-cleanup-job"
    and .metadata.namespace == "udemy4-s4-logs"
    and .roleRef == {
      "apiGroup": "rbac.authorization.k8s.io",
      "kind": "Role",
      "name": "udemy4-s4-cleanup-job"
    }
    and .subjects == [{
      "apiGroup": "rbac.authorization.k8s.io",
      "kind": "Group",
      "name": "udemy4:c010:s4-cleanup"
    }]
  ' <<<"$role_binding" >/dev/null ||
    die "Cleanup Job RoleBinding is not bound to the exact AccessEntry group."
  jq -e '
    .metadata.name == "udemy4-c010-s4-cleanup-namespace"
    and (.rules | length) == 1
    and .rules[0].apiGroups == [""]
    and .rules[0].resources == ["namespaces"]
    and .rules[0].resourceNames == ["udemy4-s4-logs"]
    and (.rules[0].verbs | sort) == ["delete", "get"]
  ' <<<"$cluster_role" >/dev/null ||
    die "Cleanup Namespace ClusterRole is not limited to the exact resourceName and verbs."
  jq -e '
    .metadata.name == "udemy4-c010-s4-cleanup-namespace"
    and .roleRef == {
      "apiGroup": "rbac.authorization.k8s.io",
      "kind": "ClusterRole",
      "name": "udemy4-c010-s4-cleanup-namespace"
    }
    and .subjects == [{
      "apiGroup": "rbac.authorization.k8s.io",
      "kind": "Group",
      "name": "udemy4:c010:s4-cleanup"
    }]
  ' <<<"$cluster_role_binding" >/dev/null ||
    die "Cleanup Namespace ClusterRoleBinding is not bound to the exact AccessEntry group."
}

apply_exact_cleanup_rbac() {
  [[ -n "${CLEANUP_RBAC_MANIFEST:-}" ]] ||
    die "Exact cleanup RBAC manifest is not bound to the common stack output."
  printf '%s\n' "$CLEANUP_RBAC_MANIFEST" | kubectl apply -f - >/dev/null
  assert_exact_cleanup_rbac
}

get_exact_job_pod_name() {
  local job pods count pod_name
  job="$(kubectl get job "$JOB_NAME" -n "$NAMESPACE" -o json)"
  pods="$(kubectl get pods -n "$NAMESPACE" -l "job-name=$JOB_NAME" -o json)"
  count="$(jq -r '.items | length' <<<"$pods")"
  [[ "$count" == "1" ]] ||
    die "Expected exactly one Pod selected by the exact Job label; found $count."
  pod_name="$(
    jq -er --arg name "$JOB_NAME" --arg uid "$(jq -r '.metadata.uid' <<<"$job")" '
      .items[0]
      | select(
          ([.metadata.ownerReferences[]? |
            select(.kind == "Job" and .name == $name and .uid == $uid and .controller == true)
          ] | length) == 1
        )
      | .metadata.name
    ' <<<"$pods"
  )" || die "The selected Pod is not owned by the exact runtime Job."
  printf '%s\n' "$pod_name"
}

assert_workload_log_rows() {
  local file="$1" pod_name="$2"
  jq -e --slurp --arg namespace "$NAMESPACE" --arg pod "$pod_name" '
    select(length == 6)
    | all(.[];
        (keys | sort) == (["level","message","namespace","pod","request_id","timestamp"] | sort)
        and .namespace == $namespace
        and .pod == $pod
        and ([.timestamp,.level,.message,.request_id] | all(type == "string" and length > 0))
      )
  ' "$file" >/dev/null ||
    die "Expected exactly six schema-valid workload rows bound to the runtime namespace and Pod."
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
  die "AWS check failed and was not an exact not-found result: $output"
}

path_is_inside() {
  local candidate root
  candidate="$(realpath -m "$1")"
  root="$(realpath -m "$2")"
  [[ "$candidate" == "$root" || "$candidate" == "$root/"* ]]
}

get_evidence_directory() {
  [[ -n "${EVIDENCE_DIR:-}" && "$EVIDENCE_DIR" == /* ]] ||
    die "Set EVIDENCE_DIR to an absolute directory outside the learner Git worktree."
  [[ -d "$EVIDENCE_DIR" ]] || die "EVIDENCE_DIR must already exist."
  [[ -n "${LEARNER_REPO:-}" && "$LEARNER_REPO" == /* && -d "$LEARNER_REPO" ]] ||
    die "Set LEARNER_REPO to the exact absolute learner Git worktree root."
  local exact_root
  exact_root="$(git -C "$LEARNER_REPO" rev-parse --show-toplevel 2>/dev/null)" ||
    die "LEARNER_REPO is not a Git worktree."
  [[ "$(realpath "$LEARNER_REPO")" == "$(realpath "$exact_root")" ]] ||
    die "LEARNER_REPO must equal the exact Git worktree root."
  ! path_is_inside "$EVIDENCE_DIR" "$exact_root" ||
    die "EVIDENCE_DIR must be outside the learner Git worktree."
  if git -C "$EVIDENCE_DIR" rev-parse --show-toplevel >/dev/null 2>&1; then
    die "EVIDENCE_DIR must not be inside any Git worktree."
  fi
  realpath "$EVIDENCE_DIR"
}

assert_exact_namespace_labels() {
  local object="$1" kind="$2"
  python3 - "$object" "$kind" "$NAMESPACE" <<'PY' ||
import json
import sys

obj = json.loads(sys.argv[1])
kind = sys.argv[2]
expected = {"course": "c010", "section": "s4", "managed-by": "udemy4"}
if kind == "Namespace":
    expected["kubernetes.io/metadata.name"] = sys.argv[3]
elif kind != "Job":
    raise SystemExit(1)
if obj.get("metadata", {}).get("labels") != expected:
    raise SystemExit(1)
PY
    die "$kind ownership label mismatch."
}

assert_exact_log_group_tags() {
  local tags="$1"
  [[ "$(jq -r 'keys | length' <<<"$tags")" == "4" &&
    "$(jq -r '.Course' <<<"$tags")" == "C010" &&
    "$(jq -r '.Section' <<<"$tags")" == "s4" &&
    "$(jq -r '.ManagedBy' <<<"$tags")" == "udemy4" &&
    "$(jq -r '.Purpose' <<<"$tags")" == "training" ]] ||
    die "Log group ownership tag mismatch."
}
