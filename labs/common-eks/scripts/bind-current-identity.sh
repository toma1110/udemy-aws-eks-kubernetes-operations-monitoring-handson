#!/usr/bin/env bash
set -euo pipefail
if ! SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"; then
  printf 'ERROR: Could not resolve the identity-binding script directory.\n' >&2
  return 1 2>/dev/null || exit 1
fi
# shellcheck source=common.sh
if ! source "$SCRIPT_DIR/common.sh"; then
  printf 'ERROR: Could not load the common EKS helpers.\n' >&2
  return 1 2>/dev/null || exit 1
fi

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  die "bind-current-identity.sh must be sourced so the current shell retains its exports."
  exit 1
fi

identity_root="$HOME/eks-monitoring-private/c010-s4"
expected_private_dir="$identity_root/current-run"
expected_identity_file="$expected_private_dir/current-sts-identity.json"
temporary_private_dir=""
discovery_file=""

cleanup_atomic_candidate() {
  if [[ -n "$temporary_private_dir" &&
    "$(realpath -m "$temporary_private_dir")" == "$(realpath -m "$identity_root")/.current-run.tmp."* ]]; then
    rm -f -- "$temporary_private_dir/current-sts-identity.json"
    rmdir -- "$temporary_private_dir" 2>/dev/null || true
  fi
  rmdir -- "$identity_root" 2>/dev/null || true
  rmdir -- "$HOME/eks-monitoring-private" 2>/dev/null || true
}

remove_discovery_file() {
  if [[ -n "$discovery_file" ]]; then
    rm -f -- "$discovery_file" || return 1
    discovery_file=""
  fi
}

cleanup_failed_discovery() {
  remove_discovery_file || true
  cleanup_atomic_candidate
}

prepare_discovery_file() {
  if ! discovery_file="$(
    umask 077
    mktemp "$HOME/eks-monitoring-private/.c010-s4-discovery.XXXXXX"
  )"; then
    cleanup_atomic_candidate
    return 1
  fi
  if ! chmod 600 "$discovery_file"; then
    cleanup_failed_discovery
    return 1
  fi
}

if ! expected_private_real="$(realpath -m "$expected_private_dir")" ||
  ! expected_identity_real="$(realpath -m "$expected_identity_file")"; then
  die "Could not resolve the deterministic current-run binding."
  return 1
fi
if [[ -n "${PRIVATE_EXECUTION_DIR:-}" ]] &&
  { ! supplied_private_real="$(realpath -m "$PRIVATE_EXECUTION_DIR")" ||
    [[ "$supplied_private_real" != "$expected_private_real" ]]; }; then
  die "PRIVATE_EXECUTION_DIR points outside the deterministic current-run binding."
  return 1
fi
if [[ -n "${CURRENT_STS_IDENTITY_FILE:-}" ]] &&
  { ! supplied_identity_real="$(realpath -m "$CURRENT_STS_IDENTITY_FILE")" ||
    [[ "$supplied_identity_real" != "$expected_identity_real" ]]; }; then
  die "CURRENT_STS_IDENTITY_FILE points outside the deterministic current-run binding."
  return 1
fi

if ! mkdir -p "$identity_root"; then
  die "Could not create the deterministic private identity root."
  return 1
fi
if ! prepare_discovery_file; then
  die "Could not create the private candidate-discovery file."
  return 1
fi
if find "$identity_root" -mindepth 2 -maxdepth 2 \
  -type f -name current-sts-identity.json -print0 >"$discovery_file"; then
  :
else
  discovery_status=$?
  cleanup_failed_discovery
  die "Could not enumerate retained current-run identity candidates."
  return "$discovery_status"
fi
if mapfile -d '' identity_candidates <"$discovery_file"; then
  :
else
  discovery_status=$?
  cleanup_failed_discovery
  die "Could not inspect retained current-run identity candidates."
  return "$discovery_status"
fi
if ! remove_discovery_file; then
  cleanup_atomic_candidate
  die "Could not remove the private candidate-discovery file."
  return 1
