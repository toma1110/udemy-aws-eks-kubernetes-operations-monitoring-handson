#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

require_command jq
require_command python3
assert_s6_target
evidence_dir="$(validate_s6_evidence_directory)"

printf 'Preflight passed for read-only Section 6 observation in %s; private evidence: %s\n' \
  "$REGION" "$evidence_dir"
