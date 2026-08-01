#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

evidence_dir="$(validate_s7_evidence_directory)"
[[ "$evidence_dir" == "$PRIVATE_EXECUTION_DIR/s7-observations/observations-$S7_RUN_ID" ]] ||
  die "Section 7 の保存先が今回の実行と一致しないため、削除を中止しました。"
[[ "${S7_EVIDENCE_ROOT:-}" == "$PRIVATE_EXECUTION_DIR/s7-observations" ]] ||
  die "Section 7 の親保存先が指定された Git管理外のパスと一致しません。"
[[ -d "$S7_EVIDENCE_ROOT" && ! -L "$S7_EVIDENCE_ROOT" ]] ||
  die "Section 7 の親保存先がないか、安全に使用できません。"
[[ "$(realpath "$S7_EVIDENCE_ROOT")" == "$(realpath "$PRIVATE_EXECUTION_DIR")/s7-observations" ]] ||
  die "Section 7 の親保存先が指定された Git管理外の非公開領域から外れています。"
mapfile -d '' s7_entries < <(
  find "$S7_EVIDENCE_ROOT" -mindepth 1 -maxdepth 1 -print0
)
((${#s7_entries[@]} == 1)) ||
  die "Section 7 の親保存先に不明なファイルまたは保存先があります。何も削除しません。"
[[ "$(realpath "${s7_entries[0]}")" == "$evidence_dir" ]] ||
  die "Section 7 の親保存先に別の観察記録があります。何も削除しません。"

rm -rf -- "$evidence_dir"
[[ ! -e "$evidence_dir" ]] || die "Section 7 の今回の観察記録を削除できませんでした。"
mapfile -d '' remaining_s7_entries < <(
  find "$S7_EVIDENCE_ROOT" -mindepth 1 -maxdepth 1 -print0
)
((${#remaining_s7_entries[@]} == 0)) ||
  die "今回の観察記録を削除した後も Section 7 の親保存先が空になっていません。"
rmdir -- "$S7_EVIDENCE_ROOT"
[[ ! -e "$S7_EVIDENCE_ROOT" ]] ||
  die "空になった Section 7 の親保存先を削除できませんでした。"
[[ -f "$CURRENT_STS_IDENTITY_FILE" ]] ||
  die "Section 7 の削除後に残すべき共通の非公開 identity 記録がありません。"
printf 'Section 7 の観察記録と空の親保存先を削除しました。共通 cleanup 用の非公開 identity 記録は残しています。\n'
