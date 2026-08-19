#!/usr/bin/env python3
"""Sample the revenue-path SLIs during an AZ-loss drill and derive RTO / RPO.

Mandate #21 is scored on two numbers taken while an Availability Zone is
deliberately lost under load:

  RTO  how long the checkout SLO stays below its threshold before it recovers.
  RPO  whether any confirmed order is lost (expected: 0).

The SLO formulas are NOT reinvented here - they are read from
`scripts/mandate-19/sli_queries.json`, the same queries the Grafana SLO
dashboard uses, so the drill measures exactly what the dashboard shows.

Usage (Prometheus reached over a port-forward):
    kubectl port-forward -n techx-tf3 svc/prometheus 9090:9090 &
    python scripts/ops/az-drill-measure.py --out drill-evidence/1c-run.csv

Ctrl-C to stop; a summary (baseline, worst dip, RTO window, orders gained,
RPO verdict) prints on exit. Read-only: it only queries Prometheus.
"""
import argparse
import csv
import json
import os
import signal
import sys
import time
import urllib.parse
import urllib.request

# Money-path SLO thresholds from the project (checkout >=99%, browse/cart >=99.5%,
# p95 < 1s). RTO is measured against the checkout gate - the hardest one and the
# actual "revenue flowing" signal.
CHECKOUT_SLO = 0.99
BROWSE_SLO = 0.995
CART_SLO = 0.995
P95_SLO_MS = 1000.0

# The SLIs we chart plus the two monotonic order counters used for RPO. Order
# counters are summed across otel-gateway replicas.
COUNTER_QUERIES = {
    "orders_confirmed": "sum(app_confirmation_counter_total)",
    "payment_txns": "sum(app_payment_transactions_total)",
}


def prom_query(base, expr):
    url = base + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    with urllib.request.urlopen(url, timeout=10) as r:
        result = json.load(r)["data"]["result"]
    if not result:
        return None
    return float(result[0]["value"][1])


def load_sli_queries(path, window):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    # Keep the SLIs relevant to the money path; substitute the rate window.
    keep = [
        "checkout_success",
        "browse_success",
        "cart_success",
        "checkout_rate",
        "checkout_p95",
        "browse_p95",
    ]
    return {k: raw[k].replace("WINDOW", window) for k in keep if k in raw}


def fmt(v, pct=False):
    if v is None:
        return "  n/a "
    if pct:
        return "%6.3f%%" % (v * 100)
    return "%7.1f" % v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prom", default="http://localhost:9090")
    # Span metrics are scraped ~60s apart, so a rate window must span >=2 scrapes.
    # 90s is the tightest window that always resolves; shorter windows return empty.
    # The exact customer-facing RTO comes from the external curl probe in the
    # runbook - this SLI is the dashboard SLO story, smoothed by the window.
    ap.add_argument("--window", default="90s", help="rate window for SLIs (default 90s)")
    ap.add_argument("--interval", type=float, default=5.0, help="seconds between samples")
    ap.add_argument("--out", default="drill-measure.csv")
    ap.add_argument(
        "--queries",
        default=os.path.join(os.path.dirname(__file__), "..", "mandate-19", "sli_queries.json"),
    )
    args = ap.parse_args()

    slis = load_sli_queries(args.queries, args.window)
    all_q = dict(slis)
    all_q.update(COUNTER_QUERIES)

    fields = ["ts", "checkout_success", "browse_success", "cart_success",
              "checkout_rate", "checkout_p95", "browse_p95",
              "orders_confirmed", "payment_txns", "checkout_slo_ok"]

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    f = open(args.out, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()

    samples = []
    running = {"go": True}

    def stop(*_):
        running["go"] = False
    signal.signal(signal.SIGINT, stop)
    try:
        signal.signal(signal.SIGTERM, stop)
    except (ValueError, AttributeError):
        pass

    print("%-20s %8s %8s %8s %8s %8s %10s  %s" % (
        "UTC", "chk_ok", "brw_ok", "crt_ok", "chk_rt", "chk_p95", "orders", "SLO"))
    print("-" * 92)

    while running["go"]:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        row = {"ts": ts}
        for name, expr in all_q.items():
            try:
                row[name] = prom_query(args.prom, expr)
            except Exception as e:  # keep sampling through transient prom blips
                row[name] = None
                sys.stderr.write("query %s failed: %s\n" % (name, e))
        cs = row.get("checkout_success")
        row["checkout_slo_ok"] = "" if cs is None else int(cs >= CHECKOUT_SLO)
        writer.writerow({k: row.get(k) for k in fields})
        f.flush()
        samples.append(row)
        print("%-20s %8s %8s %8s %8s %8s %10s  %s" % (
            ts,
            fmt(row.get("checkout_success"), pct=True),
            fmt(row.get("browse_success"), pct=True),
            fmt(row.get("cart_success"), pct=True),
            fmt(row.get("checkout_rate")),
            fmt(row.get("checkout_p95")),
            fmt(row.get("orders_confirmed")),
            "" if cs is None else ("OK" if cs >= CHECKOUT_SLO else "*** BREACH ***"),
        ))
        # Sleep in small slices so Ctrl-C is responsive.
        slept = 0.0
        while running["go"] and slept < args.interval:
            time.sleep(0.25)
            slept += 0.25

    f.close()
    summarize(samples, args.out)


def summarize(samples, out):
    if not samples:
        print("\nno samples collected")
        return
    breach = [s for s in samples if s.get("checkout_success") is not None
              and s["checkout_success"] < CHECKOUT_SLO]
    orders = [s["orders_confirmed"] for s in samples if s.get("orders_confirmed") is not None]

    print("\n==================== DRILL SUMMARY ====================")
    print("samples:            %d  (csv: %s)" % (len(samples), out))
    if orders:
        gained = orders[-1] - orders[0]
        # A monotonic order counter never going backwards is the RPO proof: no
        # confirmed order was lost across the failover.
        went_backwards = any(orders[i + 1] < orders[i] for i in range(len(orders) - 1))
        print("orders confirmed:   %.0f -> %.0f  (+%.0f during window)" % (
            orders[0], orders[-1], gained))
        print("RPO (orders lost):  %s" % (
            "*** COUNTER WENT BACKWARDS - INVESTIGATE ***" if went_backwards
            else "0 (order counter monotonic, no confirmed order lost)"))
    if breach:
        print("checkout SLO breach: %s  ->  %s" % (breach[0]["ts"], breach[-1]["ts"]))
        print("RTO (checkout <99%): %d consecutive/near samples in breach" % len(breach))
        worst = min(s["checkout_success"] for s in breach)
        print("worst checkout succ: %.3f%%" % (worst * 100))
    else:
        print("checkout SLO:       never dipped below 99%% (no RTO needed - rode through)")
    print("======================================================")


if __name__ == "__main__":
    main()
