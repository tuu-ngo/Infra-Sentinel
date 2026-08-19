#!/usr/bin/env bash
# run_stage_external.sh <ARM> <USERS> <TỔNG_GIÂY> <CỬA_SỔ_ĐO_GIÂY>
#
# Chạy một stage với generator NGOÀI cluster (Docker, qua CloudFront), rồi đo SLI
# trên cửa sổ cuối của stage bằng Prometheus. Xem locustfile_external.py về lý do
# generator phải ở ngoài, và README.md về định nghĩa cổng SLO.
#
# Cần trước: tunnel EKS API + `kubectl -n techx-tf3 port-forward svc/prometheus 29090:9090`
set -uo pipefail
SP="$(cd "$(dirname "$0")" && pwd)"
ARM=$1; USERS=$2; DUR=$3; WIN=${4:-300}
NS=techx-tf3
HOST=${HOST:-https://d2tn71186d7ilz.cloudfront.net}
PROCS=${PROCS:-8}
OUT="${OUTDIR:-$SP/runs}/$ARM/u$USERS"; mkdir -p "$OUT"

SPAWN=$(( USERS / 10 )); [ $SPAWN -lt 1 ] && SPAWN=1

# Cửa sổ đo phải >= 5 phút. Span metrics của OTel collector aggregate thưa, nên
# rate() trên cửa sổ 1m trả rỗng/0 cho cart+checkout (đã đo: cart_success=None,
# frontend_total_rate=0 ở WIN=60 trong khi WIN=300 cho 112 rps). Đây cũng đúng
# protocol stage 5 phút, nên không có lý do dùng cửa sổ ngắn hơn.
if [ "$WIN" -lt 300 ]; then
  echo "LỖI: cửa sổ đo ${WIN}s < 300s -> SLI cart/checkout sẽ rỗng. Dùng >= 300." >&2
  exit 2
fi
if [ "$DUR" -le "$WIN" ]; then
  echo "LỖI: tổng thời lượng ${DUR}s phải > cửa sổ ${WIN}s để bỏ phần ramp." >&2
  exit 2
fi

echo "[$(date -u +%H:%M:%SZ)] ARM=$ARM users=$USERS dur=${DUR}s measure_window=${WIN}s host=$HOST"
T0=$(date +%s)

docker run --rm -v "$OUT:/out" m19-bench -f /bench/locustfile.py --headless \
  --host "$HOST" -u "$USERS" -r "$SPAWN" -t "${DUR}s" --processes "$PROCS" \
  --csv /out/locust --html /out/locust.html \
  > "$OUT/locust.log" 2>&1

T1=$(date +%s)
MEAS_END=$T1

# ── snapshot hạ tầng ────────────────────────────────────────────────────────────
# Generator ở NGOÀI cluster, nên toàn bộ node đều là hệ dưới đo (SUT). node_set_sha256
# phải giống nhau ở mọi stage của cả hai arm; khác đi là Karpenter đã thêm/bớt node
# và stage đó không dùng được cho claim requests-per-node.
{
  echo "### node_count";      kubectl get nodes --no-headers | wc -l
  echo "### node_set_sha256"; kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort | sha256sum
  echo "### nodes";           kubectl get nodes -L karpenter.sh/nodepool,node.kubernetes.io/instance-type --no-headers
  echo "### hpa";             kubectl -n $NS get hpa
  echo "### top_nodes";       kubectl top nodes
  echo "### restarts_oom";    kubectl -n $NS get pods --no-headers | awk '$4!="0"{print}'
  echo "### pending";         kubectl -n $NS get pods --field-selector=status.phase=Pending --no-headers
} > "$OUT/infra.txt" 2>&1

# ── locust aggregate (offered load; KHÔNG dùng làm SLI) ─────────────────────────
python3 - "$OUT" > "$OUT/locust_agg.json" <<'PY'
import csv,json,os,sys
o=sys.argv[1]; p=os.path.join(o,'locust_stats.csv'); r={}
if os.path.exists(p):
    for row in csv.DictReader(open(p)):
        if row['Name']=='Aggregated':
            r={'rps':float(row['Requests/s']),'requests':int(row['Request Count']),
               'failures':int(row['Failure Count']),'p95_client_ms':row.get('95%'),
               'p99_client_ms':row.get('99%')}
    r['failure_pct']=round(100*r['failures']/r['requests'],4) if r.get('requests') else None
json.dump(r,sys.stdout,indent=1)
PY

# ── SLI exact-window ───────────────────────────────────────────────────────────
cd "$SP" && PROM=${PROM:-http://localhost:29090} python3 sli_eval.py "$MEAS_END" "$((WIN/60))m" > "$OUT/sli.json" 2>&1
echo "T0=$T0 T1=$T1 MEAS_END=$MEAS_END WINDOW=${WIN}s" > "$OUT/window.txt"

python3 - "$OUT" <<'PY'
import json,os,sys,re
o=sys.argv[1]
d=json.load(open(os.path.join(o,'sli.json')))
la=json.load(open(os.path.join(o,'locust_agg.json')))
infra=open(os.path.join(o,'infra.txt')).read()
nc=re.search(r'### node_count\n\s*(\d+)',infra)
nh=re.search(r'### node_set_sha256\n\s*(\w{16})',infra)
nodes=int(nc.group(1)) if nc else 0
print(f"  verdict: {d['_verdict']}")
for k,v in d['_gates'].items():
    print(f"   {'OK  ' if v['pass'] else 'FAIL'} {k} = {v['value']}")
rps=d.get('frontend_total_rate') or 0
print(f"  offered(locust) {la.get('rps')} rps, {la.get('failures')}/{la.get('requests')} fail ({la.get('failure_pct')}%)")
print(f"  served frontend {round(rps,2)} rps · browse {round(d.get('browse_rate') or 0,2)} · checkout {round(d.get('checkout_rate') or 0,2)}")
print(f"  nodes={nodes} hash={nh.group(1) if nh else '?'} -> density {round(rps/nodes,2) if nodes else 'n/a'} rps/node")
print(f"  checkout p95/p99 (tham chiếu, KHÔNG phải cổng SLO): {round(d.get('checkout_p95') or 0,1)}/{round(d.get('checkout_p99') or 0,1)} ms")
PY
