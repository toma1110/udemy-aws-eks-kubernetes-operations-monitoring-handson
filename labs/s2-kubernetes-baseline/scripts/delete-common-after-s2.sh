#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

assert_s2_target
namespace_result=""
if ! namespace_result="$(kubectl get namespace "$S2_NAMESPACE" -o json --ignore-not-found)"; then
  die "Section 2 namespace absence check failed. Common cleanup is blocked."
fi
[[ -z "$namespace_result" ]] ||
  die "Section 2 namespace remains. Run cleanup-section.sh before common cleanup."

# The common delete script sources its residual verifier in the same process.
bash "$SCRIPT_DIR/../../common-eks/scripts/delete.sh"
