#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 1 ]] || { printf 'Usage: bash capture-target-record.sh <Git-external-private-path>\n' >&2; exit 2; }
readonly OUTPUT_PATH="$1"
readonly REGION="ap-northeast-1"
readonly CLUSTER="eks-fargate-ops-lab"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ "${EXPECTED_AWS_ACCOUNT_ID:-}" =~ ^[0-9]{12}$ ]] || { printf 'STOP: EXPECTED_AWS_ACCOUNT_ID is required.\n' >&2; exit 1; }
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
[[ "$ACCOUNT_ID" == "$EXPECTED_AWS_ACCOUNT_ID" ]] || { printf 'STOP: wrong AWS account.\n' >&2; exit 1; }
aws cloudformation describe-stacks --region "$REGION" --stack-name "eksctl-${CLUSTER}-cluster" --output json >/dev/null 2>&1 || { printf 'STOP: exact ownership-tagged cluster stack is required; names alone are never sufficient.\n' >&2; exit 1; }
python "$SCRIPT_DIR/capture_target_record.py" "$OUTPUT_PATH" "$ACCOUNT_ID"
python "$SCRIPT_DIR/runtime_contract.py" validate-record --path "$OUTPUT_PATH" --expected-account "$ACCOUNT_ID" >/dev/null
printf 'PASS: private target record captured; do not add it to Git.\n'