fi
if ((${#identity_candidates[@]} > 1)); then
  die "Multiple retained current-run identity candidates exist; refusing to choose or overwrite."
  return 1
fi
if ((${#identity_candidates[@]} == 1)); then
  if ! retained_identity_real="$(realpath "${identity_candidates[0]}")" ||
    [[ "$retained_identity_real" != "$expected_identity_real" ]]; then
    die "A retained identity exists at a foreign path."
    return 1
  fi
fi

if ! prepare_discovery_file; then
  die "Could not create the private retained-artifact discovery file."
  return 1
fi
if find "$identity_root" -mindepth 1 -maxdepth 2 -print0 >"$discovery_file"; then
  :
else
  discovery_status=$?
  cleanup_failed_discovery
  die "Could not enumerate retained private artifacts."
  return "$discovery_status"
fi
if mapfile -d '' retained_entries <"$discovery_file"; then
  :
else
  discovery_status=$?
  cleanup_failed_discovery
  die "Could not inspect retained private artifacts."
  return "$discovery_status"
fi
if ! remove_discovery_file; then
  cleanup_atomic_candidate
  die "Could not remove the private retained-artifact discovery file."
  return 1
fi
if ((${#identity_candidates[@]} == 0)); then
  if ((${#retained_entries[@]} != 0)); then
    die "Malformed or foreign retained private artifacts exist; refusing to create a second binding."
    return 1
  fi
  if ! temporary_private_dir="$(mktemp -d "$identity_root/.current-run.tmp.XXXXXX")"; then
    cleanup_atomic_candidate
    die "Could not create the private atomic identity candidate."
    return 1
  fi
  if ! chmod 700 "$temporary_private_dir"; then
    cleanup_atomic_candidate
    die "Could not protect the private atomic identity candidate."
    return 1
  fi
  if ! export PRIVATE_EXECUTION_DIR="$temporary_private_dir" ||
    ! export CURRENT_STS_IDENTITY_FILE="$temporary_private_dir/current-sts-identity.json"; then
    cleanup_atomic_candidate
    die "Could not export the private atomic identity candidate."
    return 1
  fi
  if ! record_current_sts_identity; then
    cleanup_atomic_candidate
    die "Current STS identity could not be validated and written atomically."
    return 1
  fi
  if ! prepare_discovery_file; then
    cleanup_atomic_candidate
    die "Could not create the private collision-discovery file."
    return 1
  fi
  if find "$identity_root" -mindepth 1 -maxdepth 1 \
    ! -path "$temporary_private_dir" -print0 >"$discovery_file"; then
    :
  else
    discovery_status=$?
    cleanup_failed_discovery
    die "Could not enumerate atomic installation collisions."
    return "$discovery_status"
  fi
  if mapfile -d '' collision_entries <"$discovery_file"; then
    :
  else
    discovery_status=$?
    cleanup_failed_discovery
    die "Could not inspect the atomic installation target."
    return "$discovery_status"
  fi
  if ! remove_discovery_file; then
    cleanup_atomic_candidate
    die "Could not remove the private collision-discovery file."
    return 1
  fi
  if ((${#collision_entries[@]} != 0)) || [[ -e "$expected_private_dir" ]]; then
    cleanup_atomic_candidate
    die "A retained binding appeared during atomic creation; it was not touched."
    return 1
  fi
  if ! mv -T -n -- "$temporary_private_dir" "$expected_private_dir" ||
    [[ -e "$temporary_private_dir" ]]; then
    cleanup_atomic_candidate
    die "Atomic current-run identity installation failed or collided."
    return 1
  fi
  temporary_private_dir=""
else
  if ((${#retained_entries[@]} != 2)); then
    die "The retained current-run binding contains an unexpected or orphan artifact."
    return 1
  fi
  if [[ ! -d "$expected_private_dir" || ! -f "$expected_identity_file" ]]; then
    die "The retained current-run binding shape is invalid."
    return 1
  fi
fi

if ! export PRIVATE_EXECUTION_DIR="$expected_private_dir" ||
  ! export CURRENT_STS_IDENTITY_FILE="$expected_identity_file"; then
  die "Could not export the deterministic current-run binding."
  return 1
fi
if ((${#identity_candidates[@]} == 1)); then
  if ! record_current_sts_identity; then
    die "The retained current-run identity could not be revalidated."
    return 1
  fi
fi
