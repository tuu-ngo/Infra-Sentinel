"""Contracts the external policy cannot break silently.

Two of the three assertions here describe the exact shape of the 2026-07-30
shopping-copilot gap. 233ecca widened the precondition so the image fell outside
this rule, but left its digest sitting in the allow-list, and never added it to
verify-first-party-signatures. The result was a policy that read as Enforce, a
catalogue entry nothing could ever match, and an image no rule judged.

Nothing in CI noticed, because the precondition and the allow-list were only
ever checked in isolation.
"""

import importlib.util
import re
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]
POLICY = REPO / "gitops" / "policies" / "kyverno" / "allow-approved-external-image-digests.yaml"
DRIFT_SCRIPT = REPO / "scripts" / "ci" / "check-external-image-allowlist-drift.py"

FIRST_PARTY_REPO = "197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp"
DIGEST = "sha256:" + "0" * 64

# One representative of every form that reaches admission today.
CLASSIFICATION_FIXTURES = [
    f"{FIRST_PARTY_REPO}@{DIGEST}",
    # Grafana: the subchart renders repo:<tag>@sha256:<digest> and cannot be
    # repinned from values, so both spellings have to land on the same side.
    f"{FIRST_PARTY_REPO}:1.2.3@{DIGEST}",
    f"197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/shopping-copilot@{DIGEST}",
    f"busybox@{DIGEST}",
    f"quay.io/prometheus/prometheus@{DIGEST}",
    "busybox:1.36",
]


def foreach_blocks():
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    blocks = policy["spec"]["rules"][0]["validate"]["foreach"]
    # containers, initContainers, ephemeralContainers - an image that only ever
    # appears in one of them must not get an easier ride than the others.
    assert len(blocks) == 3
    return blocks


def precondition_pattern(block) -> str:
    key = block["preconditions"]["all"][0]["key"]
    match = re.search(r"regex_match\('([^']+)'", key)
    assert match, f"precondition is no longer a regex_match call: {key}"
    return match.group(1)


def allow_list(block):
    return block["deny"]["conditions"]["any"][0]["value"]


def test_every_foreach_block_applies_the_same_rule():
    blocks = foreach_blocks()
    patterns = {precondition_pattern(block) for block in blocks}
    assert len(patterns) == 1, f"foreach blocks disagree on the precondition: {patterns}"
    lists = {tuple(allow_list(block)) for block in blocks}
    assert len(lists) == 1, "foreach blocks carry different allow-lists"


def test_precondition_never_excludes_a_catalogued_image():
    """A catalogued image that the precondition skips is a dead entry.

    The precondition selects first-party references and hands them to the
    signature policy; the deny below only sees what it did not select. So an
    allow-list entry matching the precondition can never be reached - it reads
    as approved while the image it names is judged by nothing.
    """
    for block in foreach_blocks():
        # Kyverno evaluates this with Go RE2. Every construct used here - [.],
        # (:[^@]+)?, [0-9a-f]{64} - means the same in both engines.
        pattern = re.compile(precondition_pattern(block))
        dead = [image for image in allow_list(block) if pattern.match(image)]
        assert not dead, (
            "these images are in the allow-list but excluded by the precondition, "
            f"so no rule judges them: {dead}"
        )


def test_drift_check_and_policy_classify_images_identically():
    """The gate has to agree with the rule it is protecting.

    The drift check keeps its own copy of the first-party pattern. When 233ecca
    changed the policy and not the script, the script kept demanding a catalogue
    entry for an image the policy had stopped judging - which is how CI went red
    on pull requests that had touched neither.
    """
    spec = importlib.util.spec_from_file_location("drift_check", DRIFT_SCRIPT)
    drift = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drift)

    pattern = re.compile(precondition_pattern(foreach_blocks()[0]))
    disagreements = [
        image
        for image in CLASSIFICATION_FIXTURES
        if bool(pattern.match(image)) != bool(drift.FIRST_PARTY.match(image))
    ]
    assert not disagreements, (
        "check-external-image-allowlist-drift.py and the ClusterPolicy sort these "
        f"images differently: {disagreements}"
    )
