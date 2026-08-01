#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

evidence_dir="$(validate_s7_evidence_directory)"
private_log="$evidence_dir/status/preflight-private.log"
assert_s7_target >"$private_log" 2>&1 || {
  printf 'エラー: Section 7 の対象確認に失敗しました。Git管理外の非公開ログを確認してください。\n' >&2
  exit 1
}
chmod 600 "$private_log"

aws_json eks describe-cluster --region "$REGION" --name "$S7_CLUSTER_NAME" \
  >"$evidence_dir/raw/cluster.json" 2>>"$private_log" || {
  printf 'エラー: 共通クラスターの読み取りに失敗しました。Git管理外の非公開ログを確認してください。\n' >&2
  exit 1
}
jq -e --arg name "$S7_CLUSTER_NAME" \
  '.cluster.name == $name and .cluster.status == "ACTIVE"' \
  "$evidence_dir/raw/cluster.json" >/dev/null ||
  die "指定された共通 EKS クラスターが ACTIVE ではありません。"
chmod 600 "$evidence_dir/raw/cluster.json"
printf 'Section 7 の事前確認が完了しました: リージョン=%s、クラスター=ACTIVE。\n' "$REGION"
