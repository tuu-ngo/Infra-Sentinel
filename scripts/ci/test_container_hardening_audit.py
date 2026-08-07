import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / "scripts" / "ci" / "audit-container-hardening.py"


def test_audit_reports_each_required_control(tmp_path):
    rendered = tmp_path / "rendered.yaml"
    output = tmp_path / "inventory.json"
    rendered.write_text(
        """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hardened
spec:
  template:
    spec:
      containers:
        - name: app
          image: example/app@sha256:abc
          securityContext:
            runAsNonRoot: true
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gap
spec:
  template:
    spec:
      containers:
        - name: app
          image: example/gap@sha256:def
          securityContext:
            runAsNonRoot: false
            allowPrivilegeEscalation: true
""",
        encoding="utf-8",
    )

    subprocess.run(
        [sys.executable, str(AUDIT), "--rendered", str(rendered), "--output", str(output)],
        cwd=REPO,
        check=True,
    )

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["summary"] == {
        "workloadCount": 2,
        "containerCount": 2,
        "findingCount": 3,
        "bySeverity": {"critical": 1, "high": 1, "medium": 1},
    }
    assert {finding["rule"] for finding in data["findings"]} == {
        "require-effective-non-root",
        "require-allow-privilege-escalation-false",
        "require-read-only-root-filesystem",
    }
