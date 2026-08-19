import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parents[2]
CHART = REPO / "phase3 - information" / "techx-corp-chart"
APPLICATION = REPO / "gitops" / "apps" / "techx-corp.yaml"
HPA = REPO / "gitops" / "infrastructure" / "hpa-hotpath.yaml"


def production_render() -> list[dict]:
    application = yaml.safe_load(APPLICATION.read_text(encoding="utf-8"))
    helm = application["spec"]["source"]["helm"]

    with tempfile.TemporaryDirectory() as tmpdir:
        chart_copy = Path(tmpdir) / CHART.name
        shutil.copytree(CHART, chart_copy)
        subprocess.run(
            ["helm", "dependency", "build", str(chart_copy)],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        )

        value_arguments: list[str] = []
        for value_file in helm["valueFiles"]:
            path = (
                chart_copy / value_file
                if value_file == "values.yaml"
                else (CHART / value_file).resolve()
            )
            value_arguments.extend(["-f", str(path)])

        parameter_arguments = [
            argument
            for parameter in helm["parameters"]
            for argument in ("--set", f"{parameter['name']}={parameter['value']}")
        ]
        result = subprocess.run(
            [
                "helm",
                "template",
                "techx-corp",
                str(chart_copy),
                "--namespace",
                "techx-tf3",
                *value_arguments,
                *parameter_arguments,
            ],
            cwd=REPO,
            check=True,
            capture_output=True,
            text=True,
        )
        return [
            document
            for document in yaml.safe_load_all(result.stdout)
            if document
        ]


def named_document(documents: list[dict], kind: str, name: str) -> dict:
    return next(
        document
        for document in documents
        if document.get("kind") == kind
        and (document.get("metadata") or {}).get("name") == name
    )


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is required")
def test_checkout_rollout_is_the_only_replica_owner():
    documents = production_render()
    deployment = named_document(documents, "Deployment", "checkout")
    rollout = named_document(documents, "Rollout", "checkout-rollout")

    assert "replicas" not in deployment["spec"]
    assert "replicas" not in rollout["spec"]
    assert rollout["spec"]["workloadRef"] == {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "name": "checkout",
        "scaleDown": "progressively",
    }

    hpa_documents = [
        document
        for document in yaml.safe_load_all(HPA.read_text(encoding="utf-8"))
        if document
    ]
    checkout_hpa = named_document(
        hpa_documents, "HorizontalPodAutoscaler", "checkout-hpa"
    )
    assert checkout_hpa["spec"]["scaleTargetRef"] == {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Rollout",
        "name": "checkout-rollout",
    }
    assert checkout_hpa["spec"]["minReplicas"] == 2
    # maxReplicas 8 -> 14 (Mandate-19 capacity step, 30/07/2026). Trọng tâm của test
    # này là "Rollout là chủ sở hữu replica duy nhất" — điều đó không đổi. Chỉ trần
    # replica thay đổi, theo số đo trên node-set cố định 9 node: checkout đứng ở 8/8
    # replica với 89%/65% tại stage vỡ 1400 user và 3.912/5.526 đơn trả 504, trong
    # khi CPU node cao nhất chỉ 60%. Xem docs/evidence/mandate-19/real-2026-07-30/.
    assert checkout_hpa["spec"]["maxReplicas"] == 14

    application = yaml.safe_load(APPLICATION.read_text(encoding="utf-8"))
    checkout_ignores = {
        (
            rule["group"],
            rule["kind"],
            rule["name"],
            rule["namespace"],
        ): rule["jsonPointers"]
        for rule in application["spec"]["ignoreDifferences"]
        if rule.get("name") in {"checkout", "checkout-rollout"}
    }
    assert checkout_ignores == {
        (
            "apps",
            "Deployment",
            "checkout",
            "techx-tf3",
        ): ["/spec/replicas"],
        (
            "argoproj.io",
            "Rollout",
            "checkout-rollout",
            "techx-tf3",
        ): ["/spec/replicas"],
    }
