#!/usr/bin/env bash
# shed_demo.sh <OUT_DIR> [USERS] [GIÂY]
#
# Demo YC#4 của directive #19: đẩy tải VƯỢT TRẦN rồi chứng minh hệ xuống mềm —
# browse bị shed, checkout/cart/product-detail vẫn được phục vụ, không sập.
#
# Chạy một lệnh ra đủ bộ evidence:
#   probe.txt      mã HTTP + header theo từng lớp route, bắn qua CloudFront công khai
#   counters.txt   counter Envoy trước/sau (rate_limited, enforced, ok)
#   frames/*.png   ảnh dashboard SLO trong lúc overload (time picker nằm trong ảnh)
#   timelapse.mp4  video ghép từ frames
#
# Vì sao probe đi qua CloudFront chứ không gọi thẳng pod: phải chứng minh cơ chế
# hoạt động trên ĐƯỜNG NGƯỜI DÙNG THẬT, không phải một đường tắt trong cluster.
#
# Vì sao đọc counter Envoy: 429 quan sát từ ngoài có thể do bất cứ tầng nào sinh
# ra. Counter `browse_rate_limiter.rate_limited` chứng minh chính local_ratelimit
# của Envoy đã chặn, và `local_rate_limiter.rate_limited: 0` chứng minh bucket bảo
# vệ luồng tiền KHÔNG hề chạm tới.
#
# Profile tải: `mandate19_locustfile.py` lấy nguyên từ cây nguồn load-generator —
# BrowseOverloadUser (weight 9) + ProtectedCheckoutUser (weight 1). Tỉ lệ 9:1 là
# chủ đích: chỉ khi browse áp đảo mới thấy được hệ hy sinh browse mà vẫn giữ đơn.
#
# Cần trước: tunnel EKS API + `kubectl -n techx-tf3 port-forward svc/grafana 23000:80`
set -uo pipefail
SP="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:?cần OUT_DIR}"; USERS="${2:-120}"; SECS="${3:-420}"
HOST=${HOST:-https://d2tn71186d7ilz.cloudfront.net}
NS=techx-tf3
mkdir -p "$OUT"; ABS="$(cd "$OUT" && pwd)"

# Phải lọc Running: dưới overload, HPA sinh pod mới mà Karpenter không cấp nổi node
# (NodePool limits) nên .items[0] rất dễ trúng một pod Pending -> port-forward chết.
proxy_pod() { kubectl -n $NS get pod -l app.kubernetes.io/name=frontend-proxy \
  --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}'; }

# Envoy là image distroless (không shell, không curl) nên đọc counter qua admin
# port bằng port-forward, không phải `kubectl exec`.
counters() {
  local pod; pod=$(proxy_pod)
  # Admin port của Envoy ở đây là 10000 (ENVOY_ADMIN_PORT), KHÔNG phải 9901 mặc định.
  # Dùng 9901 thì port-forward dựng được nhưng curl trả rỗng -> tưởng "không có counter".
  kubectl -n $NS port-forward "pod/$pod" 29901:"${ENVOY_ADMIN_PORT:-10000}" >/dev/null 2>&1 &
  local pf=$!; sleep 4
  curl -s --max-time 12 "http://localhost:29901/stats?filter=rate_limit" \
    || echo "  (không đọc được stats)"
  kill $pf 2>/dev/null
}

{
  echo "### counters TRƯỚC overload — $(date -u +%FT%TZ)"; counters
} > "$ABS/counters.txt" 2>&1

echo "[$(date -u +%H:%M:%SZ)] phóng overload: $USERS user, ${SECS}s, host=$HOST"
docker run --rm -d --name m19-shed -v "$ABS:/out" m19-bench \
  -f /bench/mandate19_locustfile.py --headless --host "$HOST" \
  -u "$USERS" -r "$USERS" -t "${SECS}s" --processes 4 \
  --csv /out/shed --html /out/shed.html >/dev/null

# Để tải dựng lên chạm trần trước khi probe, không thì probe bắt được lúc chưa shed.
sleep 45

{
  echo "### probe qua CloudFront — $(date -u +%FT%TZ)"
  echo "# Kỳ vọng: hai route browse có 429 + header x-techx-load-shed;"
  echo "# ba route protected KHÔNG có 429 nào."
  for spec in "GET:/:browse(shedable)" \
              "GET:/api/products:browse(shedable)" \
              "GET:/api/products/OLJCESPC7Z:product_detail(protected)" \
              "GET:/api/cart:cart(protected)" \
              "POST:/api/checkout:checkout(protected)"; do
    m="${spec%%:*}"; rest="${spec#*:}"; p="${rest%%:*}"; label="${rest#*:}"
    codes=""; shed=""
    for _ in $(seq 1 8); do
      resp=$(curl -s -o /dev/null -D - -X "$m" "$HOST$p" 2>/dev/null)
      codes="$codes $(printf '%s' "$resp" | awk 'NR==1{print $2}')"
      printf '%s' "$resp" | grep -qi "x-techx-load-shed" && shed="yes"
    done
    printf "%-46s codes=%s  load-shed-header=%s\n" "$m $p [$label]" "$codes" "${shed:-no}"
  done
} > "$ABS/probe.txt" 2>&1

# Quay dashboard trong phần còn lại của cửa sổ overload.
REMAIN=$(( SECS - 60 )); [ $REMAIN -lt 60 ] && REMAIN=60
bash "$SP/timelapse.sh" "$ABS" "$REMAIN" 15 "${GRAFANA_PORT:-23000}"

docker stop m19-shed >/dev/null 2>&1
{
  echo; echo "### counters SAU overload — $(date -u +%FT%TZ)"; counters
} >> "$ABS/counters.txt" 2>&1

echo "xong -> $ABS"
cat "$ABS/probe.txt"
