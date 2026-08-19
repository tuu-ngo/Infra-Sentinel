"""Guards against the failure that produced the shopping-copilot admission gap.

The allow-list drift check is only as good as the events that run it. On
2026-07-30 the check was correct and the policy was correct, but the workflow's
path filter listed none of the files the check reads, so the two commits that
opened the gap (9b774a6, 233ecca) merged green and the breakage appeared as an
admission denial in production instead.

A filter narrower than the step's inputs is worse than no filter: the job still
reports a green tick, so the gate looks alive while judging nothing.
"""

import importlib.util
import re
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "test-image-bump.yml"
DRIFT_SCRIPT = REPO / "scripts" / "ci" / "check-external-image-allowlist-drift.py"


def load_drift_module():
    """Import the check by path - its filename has hyphens, so no plain import."""
    spec = importlib.util.spec_from_file_location("drift_check", DRIFT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trigger_paths():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # "on" is parsed as the boolean True by YAML 1.1 unless the key is quoted;
    # this workflow quotes it, but accept both so a future unquoting does not
    # silently turn this test into a no-op.
    triggers = workflow.get("on", workflow.get(True))
    return triggers["pull_request"]["paths"]


def covers(pattern: str, target: Path) -> bool:
    """True when a GitHub path filter would match something under `target`."""
    relative = target.relative_to(REPO).as_posix()
    prefix = pattern[: -len("/**")] if pattern.endswith("/**") else pattern
    return relative == prefix or relative.startswith(prefix + "/")


def test_drift_gate_trigger_covers_its_inputs():
    drift = load_drift_module()
    inputs = {
        "chart": drift.DEFAULT_CHART,
        "values": drift.DEFAULT_VALUES,
        "policy": drift.DEFAULT_POLICY,
        "gitops": drift.DEFAULT_GITOPS,
    }
    paths = trigger_paths()

    uncovered = {
        name: path.relative_to(REPO).as_posix()
        for name, path in inputs.items()
        if not any(covers(pattern, path) for pattern in paths)
    }
    assert not uncovered, (
        "these inputs of check-external-image-allowlist-drift.py are not in the "
        f"pull_request path filter, so edits to them merge without the gate: {uncovered}"
    )


def test_drift_gate_trigger_covers_the_reviewed_catalogue():
    """The catalogue and the policy have to move together.

    test_pm127_policy_contract.py asserts they agree, but that assertion only
    runs when the job runs. Editing the catalogue alone has to be enough to
    trigger it.
    """
    catalogue = REPO / "docs" / "evidence" / "mandate-10" / "external-image-allowlist.yaml"
    assert catalogue.exists()
    assert any(covers(pattern, catalogue) for pattern in trigger_paths())


def test_drift_gate_step_still_runs_the_check():
    """The filter is pointless if the step it feeds is renamed away or dropped."""
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/ci/check-external-image-allowlist-drift.py" in body
    assert re.search(r"name:\s*Verify external images match the reviewed allow-list", body)
