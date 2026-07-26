#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

assert_s2_target
assert_exact_s2_namespace "$(kubectl get namespace "$S2_NAMESPACE" -o json)"
evidence_dir="$(get_s2_evidence_directory)"
pods_json="$(kubectl get pods -n "$S2_NAMESPACE" \
  -l app.kubernetes.io/name=baseline-web,udemy4.example/lab=s2-baseline \
  -o json)"
jq -e --arg lab "$S2_LAB" '
  (.items | length) == 1
  and .items[0].metadata.labels["udemy4.example/lab"] == $lab
  and (.items[0].metadata.uid | type == "string" and length > 0)
  and ([.items[0].metadata.ownerReferences[]? | select(.controller == true)] | length) == 1
  and [.items[0].metadata.ownerReferences[]? | select(.controller == true)][0].kind == "ReplicaSet"
  and .items[0].status.phase == "Running"
  and any(.items[0].status.conditions[]?; .type == "Ready" and .status == "True")
  and (.items[0].status.containerStatuses | length) == 1
  and .items[0].status.containerStatuses[0].ready == true
' <<<"$pods_json" >/dev/null ||
  die "Expected exactly one owned baseline Pod in Running and Ready state."
pod_name="$(jq -er '.items[0].metadata.name' <<<"$pods_json")"
pod_uid="$(jq -er '.items[0].metadata.uid' <<<"$pods_json")"
replicaset_name="$(jq -er '[.items[0].metadata.ownerReferences[] | select(.controller == true)][0].name' <<<"$pods_json")"
replicaset_uid="$(jq -er '[.items[0].metadata.ownerReferences[] | select(.controller == true)][0].uid' <<<"$pods_json")"

replicaset_json="$(kubectl get replicaset "$replicaset_name" -n "$S2_NAMESPACE" -o json)"
jq -e --arg name "$replicaset_name" --arg uid "$replicaset_uid" '
  .metadata.name == $name
  and .metadata.uid == $uid
  and ([.metadata.ownerReferences[]? | select(.controller == true)] | length) == 1
  and [.metadata.ownerReferences[]? | select(.controller == true)][0].kind == "Deployment"
  and [.metadata.ownerReferences[]? | select(.controller == true)][0].name == "baseline-web"
' <<<"$replicaset_json" >/dev/null ||
  die "Pod ReplicaSet does not have the exact baseline-web Deployment controller."
deployment_uid="$(jq -er '[.metadata.ownerReferences[] | select(.controller == true)][0].uid' <<<"$replicaset_json")"

kubectl get nodes -o wide >"$evidence_dir/nodes.txt"
kubectl get namespaces >"$evidence_dir/namespaces.txt"
kubectl get pods -A -o wide >"$evidence_dir/pods-all-namespaces.txt"
deployment_json="$(kubectl get deployment baseline-web -n "$S2_NAMESPACE" -o json)"
jq -e --arg uid "$deployment_uid" --arg lab "$S2_LAB" '
  .metadata.name == "baseline-web"
  and .metadata.uid == $uid
  and .metadata.labels["udemy4.example/lab"] == $lab
  and .spec.replicas == 1
  and .status.readyReplicas == 1
  and .status.availableReplicas == 1
  and .status.observedGeneration == .metadata.generation
' <<<"$deployment_json" >/dev/null ||
  die "Expected one observed and available Deployment replica."
printf '%s\n' "$deployment_json" >"$evidence_dir/deployment.json"

kubectl get service baseline-web -n "$S2_NAMESPACE" -o yaml >"$evidence_dir/service.yaml"
endpoints_json="$(kubectl get endpoints baseline-web -n "$S2_NAMESPACE" -o json)"
jq -e --arg pod "$pod_name" --arg pod_uid "$pod_uid" '
  [.subsets[]?.addresses[]?] as $addresses
  | [.subsets[]?.notReadyAddresses[]?] as $not_ready
  | ($addresses | length) == 1
  and ($not_ready | length) == 0
  and $addresses[0].targetRef.kind == "Pod"
  and $addresses[0].targetRef.name == $pod
  and $addresses[0].targetRef.uid == $pod_uid
' <<<"$endpoints_json" >/dev/null ||
  die "Service must have exactly one ready endpoint bound to the accepted Pod."
printf '%s\n' "$endpoints_json" >"$evidence_dir/endpoints.json"

kubectl describe pod "$pod_name" -n "$S2_NAMESPACE" >"$evidence_dir/pod-describe.txt"
kubectl logs "$pod_name" -n "$S2_NAMESPACE" --tail=100 >"$evidence_dir/pod.log"
grep -Fqx 'baseline-started' "$evidence_dir/pod.log" ||
  die "Real Pod log is missing exact baseline-started marker."
grep -Fqx 'baseline-heartbeat' "$evidence_dir/pod.log" ||
  die "Real Pod log is missing exact baseline-heartbeat marker."
kubectl get events -n "$S2_NAMESPACE" --sort-by=.metadata.creationTimestamp >"$evidence_dir/events.txt"

identity="$(aws sts get-caller-identity --output json)"
account_hash="$(jq -r .Account <<<"$identity" | sha256sum | awk '{print $1}')"
principal_hash="$(jq -r .Arn <<<"$identity" | sha256sum | awk '{print $1}')"
endpoint_count="$(jq '[.subsets[]?.addresses[]?] | length' <<<"$endpoints_json")"
jq -n \
  --arg checked_at "$(date --iso-8601=seconds)" \
  --arg namespace "$S2_NAMESPACE" \
  --arg account_sha256 "$account_hash" \
  --arg principal_arn_sha256 "$principal_hash" \
  --arg common_foundation_commit "$S2_COMMON_FOUNDATION_COMMIT" \
  --arg common_foundation_tree_oid "$S2_COMMON_FOUNDATION_TREE" \
  --argjson endpoint_count "$endpoint_count" '
  {
    schema: "udemy-s2-live-verification-evidence-v1",
    section_id: "s2",
    checked_at: $checked_at,
    common_foundation_commit: $common_foundation_commit,
    common_foundation_tree_oid: $common_foundation_tree_oid,
    execution_environment: {
      kind: "AWS CloudShell Bash",
      region: "ap-northeast-1",
      identity_binding_redacted: true,
      account_sha256: $account_sha256,
      principal_arn_sha256: $principal_arn_sha256
    },
    section_observations: {
      namespace: $namespace,
      owned_pod_count: 1,
      pod_phase: "Running",
      pod_ready: true,
      deployment_ready_replicas: 1,
      service_endpoint_count: $endpoint_count,
      endpoint_bound_to_pod: true,
      log_contains_baseline_started: true,
      log_contains_baseline_heartbeat: true
    },
    cleanup: {
      section_namespace_absent: false,
      common_cleanup_verified: false
    },
    result: "pass"
  }
' >"$evidence_dir/live-verification-result.json"

(cd "$evidence_dir" && sha256sum deployment.json endpoints.json events.txt \
  live-verification-result.json namespaces.txt nodes.txt pod-describe.txt pod.log \
  pods-all-namespaces.txt service.yaml >SHA256SUMS)
printf 'Real AWS/CLI evidence captured. Inspect and redact before sharing; do not add raw evidence to Git.\n'
