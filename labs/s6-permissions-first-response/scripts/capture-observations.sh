#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

assert_s6_target
evidence_dir="$(validate_s6_evidence_directory)"
raw_dir="$evidence_dir/raw"
status_dir="$evidence_dir/status"

[[ -z "$(find "$raw_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]] ||
  die "Run-specific raw directory is not empty; stale-file inclusion is rejected."
find "$status_dir" -mindepth 1 -maxdepth 1 -type f \
  ! -name 'common-target-private.log' \
  ! -name 'serviceaccount-private.log' \
  ! -name 'cluster-private.json' \
  ! -name 'nodes-private.json' \
  -print -quit |
  grep -q . &&
  die "Run-specific status directory contains unexpected stale files."

write_status() {
  local layer="$1" observed="$2" reason="$3"
  jq -n \
    --arg layer "$layer" \
    --argjson observed "$observed" \
    --arg reason "$reason" \
    '{layer:$layer,observed:$observed,reason:$reason}' \
    >"$status_dir/$layer.json"
  chmod 600 "$status_dir/$layer.json"
}

capture_optional_aws() {
  local layer="$1" output="$2"
  shift 2
  local error_file="$status_dir/.$layer.error"
  if aws_json "$@" >"$output" 2>"$error_file"; then
    rm -f -- "$error_file"
    chmod 600 "$output"
    write_status "$layer" true "observed"
    return 0
  fi
  local reason="read-failed"
  if grep -Eqi 'AccessDenied|UnauthorizedOperation|not authorized' "$error_file"; then
    reason="access-denied"
  elif grep -Eqi 'ExpiredToken|InvalidClientToken|UnrecognizedClient' "$error_file"; then
    reason="credential-invalid"
  fi
  rm -f -- "$error_file" "$output"
  write_status "$layer" false "$reason"
  return 1
}

required_kubectl() {
  local output="$1"
  shift
  local error_file="$status_dir/.kubernetes.error"
  if kubectl "$@" >"$output" 2>"$error_file"; then
    rm -f -- "$error_file"
    chmod 600 "$output"
    return 0
  fi
  mv -- "$error_file" "$status_dir/kubernetes-private-error.log"
  chmod 600 "$status_dir/kubernetes-private-error.log"
  printf 'ERROR: Required Kubernetes read failed. Inspect the private status log.\n' >&2
  return 1
}

required_kubectl "$raw_dir/serviceaccount.json" get serviceaccount \
  "$TARGET_SERVICE_ACCOUNT" -n "$TARGET_NAMESPACE" -o json
required_kubectl "$raw_dir/rolebindings.json" get rolebindings -A -o json
required_kubectl "$raw_dir/clusterrolebindings.json" get clusterrolebindings -o json
chmod 600 "$raw_dir/serviceaccount.json" "$raw_dir/rolebindings.json" \
  "$raw_dir/clusterrolebindings.json"
write_status "kubernetes_rbac" true "observed"

if capture_optional_aws \
  "eks_access_list" "$raw_dir/access-entries.json" \
  eks list-access-entries --region "$REGION" --cluster-name "$CLUSTER_NAME"; then
  access_total=0
  access_observed=0
  access_policies_observed=0
  access_denied=0
  access_failed=0
  while IFS= read -r principal_arn; do
    [[ -n "$principal_arn" ]] || continue
    access_total=$((access_total + 1))
    ordinal="$(printf '%s' "$principal_arn" | sha256sum | cut -c1-16)"
    if capture_optional_aws \
      "access_entry_$ordinal" "$raw_dir/access-entry-$ordinal.json" \
      eks describe-access-entry --region "$REGION" \
      --cluster-name "$CLUSTER_NAME" --principal-arn "$principal_arn"; then
      access_observed=$((access_observed + 1))
    else
      reason="$(jq -r '.reason' "$status_dir/access_entry_$ordinal.json")"
      if [[ "$reason" == "access-denied" ]]; then
        access_denied=$((access_denied + 1))
      else
        access_failed=$((access_failed + 1))
      fi
    fi
    if capture_optional_aws \
      "access_policies_$ordinal" "$raw_dir/access-policies-$ordinal.json" \
      eks list-associated-access-policies --region "$REGION" \
      --cluster-name "$CLUSTER_NAME" --principal-arn "$principal_arn"; then
      access_policies_observed=$((access_policies_observed + 1))
    else
      reason="$(jq -r '.reason' "$status_dir/access_policies_$ordinal.json")"
      if [[ "$reason" == "access-denied" ]]; then
        access_denied=$((access_denied + 1))
      else
        access_failed=$((access_failed + 1))
      fi
    fi
  done < <(jq -r '.accessEntries[]?' "$raw_dir/access-entries.json")
  jq -n \
    --argjson total "$access_total" \
    --argjson observed "$access_observed" \
    --argjson policies_observed "$access_policies_observed" \
    --argjson denied "$access_denied" \
    --argjson failed "$access_failed" \
    '{listed:true,entry_count:$total,described_count:$observed,
      policy_listed_count:$policies_observed,
      detail_access_denied_count:$denied,detail_read_failed_count:$failed,
      complete:($total == $observed and $total == $policies_observed)}' \
    >"$status_dir/eks_access_detail.json"
else
  jq -n \
    '{listed:false,entry_count:null,described_count:0,
      policy_listed_count:0,
      detail_access_denied_count:0,detail_read_failed_count:0,complete:false}' \
    >"$status_dir/eks_access_detail.json"
fi
chmod 600 "$status_dir/eks_access_detail.json"

if capture_optional_aws \
  "pod_identity_list" "$raw_dir/pod-identity-associations.json" \
  eks list-pod-identity-associations --region "$REGION" \
  --cluster-name "$CLUSTER_NAME"; then
  pod_total=0
  pod_observed=0
  pod_denied=0
  pod_failed=0
  while IFS= read -r association_id; do
    [[ -n "$association_id" ]] || continue
    pod_total=$((pod_total + 1))
    ordinal="$(printf '%s' "$association_id" | sha256sum | cut -c1-16)"
    if capture_optional_aws \
      "pod_identity_$ordinal" "$raw_dir/pod-identity-$ordinal.json" \
      eks describe-pod-identity-association --region "$REGION" \
      --cluster-name "$CLUSTER_NAME" --association-id "$association_id"; then
      pod_observed=$((pod_observed + 1))
    else
      reason="$(jq -r '.reason' "$status_dir/pod_identity_$ordinal.json")"
      if [[ "$reason" == "access-denied" ]]; then
        pod_denied=$((pod_denied + 1))
      else
        pod_failed=$((pod_failed + 1))
      fi
    fi
  done < <(jq -r '.associations[]?.associationId' "$raw_dir/pod-identity-associations.json")
  jq -n \
    --argjson total "$pod_total" \
    --argjson observed "$pod_observed" \
    --argjson denied "$pod_denied" \
    --argjson failed "$pod_failed" \
    '{listed:true,association_count:$total,described_count:$observed,
      detail_access_denied_count:$denied,detail_read_failed_count:$failed,
      complete:($total == $observed)}' \
    >"$status_dir/pod_identity_detail.json"
else
  jq -n \
    '{listed:false,association_count:null,described_count:0,
      detail_access_denied_count:0,detail_read_failed_count:0,complete:false}' \
    >"$status_dir/pod_identity_detail.json"
fi
chmod 600 "$status_dir/pod_identity_detail.json"

printf 'Read-only capture finished. Optional AWS layers may be not observed; run analyze.py for the redacted summary.\n'
