"""Throughput + tỉ lệ thành công tính từ CSV Locust (client-side, không qua span pipeline).

VÌ SAO TỒN TẠI FILE NÀY — một lỗi phương pháp đã phải sửa giữa chừng.

Ban đầu tôi lấy `frontend_total_rate` (span metrics trong Prometheus) làm con số
"served RPS". Sai. otel-gateway MẤT span dưới tải:

    2026-07-30T07:18:01Z memorylimiter "Memory usage is above soft limit. Forcing a GC."
    2026-07-30T07:18:10Z queue_sender  "Exporting failed. Dropping data." dropped_items=8645
    2026-07-30T07:19:00Z queue_sender  "Exporting failed. Dropping data." dropped_items=8365
    2026-07-30T07:19:18Z queue_sender  "... larger than max 4194304"      dropped_items=10100

Phát hiện ra vì stage u800 của arm tuned2 báo throughput THẤP HƠN u600 (265 vs 362 rps)
trong khi Locust offered y hệt nhau (164,0 vs 164,4 rps ở arm trước). Đối chiếu từng
span_name thì mọi route giảm đúng CÙNG hệ số 1,688x — dấu hiệu mất mát đồng đều, không
phải hệ chậm đi.

Hệ quả và cách dùng:
  - TỈ LỆ (success rate) qua span vẫn dùng được, vì mất mát đồng đều thì tử/mẫu cùng co.
  - CON SỐ TUYỆT ĐỐI (RPS) qua span thì KHÔNG. Phải lấy từ Locust — đo tại người dùng,
    không đi qua pipeline nào.
Vì vậy: cổng SLO vẫn đọc từ Prometheus (đúng query của slo-dashboard.json), còn throughput
và tỉ lệ thành công đối chứng thì đọc từ đây.

Lưu ý khi đọc số: generator là closed-loop có think time (`wait_time = between(1,10)`),
nên offered RPS bị chặn bởi số user / think time chứ không bởi sức hệ. Do đó "trần" phải
đọc theo SỐ USER giữ được SLO; RPS là con số dẫn xuất đi kèm, không phải biến độc lập.
"""
import csv, json, os, sys

# Phân lớp route theo đúng cách Envoy phân lớp (xem envoy.tmpl.yaml):
# prefix /api/cart, /api/checkout, /api/products/ là protected; còn lại catch-all.
def is_protected(name):
    return name.startswith(('/api/cart', '/api/checkout', '/api/products/'))

# Browse SLI: các route người dùng coi là "duyệt hàng".
BROWSE = ('/', '/api/data/', '/api/recommendations', '/api/product-reviews/[id]',
          '/api/products/[id]', '/api/product-ask-ai-assistant/[id]')

def stage(d):
    tot = {'req': 0, 'fail': 0}
    per = {}
    for r in csv.DictReader(open(os.path.join(d, 'locust_stats.csv'))):
        n, rc, fc = r['Name'], int(r['Request Count']), int(r['Failure Count'])
        rps = float(r['Requests/s'])
        if n == 'Aggregated':
            tot = {'req': rc, 'fail': fc, 'rps': rps}
        else:
            per[n] = {'req': rc, 'fail': fc, 'rps': rps, 'p95': r['95%'], 'protected': is_protected(n)}
    n429 = 0
    fpath = os.path.join(d, 'locust_failures.csv')
    if os.path.exists(fpath):
        for r in csv.DictReader(open(fpath)):
            if '429' in r['Error']:
                n429 += int(r['Occurrences'])
    br = {'req': 0, 'fail': 0, 'rps': 0.0}
    ck = per.get('/api/checkout', {'req': 0, 'fail': 0, 'rps': 0.0})
    cart = {'req': 0, 'fail': 0}
    for n, v in per.items():
        if n in BROWSE:
            br['req'] += v['req']; br['fail'] += v['fail']; br['rps'] += v['rps']
        if n.startswith('/api/cart'):
            cart['req'] += v['req']; cart['fail'] += v['fail']
    ok = tot['req'] - tot['fail']
    return {
        'served_rps_client': round(tot['rps'] * ok / tot['req'], 2) if tot['req'] else 0,
        'offered_rps_client': round(tot['rps'], 2),
        'browse_success_pct': round(100 * (br['req'] - br['fail']) / br['req'], 3) if br['req'] else None,
        'cart_success_pct': round(100 * (cart['req'] - cart['fail']) / cart['req'], 3) if cart['req'] else None,
        'checkout_success_pct': round(100 * (ck['req'] - ck['fail']) / ck['req'], 3) if ck['req'] else None,
        'checkout_req': ck['req'],
        'shed_429': n429,
        'overall_fail_pct': round(100 * tot['fail'] / tot['req'], 3) if tot['req'] else None,
    }

if __name__ == '__main__':
    root = sys.argv[1]
    out = {}
    for u in sorted(os.listdir(root), key=lambda x: int(x[1:])):
        d = os.path.join(root, u)
        if os.path.isfile(os.path.join(d, 'locust_stats.csv')):
            out[u] = stage(d)
    print(json.dumps(out, indent=1))
