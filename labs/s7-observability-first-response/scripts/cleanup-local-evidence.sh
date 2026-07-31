#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

evidence_dir="$(validate_s7_evidence_directory)"
[[ "$evidence_dir" == "$PRIVATE_EXECUTION_DIR/s7-observations/observations-$S7_RUN_ID" ]] ||
  die "Refusing to remove a non-exact Section 7 evidence directory."
[[ "${S7_EVIDENCE_ROOT:-}" == "$PRIVATE_EXECUTION_DIR/s7-observations" ]] ||
  die "Section 7 evidence root is not the exact governed path."
[[ -d "$S7_EVIDENCE_ROOT" && ! -L "$S7_EVIDENCE_ROOT" ]] ||
  die "Section 7 evidence root is missing or unsafe."
[[ "$(realpath "$S7_EVIDENCE_ROOT")" == "$(realpath "$PRIVATE_EXECUTION_DIR")/s7-observations" ]] ||
  die "Section 7 evidence root escaped the governed private directory."
mapfile -d '' s7_entries < <(
  find "$S7_EVIDENCE_ROOT" -mindepth 1 -maxdepth 1 -print0
)
((${#s7_entries[@]} == 1)) ||
  die "Section 7 evidence root contains an unexpected or orphan artifact."
[[ "$(realpath "${s7_entries[0]}")" == "$evidence_dir" ]] ||
  die "Section 7 evidence root contains a foreign run."

rm -rf -- "$evidence_dir"
[[ ! -e "$evidence_dir" ]] || die "Section 7 local evidence cleanup failed."
mapfile -d '' remaining_s7_entries < <(
  find "$S7_EVIDENCE_ROOT" -mindepth 1 -maxdepth 1 -print0
)
((${#remaining_s7_entries[@]} == 0)) ||
  die "Section 7 evidence root did not become empty after exact run cleanup."
rmdir -- "$S7_EVIDENCE_ROOT"
[[ ! -e "$S7_EVIDENCE_ROOT" ]] ||
  die "Empty Section 7 evidence root cleanup failed."
[[ -f "$CURRENT_STS_IDENTITY_FILE" ]] ||
  die "Governed common identity must remain after Section 7 cleanup."
printf 'Section 7 local evidence and its empty root were removed. Governed common identity remains for common cleanup.\n'
