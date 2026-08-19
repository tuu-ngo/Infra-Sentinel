#!/usr/bin/env bash
# capture_stage.sh <STAGE_DIR> [PORT]
#
# Chụp dashboard SLO cho ĐÚNG cửa sổ đo của một stage, đọc mốc thời gian từ
# <STAGE_DIR>/window.txt do run_stage_external.sh ghi ra.
#
# Vì sao không chụp tay: ảnh chụp tay là panel rolling `Last 1 hour`/`Last 24 hours`,
# nên giá trị của nó trộn các stage khác — đó chính là lỗi làm evidence cũ không
# dùng được để kết luận stage nào đạt/không đạt. Ở đây from/to được ghim vào
# [MEAS_END-WINDOW, MEAS_END], khớp chính xác cửa sổ mà sli.json đã đo.
#
# Cần trước: `kubectl -n techx-tf3 port-forward svc/grafana 23000:80`
# Grafana không có renderer plugin (đã kiểm: /render trả 500), nên dùng headless
# Chromium trong Docker.
set -uo pipefail
DIR="${1:?cần STAGE_DIR}"
PORT="${2:-23000}"
UID_DASH="tf3-slo-v1"

[ -f "$DIR/window.txt" ] || { echo "thiếu $DIR/window.txt" >&2; exit 1; }
# shellcheck disable=SC2046
eval $(tr ' ' '\n' < "$DIR/window.txt" | grep -E '^(MEAS_END|WINDOW)=' | sed 's/WINDOW=\([0-9]*\)s/WINDOW=\1/')

FROM_MS=$(( (MEAS_END - WINDOW) * 1000 ))
TO_MS=$(( MEAS_END * 1000 ))
ABS="$(cd "$DIR" && pwd)"

echo "  chụp $(basename "$ABS")  window=[$(date -u -d @$((MEAS_END-WINDOW)) +%H:%M:%SZ) .. $(date -u -d @$MEAS_END +%H:%M:%SZ)]"

docker run --rm --network host --user 0 -v "$ABS:/out" \
  --entrypoint chromium-browser zenika/alpine-chrome \
  --headless --no-sandbox --disable-gpu --disable-dev-shm-usage --hide-scrollbars \
  --window-size=1920,2200 --virtual-time-budget=30000 \
  --screenshot=/out/grafana-slo.png \
  "http://localhost:$PORT/d/$UID_DASH/tf3-slo-dashboard?from=$FROM_MS&to=$TO_MS&kiosk" \
  > "$ABS/capture.log" 2>&1

if [ -f "$ABS/grafana-slo.png" ]; then
  echo "     -> grafana-slo.png ($(stat -c%s "$ABS/grafana-slo.png") bytes)"
else
  echo "     -> THẤT BẠI, xem $ABS/capture.log" >&2
fi
