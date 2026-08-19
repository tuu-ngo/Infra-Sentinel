# Mandate #19 — evidence đo thật, 30/07/2026 (4 arm)

Bộ này **thay thế** `docs/evidence/mandate-19/pm-152/` và `docs/evidence/mandate-19/after/`
làm nguồn số liệu cho Mandate #19. Lý do loại hai bộ cũ ở mục 5.

Tái lập: [`scripts/mandate-19/`](../../../../scripts/mandate-19/) — `README.md` ở đó có lệnh.

## 0. Bản đồ thư mục

| Đường dẫn | Nội dung |
|---|---|
| `baseline/` + `baseline-client-truth.json` | arm **baseline** — cấu hình production trước mọi tuning của mandate này |
| `tuned/` + `tuned-client-truth.json` | arm **tuned** — sau PR #649 (chỉ nới `maxReplicas`). **Không nâng được trần** |
| `tuned2/` + `tuned2-client-truth.json` | arm **tuned2** — sau PR #656 (nới nút thắt `email`). Checkout @1400 lên **98,18%** |
| `tuned3/` + `tuned3-client-truth.json` | arm **tuned3** — sau PR #660+#664 (client-side LB). Throughput @2400 **+29%**, checkout @1800 **99,18%** |
| `roundrobin-proof/` | bằng chứng phân bố tải: **353× → 3,7×** lệch |
| `ceiling-root-cause.txt` | vì sao trần bị chặn: 13 pod Pending, 4 node managed rảnh không dùng được |
| `shed-demo/` | demo YC#4: probe qua CloudFront + counter Envoy + **video MP4/GIF** + ảnh mốc |
| `tuned3-ceiling-video/` | video vùng trần của arm cuối |

Mỗi `u<N>/` có: `sli.json` (cổng SLO), `infra.txt` (node-set hash + HPA + top nodes),
`window.txt` (cửa sổ đo chính xác), `locust_stats.csv`, `locust_failures.csv`, `locust_agg.json`.

> ### ⚠️ Đọc con số RPS ở đâu
> **`*-client-truth.json`** là nguồn đúng cho throughput, không phải `sli.json`.
> `frontend_total_rate` trong `sli.json` đi qua span pipeline, mà `otel-gateway` **mất span
> dưới tải** (`dropped_items=8645/8365/10100` trong log 07:18–07:19). Mất mát đồng đều nên
> **tỉ lệ** trong `sli.json` vẫn dùng được; **con số tuyệt đối** thì không.
> Xem đầu file [`scripts/mandate-19/client_truth.py`](../../../../scripts/mandate-19/client_truth.py).

## 0b. Kết quả ba arm (client-side, cổng SLO của `SLO.md`)

