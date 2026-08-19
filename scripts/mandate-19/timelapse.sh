#!/usr/bin/env bash
# timelapse.sh <OUT_DIR> <TỔNG_GIÂY> [GIÂY_MỖI_FRAME] [PORT_GRAFANA]
#
# Chụp dashboard SLO theo chu kỳ rồi ghép thành GIF — dùng làm video demo
# "vượt trần -> xuống mềm". Mỗi frame là một ảnh thật có time picker trong ảnh,
# nên tua lại được và không thể dựng khống.
#
# Vì sao không dùng screen-record: extension Chrome chỉ ghi frame từ hành động
# tương tác (click/navigate), không ghi từ screenshot, nên GIF trả về 0 frame.
# Headless Chromium chủ động hơn và chạy được không cần UI.
#
# Cần trước: `kubectl -n techx-tf3 port-forward svc/grafana 23000:80`
set -uo pipefail
OUT="${1:?cần OUT_DIR}"; TOTAL="${2:?cần TỔNG_GIÂY}"
EVERY="${3:-15}"; PORT="${4:-23000}"
mkdir -p "$OUT/frames"
ABS="$(cd "$OUT" && pwd)"
N=$(( TOTAL / EVERY ))

echo "[$(date -u +%H:%M:%SZ)] timelapse: $N frame, mỗi ${EVERY}s, tổng ${TOTAL}s -> $ABS/frames"
for i in $(seq -w 1 "$N"); do
  # Cửa sổ 15 phút trượt: thấy được cả trước và trong lúc overload.
  docker run --rm --network host --user 0 -v "$ABS/frames:/out" \
    --entrypoint chromium-browser zenika/alpine-chrome \
    --headless --no-sandbox --disable-gpu --disable-dev-shm-usage --hide-scrollbars \
    `# 1920x2200 để MỘT frame chứa trọn dashboard: 4 gauge SLO + 3 hàng trend` \
    `# (browse/cart/checkout) + Error Budget + panel Node count. Khung hẹp hơn sẽ` \
    `# cắt mất Node count — mà đó là bằng chứng "không thêm node".` \
    --window-size=1920,2200 --virtual-time-budget=20000 \
    --screenshot="/out/f$i.png" \
    "http://localhost:$PORT/d/tf3-slo-v1/tf3-slo-dashboard?from=now-15m&to=now&kiosk" \
    >/dev/null 2>&1
  printf "  f%s %s\n" "$i" "$(date -u +%H:%M:%SZ)"
  sleep "$EVERY"
done

# Xuất HAI bản. ffmpeg chạy trong container để không phụ thuộc máy host.
#
#  - MP4 là bản để mentor xem. Giữ nguyên 1920px nên đọc được số trên panel và
#    time picker; 1 frame ~ 1,5s để kịp đọc.
#  - GIF là bản dán vào báo cáo/PR (GitHub không phát MP4 inline). Buộc phải hạ
#    còn 1100px cho khỏi vài chục MB — ở kích thước đó chữ trong panel nhoè, nên
#    GIF chỉ dùng để thấy XU HƯỚNG; con số phải đọc từ MP4 hoặc frame PNG gốc.
echo "ghép MP4..."
docker run --rm -v "$ABS:/w" -w /w linuxserver/ffmpeg \
  -y -framerate 2/3 -pattern_type glob -i 'frames/f*.png' \
  -c:v libx264 -pix_fmt yuv420p -r 24 \
  -vf "scale=1920:-2:flags=lanczos,pad=ceil(iw/2)*2:ceil(ih/2)*2" \
  timelapse.mp4 >/dev/null 2>&1

echo "ghép GIF..."
docker run --rm -v "$ABS:/w" -w /w linuxserver/ffmpeg \
  -y -framerate 2 -pattern_type glob -i 'frames/f*.png' \
  -vf "scale=1100:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" \
  -loop 0 timelapse.gif >/dev/null 2>&1

for f in timelapse.mp4 timelapse.gif; do
  if [ -f "$ABS/$f" ]; then
    echo "  -> $f ($(stat -c%s "$ABS/$f") bytes, $N frame)"
  else
    echo "  -> ffmpeg thất bại với $f; frame PNG gốc vẫn còn ở $ABS/frames/" >&2
  fi
done
