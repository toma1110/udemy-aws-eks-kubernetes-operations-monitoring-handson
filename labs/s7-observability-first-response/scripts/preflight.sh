#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

evidence_dir="$(validate_s7_evidence_directory)"
private_log="$evidence_dir/status/preflight-private.log"
assert_s7_target >"$private_log" 2>&1 || {
  printf 'ERROR: Section 7 target validation failed. Inspect the private preflight log.\n' >&2
  exit 1
}
chmod 600 "$private_log"

aws_json eks describe-cluster --region "$REGION" --name "$S7_CLUSTER_NAME" \
  >"$evidence_dir/raw/cluster.json" 2>>"$private_log" || {
  printf 'ERROR: Exact common cluster read failed. Inspect the private preflight log.\n' >&2
  exit 1
}
jq -e --arg name "$S7_CLUSTER_NAME" \
  '.cluster.name == $name and .cluster.status == "ACTIVE"' \
  "$evidence_dir/raw/cluster.json" >/dev/null ||
  die "The exact common EKS cluster is not ACTIVE."
chmod 600 "$evidence_dir/raw/cluster.json"
printf 'Section 7 preflight passed: Region=%s, cluster=ACTIVE.\n' "$REGION"
