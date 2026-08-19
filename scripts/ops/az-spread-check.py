#!/usr/bin/env python3
"""Report how each workload's pods are spread across availability zones.

Mandate #21 asks for proof that nothing on the money path sits inside a single
AZ. Reading `kubectl get pods -o wide` by hand does not answer that, because the
node name does not say which zone it is in - so this joins pods to their node's
topology.kubernetes.io/zone label and flags anything concentrated in one zone.

Usage:
    kubectl get nodes -o json > /tmp/nodes.json
    kubectl get pods -n techx-tf3 -o json | python scripts/ops/az-spread-check.py /tmp/nodes.json

Reads pod JSON on stdin, node JSON from argv[1]. Read-only: it never talks to
the cluster itself, so it is safe to run with a read-only profile.
"""
import collections
import json
import sys

# browse -> cart -> checkout. A single-AZ placement here is a Mandate #21 failure,
# not merely untidy, so these are reported separately from everything else.
MONEY_PATH = {
    "frontend",
    "frontend-proxy",
    "cart",
    "checkout",
    "product-catalog",
    "payment",
    "shipping",
    "quote",
    "currency",
}

ZONES = ("ap-southeast-1a", "ap-southeast-1b", "ap-southeast-1c")


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: kubectl get pods -o json | %s <nodes.json>" % sys.argv[0])

    nodes = json.load(open(sys.argv[1], encoding="utf-8"))
    zone_of_node = {
        n["metadata"]["name"]: n["metadata"]["labels"].get(
            "topology.kubernetes.io/zone", "?"
        )
        for n in nodes["items"]
    }

    pods = json.load(sys.stdin)
    spread = collections.defaultdict(collections.Counter)
    for pod in pods["items"]:
        if pod.get("status", {}).get("phase") != "Running":
            continue
        labels = pod["metadata"].get("labels", {})
        # Components are the chart's unit of deployment; fall back to name for
        # workloads that arrived outside the chart (aiops, cloudflared, ...).
        name = labels.get("app.kubernetes.io/component") or labels.get(
            "app.kubernetes.io/name", "?"
        )
        spread[name][zone_of_node.get(pod["spec"].get("nodeName"), "?")] += 1

    def counts(name):
        per_zone = [spread[name].get(z, 0) for z in ZONES]
        return per_zone, sum(per_zone), sum(1 for c in per_zone if c)

    print("%-24s %3s %3s %3s %6s  %s" % ("WORKLOAD", "1a", "1b", "1c", "TOTAL", "VERDICT"))
    print("-" * 72)

    failures = 0
    for name in sorted(spread):
        if name not in MONEY_PATH:
            continue
        per_zone, total, zones_used = counts(name)
        if zones_used >= 2:
            verdict = "ok (%d AZs)" % zones_used
        else:
            verdict = "*** SINGLE-AZ SPOF ***"
            failures += 1
        print("%-24s %3d %3d %3d %6d  %s" % (name, *per_zone, total, verdict))

    others = []
    singles = []
    for name in sorted(spread):
        per_zone, total, zones_used = counts(name)
        if name not in MONEY_PATH and total > 1 and zones_used == 1:
            others.append((name, total))
        if total == 1:
            singles.append(name)

    if others:
        print("\nOff money path, multiple replicas but all in one AZ:")
        for name, total in others:
            print("  %-24s %d replicas" % (name, total))

    if singles:
        print("\nSingle-replica workloads (losing their AZ takes them down briefly):")
        print("  " + ", ".join(singles))

    print(
        "\n%d money-path workload(s) confined to a single AZ."
        % failures
    )
    # Non-zero exit makes this usable as a pre-drill gate in a pipeline.
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
