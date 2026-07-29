#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

evidence_dir="$(validate_s6_evidence_directory)"
[[ "$evidence_dir" == "$S6_OBSERVATION_ROOT/observations-$S6_RUN_ID" ]] ||
  die "Cleanup accepts only the exact validated run directory."
[[ ! -L "$evidence_dir" ]] ||
  die "Refusing to remove a symbolic link."
rm -rf -- "$evidence_dir"
[[ ! -e "$evidence_dir" ]] ||
  die "Run-specific local evidence directory remains."
rmdir -- "$S6_OBSERVATION_ROOT"
[[ -f "$CURRENT_STS_IDENTITY_FILE" ]] ||
  die "Governed common identity must remain until post-guard verification."
printf 'Run evidence removed. Private identity is preserved until common cleanup and final revalidation.\n'