| Users | baseline | tuned (#649) | tuned2 (#656) | tuned3 (#660+#664) |
|---:|---|---|---|---|
| **1000** | **PASS ← trần** | **PASS ← trần** | **PASS ← trần** | browse 98,58% |
| 1400 | checkout **29,21%** | checkout **36,62%** | checkout **98,18%** | checkout **99,55%** |
| 1800 | checkout **7,12%** · 298,2 RPS | — | — | checkout **99,18%** · **355,7 RPS** |
| 2400 | checkout **0,02%** · 342,4 RPS | — | — | checkout **88,59%** · **442,3 RPS** |

Đọc bảng này theo hai chiều:

- **Chiều tốt lên:** checkout ở 1800 user đi từ `7,12%` lên `99,18%`; throughput ở 2400 user
  tăng **+29%** (342,4 → 442,3 RPS) trên **cùng 9 node**.
- **Chiều chưa đạt:** `tuned3` dính ~1–2% lỗi browse ở mọi mức tải nên **không stage nào trên
  200 user qua được cả 4 cổng**. Đây là đánh đổi có thật của client-side LB, không phải lỗi
  triển khai — xem báo cáo §6.4.

Trần cuối cùng không còn nằm ở phần mềm: 13 pod Pending vì hot path bị `nodeSelector` giam vào
tầng elastic đã cạn, trong khi 4 node `t3.large` managed ngồi ở 18–58% CPU. Xem
`ceiling-root-cause.txt`.

## 1. Điều kiện đo

| Hạng mục | Giá trị |
|---|---|
| Ngày | 30/07/2026, 02:39Z – 03:45Z |
| Generator | **Ngoài cluster** (Docker, máy CDO01) qua CloudFront `d2tn71186d7ilz.cloudfront.net` |
| Profile | [`scripts/mandate-19/locustfile_external.py`](../../../../scripts/mandate-19/locustfile_external.py) — trọng số task khớp locustfile trong cluster (tổng 32) |
| Nguồn SLI | Prometheus, query lấy **từ chính** `slo-dashboard.json` |
| Cửa sổ đo | 5 phút cuối mỗi stage (stage dài 7 phút, bỏ 2 phút ramp) |
| Node-set | 9 node, hash `54755c311f1a64b9`, **không đổi** ở mọi stage 400–2400 |

Generator đặt ngoài cluster để nó không tranh CPU với hệ đang được đo và không kích
Karpenter. Độ trễ mạng thêm vào không làm sai kết quả vì cả 4 cổng SLO đo bằng span
**server-side**; số client-side của Locust chỉ dùng để ghi nhận offered load —
và để phát hiện lỗ hổng SLI ở mục 3.

CloudFront không cache (`/` trả `no-store`; `/api/*` đều `x-cache: Miss`), nên mọi
request đều tới Envoy.

## 2. Cổng SLO — theo `SLO.md`, không phải ngưỡng tự đặt

| SLI | Ngưỡng |
|---|---|
| Browse non-5xx | ≥ 99,5% |
| Browse p95 | < 1000 ms |
| Cart success | ≥ 99,5% |
| Checkout success | ≥ 99,0% |

`SLO.md` **không có ngưỡng latency nào cho checkout**. Các báo cáo #19 trước gate theo
`checkout p99 ≤ 300ms` và tuyên FAIL từ 350 user; đó là budget *server-side,
steady-state* do Mandate #16 tự đặt (`docs/mandate-16-checkout-latency-report.md:24`),
bị đem áp cho p99 *client-side* khi đang cố ý đẩy quá trần. `checkout_p95/p99` vẫn
được ghi lại ở đây để tham chiếu #16, nhưng không tham gia quyết định PASS/FAIL.

## 3. Kết quả

| Users | Verdict SLI | browse | browse p95 | Served RPS | Nodes | Density | **checkout THẬT (client)** |
|---:|---|---:|---:|---:|---:|---:|---:|
| 200 | FAIL¹ | 98,957% | 45,1 ms | 193,23 | 7 | 27,60 | 99,893% |
| 400 | PASS | 100% | 44,6 ms | 268,69 | 9 | 29,85 | 100% |
| 600 | PASS | 99,996% | 46,9 ms | 360,77 | 9 | 40,09 | 99,963% |
| 800 | PASS | 99,958% | 56,2 ms | 444,58 | 9 | 49,40 | 100% |
| **1000** | **PASS** | 99,934% | 88,3 ms | **531,06** | 9 | **59,01** | **99,891%** |
| 1400 | "PASS" | 99,726% | 118,5 ms | 601,15 | 9 | 66,79 | **29,207%** ← |
| 1800 | FAIL | 99,207% | 233,5 ms | 746,01 | 9 | 82,89 | **7,125%** |
| 2400 | FAIL | 80,984% | 745,9 ms | 916,69 | 9 | 101,85 | **0,023%** |

¹ 200 user FAIL **không do tải**: 80 lỗi 500 dồn trong 6 giây (02:41:22–02:41:28Z)
trùng lúc Karpenter consolidate bỏ node `ip-10-0-10-62`. Pod bị evict → kết nối gRPC
tới product-catalog đứt → `/api/products/<id>` trả 500 vì handler không có retry.
Ở cùng stage đó browse p95 chỉ 45 ms và không pod nào Pending — hệ gần như chưa tải.

### 3.1. Lỗ hổng SLI checkout — phát hiện quan trọng nhất

Cột "checkout THẬT" là tỉ lệ thành công client-side. So với cổng SLI:

| Users | SLI `checkout_success` báo | Thực tế người dùng | Lỗi chính |
|---:|---:|---:|---|
| 1400 | **100%** | 29,207% | 3.912/5.526 trả **504 Gateway Timeout** |
| 1800 | **100%** | 7,125% | 6.465/6.961 trả 504 |
| 2400 | **100%** | 0,023% | 8.875/8.877 trả 504 |

Nguyên nhân: query SLI đo trên `service_name="checkout"`,
`span_name="oteldemo.CheckoutService/PlaceOrder"` — **span nội bộ của service**.
Request bị timeout ở tầng trên không bao giờ tới checkout nên không sinh span đó,
vì vậy chúng vô hình với SLI. Kết quả: dashboard báo 100% trong khi gần như toàn bộ
đơn hàng thất bại. Đây là mù trên đúng luồng quan trọng nhất (`SLO.md`: "Checkout là
luồng quan trọng nhất (ra tiền)").

504 sinh ra khi latency checkout vượt **route timeout mặc định 15s của Envoy** —
khớp với `checkout_p95`/`checkout_p99` đo được ghim đúng 15000 ms, tức bucket
histogram cao nhất.

Đã sửa: panel SLO checkout (id 13/41/52) chuyển sang đo ở biên
(`service_name="frontend"`, `span_name="POST /api/checkout"`). Panel 40/42 giữ span
nội bộ và được đổi tên thành "nội bộ service" vì chúng để chẩn đoán, không phải SLI.
Khoá bằng `scripts/ci/test_mandate19_throughput_contract.py::test_checkout_slo_is_measured_at_the_user_facing_edge`.

> ⚠️ Ảnh `grafana-slo.png` trong bộ này chụp **trước** khi sửa panel, nên gauge
> "Checkout — Success Rate" vẫn hiện ~99,99% ở các stage mà thực tế checkout đã sập.
> Giữ nguyên có chủ đích: đó chính là bằng chứng của lỗ hổng.

### 3.2. Trần thật

> **Trần = 1000 user · 531,06 RPS served · 59,01 RPS/node trên 9 node cố định.**
> Stage vỡ = 1400 user, vỡ vì **checkout 504**, không vì browse.

## 4. Nút thắt

Ở cả trần và stage vỡ, nút thắt là **trần `maxReplicas`, không phải capacity node**:

| | frontend | checkout | frontend-proxy | product-catalog | CPU node cao nhất |
|---|---|---|---|---|---|
| @1000 (trần) | **112%/65% — 8/8** | 64% — 5/8 | 68% — 6/8 | 60% — 6/8 | 60% |
| @1400 (vỡ) | **128%/65% — 8/8** | **89%/65% — 8/8** | 70% — 7/8 | 65% — 6/8 | 60% |

`frontend` và `checkout` đứng ở `maxReplicas: 8` trong khi CPU node cao nhất chỉ 60%
và hai node gần rỗng (1%, 7%). HPA muốn thêm pod nhưng bị chặn bởi trần replica.

Vì vậy nâng trần không cần thêm node — chỉ cần nới trần replica để HPA dùng được phần
CPU node đang bỏ không. `hpa-hotpath.yaml` đã có annotation hẹn đúng bước này:
*"raise maxReplicas in a separately measured capacity step after the 65% target is
validated"*. Bộ evidence này **là** bước đo đó.

## 5. Vì sao loại evidence cũ

| Bộ | Vấn đề |
|---|---|
| `pm-152/` (before) | `nodes/before.json` mô tả 9 node `ip-10-0-16-17` trên `m5.large`/`m6i.large` với providerID hex tuần tự (`i-0a1b2c3d4e5f6a7b8`); `nodeSetHash` không tái tạo được từ tên node đã sort; `frontend_cpu.json` dùng pod `frontend-74b7f` (không phải format pod K8s); `traces/summary.json` dùng traceId `pm-152-trace-001`. Cluster thật là `t3.large`/`t3.medium`/`c6g.large` với tên đủ 4 octet + `.ap-southeast-1.compute.internal`. Con số `174.75 RPS @ 328 user` không có artifact thô nào chống lưng. |
| `pm-152/test_slo/*.jpg` | Ảnh chụp ở thời điểm tuỳ ý, có ảnh chụp ngay sau RESET (`325_user_locust.jpg` chỉ có ~30 request) → không phải sustained. `nodes.jpg` cho thấy node 9 → 10 → 11 trong run, tức đã vi phạm ràng buộc "không thêm node". |
| `after/` + `test_slo_after/` | Run 10,5 giờ nhưng stage chỉ 59 giây – 4 phút (chưa đủ 5 phút). Locust chạy một tiến trình xuyên nhiều stage không reset → percentile là số tích luỹ. Panel Grafana là rolling 1h/24h → không phải cửa sổ stage. Generator là `load-generator` với limit 1 core, đã tiêu 654–706m ở 300 user nên throttle ở tải cao. |

## 6. Cấu trúc

```
baseline-summary.json      tổng hợp máy đọc được, mọi stage
baseline/u<N>/
  sli.json                 SLI + verdict theo 4 cổng, exact window
  locust_agg.json          offered load
  locust_stats.csv          per-endpoint, gồm checkout req/fail
  locust_failures.csv       phân loại lỗi (504/500/503)
  infra.txt                node list + node_set_sha256, HPA, top nodes, restart/pending
  window.txt               T0/T1/MEAS_END để đối chiếu lại Prometheus
  grafana-slo.png          dashboard SLO chụp ĐÚNG cửa sổ stage (xem cảnh báo 3.1)
```
