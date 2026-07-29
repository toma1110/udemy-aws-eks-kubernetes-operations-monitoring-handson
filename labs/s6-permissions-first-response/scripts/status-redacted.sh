#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

evidence_dir="$(validate_s6_evidence_directory)"
assert_s6_common_target_redacted "$evidence_dir"
cluster_file="$evidence_dir/status/cluster-private.json"
nodes_file="$evidence_dir/status/nodes-private.json"
private_log="$evidence_dir/status/common-target-private.log"
if ! aws_json eks describe-cluster --region "$REGION" --name "$CLUSTER_NAME" \
  >"$cluster_file" 2>>"$private_log"; then
  printf 'ERROR: Redacted cluster status read failed. Inspect the private status log.\n' >&2
  exit 1
fi
if ! kubectl get nodes -o json >"$nodes_file" 2>>"$private_log"; then
  printf 'ERROR: Redacted Node status read failed. Inspect the private status log.\n' >&2
  exit 1
fi
chmod 600 "$cluster_file" "$nodes_file"
[[ "$(jq -r '.cluster.status' "$cluster_file")" == "ACTIVE" ]] ||
  die "Common EKS cluster is not ACTIVE."
ready_count="$(
  jq '[.items[] | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))] | length' \
    "$nodes_file"
)"
[[ "$ready_count" -ge 1 ]] ||
  die "No Ready Node was observed."
printf 'Common EKS status validated: Region=%s, cluster=ACTIVE, ReadyNodes=%s.\n' \
  "$REGION" "$ready_count"
