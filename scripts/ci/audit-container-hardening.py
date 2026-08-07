#!/usr/bin/env python3
"""Produce an evidence-friendly container-hardening inventory from Helm output.

This is intentionally an audit tool, not an admission controller. It makes the
readOnlyRootFilesystem gap visible before the strict opt-in values file is
promoted, while preserving the existing Kyverno enforcement boundary.
"""

import argparse
import json
from pathlib import Path

import yaml


WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Rollout", "Job"}


def load_documents(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [document for document in yaml.safe_load_all(handle) if isinstance(document, dict)]


def pod_template(document):
    spec = document.get("spec") or {}
    if document.get("kind") in WORKLOAD_KINDS:
        return spec.get("template") or {}
    if document.get("kind") == "CronJob":
        return ((spec.get("jobTemplate") or {}).get("spec") or {}).get("template") or {}
    if document.get("kind") == "Pod":
        return document
    return None


def effective_run_as_non_root(pod_security_context, container_security_context):
    if "runAsNonRoot" in container_security_context:
        return container_security_context["runAsNonRoot"]
    return pod_security_context.get("runAsNonRoot")


def finding(workload, container_type, container, rule, message, severity):
    return {
        "kind": workload["kind"],
        "workload": workload["workload"],
        "namespace": workload["namespace"],
        "containerType": container_type,
        "container": container.get("name"),
        "rule": rule,
        "severity": severity,
        "message": message,
    }


def audit_document(document):
    template = pod_template(document)
    if template is None:
        return None, []

    metadata = document.get("metadata") or {}
    pod_spec = template.get("spec") or {}
    pod_security_context = pod_spec.get("securityContext") or {}
    workload = {
        "kind": document.get("kind"),
        "workload": metadata.get("name"),
        "namespace": metadata.get("namespace") or "techx-tf3",
        "containers": [],
    }
    findings = []

    for container_type in ("containers", "initContainers", "ephemeralContainers"):
        for container in pod_spec.get(container_type) or []:
            security_context = container.get("securityContext") or {}
            state = {
                "type": container_type,
                "name": container.get("name"),
                "image": container.get("image"),
                "runAsNonRoot": effective_run_as_non_root(pod_security_context, security_context),
                "allowPrivilegeEscalation": security_context.get("allowPrivilegeEscalation"),
                "readOnlyRootFilesystem": security_context.get("readOnlyRootFilesystem"),
            }
            workload["containers"].append(state)

            if state["runAsNonRoot"] is not True:
                findings.append(
                    finding(
                        workload,
                        container_type,
                        container,
                        "require-effective-non-root",
                        "runAsNonRoot is not effectively true",
                        "critical",
                    )
                )
            if state["allowPrivilegeEscalation"] is not False:
                findings.append(
                    finding(
                        workload,
                        container_type,
                        container,
                        "require-allow-privilege-escalation-false",
                        "allowPrivilegeEscalation is not false",
                        "high",
                    )
                )
            if state["readOnlyRootFilesystem"] is not True:
                findings.append(
                    finding(
                        workload,
                        container_type,
                        container,
                        "require-read-only-root-filesystem",
                        "readOnlyRootFilesystem is not true",
                        "medium",
                    )
                )

    return workload, findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rendered", required=True, help="Helm-rendered multi-document YAML")
    parser.add_argument("--output", required=True, help="Path for the JSON audit inventory")
    args = parser.parse_args()

    workloads = []
    findings = []
    for document in load_documents(args.rendered):
        workload, workload_findings = audit_document(document)
        if workload:
            workloads.append(workload)
            findings.extend(workload_findings)

    result = {
        "schemaVersion": 1,
        "controls": [
            "runAsNonRoot",
            "allowPrivilegeEscalation",
            "readOnlyRootFilesystem",
        ],
        "workloads": sorted(workloads, key=lambda item: (item["kind"], item["workload"] or "")),
        "findings": sorted(
            findings,
            key=lambda item: (item["severity"], item["kind"], item["workload"] or "", item["container"] or ""),
        ),
        "summary": {
            "workloadCount": len(workloads),
            "containerCount": sum(len(workload["containers"]) for workload in workloads),
            "findingCount": len(findings),
            "bySeverity": {
                severity: sum(1 for item in findings if item["severity"] == severity)
                for severity in ("critical", "high", "medium")
            },
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
