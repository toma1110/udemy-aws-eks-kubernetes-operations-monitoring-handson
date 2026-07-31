#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  die "prepare-private-run.sh must be sourced."
fi

# The reviewed common binding creates or reuses the sole private current STS identity.
# shellcheck source=../../common-eks/scripts/bind-current-identity.sh
source "$SCRIPT_DIR/../../common-eks/scripts/bind-current-identity.sh"

export S7_EVIDENCE_ROOT="$PRIVATE_EXECUTION_DIR/s7-observations"
export S7_EVIDENCE_DIR="$S7_EVIDENCE_ROOT/observations-$S7_RUN_ID"
assert_s7_inputs

old_umask="$(umask)"
umask 077
if [[ -e "$S7_EVIDENCE_DIR" ]]; then
  umask "$old_umask"
  die "Section 7 run directory already exists; choose a new S7_RUN_ID."
fi
mkdir -p -- "$S7_EVIDENCE_ROOT"
[[ -d "$S7_EVIDENCE_ROOT" && ! -L "$S7_EVIDENCE_ROOT" ]] || {
  umask "$old_umask"
  die "Section 7 evidence root is unsafe."
}
mkdir -- "$S7_EVIDENCE_DIR"
mkdir -- "$S7_EVIDENCE_DIR/raw" "$S7_EVIDENCE_DIR/status"
umask "$old_umask"
validate_s7_evidence_directory >/dev/null
printf 'Private Section 7 observation run prepared: %s\n' "$S7_RUN_ID"
