#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  die "prepare-private-run.sh は source コマンドで読み込んでください。"
fi

# The shared binding keeps the sole current STS identity outside Git. Its detailed
# failure output can contain internal path information, so only the private log gets it.
IDENTITY_BINDING_LOG=""
if ! IDENTITY_BINDING_LOG="$(
  umask 077
  mktemp "$HOME/.s7-identity-binding-private.XXXXXX.log" 2>/dev/null
)"; then
  printf 'エラー: Git管理外の非公開ログを準備できませんでした。CloudShell の $HOME の空き容量と権限を確認してください。\n' >&2
  return 1
fi
# shellcheck source=../../common-eks/scripts/bind-current-identity.sh
if ! source "$SCRIPT_DIR/../../common-eks/scripts/bind-current-identity.sh" 2>"$IDENTITY_BINDING_LOG"; then
  printf 'エラー: 現在の AWS identity を安全に確認できませんでした。CloudShell の $HOME にある Git管理外の非公開ログを確認し、保存先の重複や権限を解消してからやり直してください。\n' >&2
  return 1
fi
if ! rm -f -- "$IDENTITY_BINDING_LOG" 2>/dev/null; then
  printf 'エラー: 一時的な Git管理外の非公開ログを削除できませんでした。CloudShell の $HOME を確認してください。\n' >&2
  return 1
fi
unset IDENTITY_BINDING_LOG

export S7_EVIDENCE_ROOT="$PRIVATE_EXECUTION_DIR/s7-observations"
export S7_EVIDENCE_DIR="$S7_EVIDENCE_ROOT/observations-$S7_RUN_ID"
assert_s7_inputs

old_umask="$(umask)"
umask 077
if [[ -e "$S7_EVIDENCE_DIR" ]]; then
  umask "$old_umask"
  die "Section 7 の保存先がすでにあります。新しい S7_RUN_ID を指定してください。"
fi
mkdir -p -- "$S7_EVIDENCE_ROOT"
[[ -d "$S7_EVIDENCE_ROOT" && ! -L "$S7_EVIDENCE_ROOT" ]] || {
  umask "$old_umask"
  die "Section 7 の Git管理外の保存先を安全に使用できません。"
}
mkdir -- "$S7_EVIDENCE_DIR"
mkdir -- "$S7_EVIDENCE_DIR/raw" "$S7_EVIDENCE_DIR/status"
umask "$old_umask"
validate_s7_evidence_directory >/dev/null
printf 'Section 7 の Git管理外の保存先を準備しました: %s\n' "$S7_RUN_ID"
