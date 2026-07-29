#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  die "prepare-private-run.sh must be sourced so the governed common identity exports remain in the current shell."
  exit 1
fi

# The common script creates or reuses the sole governed identity binding and
# revalidates exact sorted Account/Arn/UserId bytes for retained bindings.
# shellcheck source=../../common-eks/scripts/bind-current-identity.sh
source "$SCRIPT_DIR/../../common-eks/scripts/bind-current-identity.sh"

export S6_OBSERVATION_ROOT="$PRIVATE_EXECUTION_DIR/s6-observations"
export S6_EVIDENCE_DIR="$S6_OBSERVATION_ROOT/observations-$S6_RUN_ID"
trap cleanup_s6_atomic_candidate EXIT INT TERM
create_s6_run_directory
trap - EXIT INT TERM
validate_s6_evidence_directory >/dev/null
printf 'Private Section observation run prepared: %s\n' "$S6_RUN_ID"
