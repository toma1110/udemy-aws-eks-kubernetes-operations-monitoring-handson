#!/usr/bin/env python3
"""Validate the deployable s5 lab contract without contacting AWS/Kubernetes."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
COMMON = ROOT.parent / "common-eks"
PREFIX = "udemy4-c010-s5-20260724"


def load_documents(path: Path) -> list[dict]:
    documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    if not documents or any(not isinstance(item, dict) for item in documents):
        raise ValueError(f"invalid YAML document: {path}")
    return documents


def validate() -> dict:
    manifests = sorted((ROOT / "manifests").glob("*.yaml"))
    if [p.name for p in manifests] != [
        "00-namespace.yaml",
        "10-pending-capacity.yaml",
        "20-crashloop-app.yaml",
        "30-crashloop-memory.yaml",
    ]:
        raise ValueError("manifest population mismatch")
    docs = [doc for path in manifests for doc in load_documents(path)]
    names = [doc["metadata"]["name"] for doc in docs]
    if any(not name.startswith(PREFIX) for name in names):
        raise ValueError("resource prefix mismatch")
    pods = [doc for doc in docs if doc["kind"] == "Pod"]
    if len(pods) != 3:
        raise ValueError("expected exactly three Pods")
    for pod in pods:
        spec = pod["spec"]
        if spec.get("activeDeadlineSeconds", 0) > 600:
            raise ValueError("unbounded Pod deadline")
        forbidden = {"hostNetwork", "hostPID", "hostIPC"}
        if forbidden.intersection(spec):
            raise ValueError("host access is forbidden")
        for container in spec["containers"]:
            security = container.get("securityContext", {})
            if security.get("privileged"):
                raise ValueError("privileged container is forbidden")
            resources = container.get("resources", {})
            if not resources.get("requests") or not resources.get("limits"):
                raise ValueError("requests and limits are required")
    shell_paths = sorted((ROOT / "scripts").glob("*.sh"))
    if [path.name for path in shell_paths] != [
        "apply-scenarios.sh",
        "capture-evidence.sh",
        "cleanup-section.sh",
        "common.sh",
    ]:
        raise ValueError("CloudShell Bash script population mismatch")
    scripts = "\n".join(path.read_text(encoding="utf-8") for path in shell_paths)
    dangerous = re.findall(r"kubectl[^\n]*(?:--all|\*)", scripts, re.IGNORECASE)
    if dangerous:
        raise ValueError("dangerous wildcard delete")
    if 'kubectl delete namespace "$NAMESPACE"' not in scripts:
        raise ValueError("exact section cleanup is missing")
    if scripts.count("assert_s5_target") < 4:
        raise ValueError("every external s5 script must enforce exact target binding")
    if list((ROOT / "scripts").glob("*.ps1")):
        raise ValueError("learner scripts must not require PowerShell")
    if not (COMMON / "template.yaml").is_file():
        raise ValueError("common EKS template is missing")
    return {
        "status": "pass",
        "manifest_count": len(manifests),
        "pod_count": len(pods),
        "resource_names": names,
        "namespace": PREFIX,
        "common_template": str((COMMON / "template.yaml").relative_to(ROOT.parent.parent)),
    }


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
