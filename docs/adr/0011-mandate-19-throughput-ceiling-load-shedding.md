# ADR 0011 — Mandate #19: Trần thông lượng, mật độ và cơ chế load-shedding

**Trạng thái:** Đã chấp thuận · đo lại toàn bộ bằng thực nghiệm ngày 30/07/2026
**Nghiệm thu Directive:** YC#1 ✅ · YC#3 ✅ · YC#4 ✅ · **YC#2 một phần** (throughput +29% trên cùng node, nhưng cổng 4/4 chưa qua — xem §"Kết quả sau khi sửa đúng nguyên nhân")
**Ngày ra quyết định:** 23/07/2026 · **Đo lại và viết lại:** 30/07/2026
**Chủ sở hữu / người ký:** CDO01 — TF3
**Trụ liên quan:** Performance Efficiency · Cost Optimization · Reliability
**Báo cáo:** [Báo cáo trần thông lượng Mandate #19](../mandate-19-throughput-ceiling-report.md)
**Evidence:** [`docs/evidence/mandate-19/real-2026-07-30/`](../evidence/mandate-19/real-2026-07-30/)
**Harness tái lập:** [`scripts/mandate-19/`](../../scripts/mandate-19/)

## Bối cảnh

Directive #19 yêu cầu bốn việc:

1. Tìm breakpoint thật — trần RPS/đồng thời mà SLO còn giữ.
2. Nâng trần bằng hiệu suất, **không thêm node**; chứng minh requests-per-node tăng.
3. Tìm service bão hoà sớm nhất và nới nó.
4. Khi vượt trần thì xuống mềm (shed/rate-limit), ưu tiên checkout, không sập toàn bộ.

## Quyết định 0 — loại bộ evidence cũ, đo lại từ đầu

Bản ADR trước dựa trên `docs/evidence/mandate-19/pm-152/` và `.../after/`. Hai bộ đó
**không dùng được** và đã bị loại khỏi mọi kết luận:

| Vấn đề | Chi tiết |
|---|---|
| Node-set không cố định | Ảnh `nodes.jpg` của run before cho thấy node trôi **9 → 10 → 11** giữa bài. Directive đòi "không thêm node", nên mọi claim requests-per-node từ đó mất cơ sở. |
| Stage quá ngắn | Nhiều stage chỉ 59s–4 phút, dưới protocol 5 phút. |
| Cổng đánh giá sai | Tuyên FAIL bằng ngưỡng "checkout p99 ≤ 300ms". Ngưỡng đó **không có trong** [`SLO.md`](../../phase3%20-%20information/onboarding/SLO.md) — nó là budget server-side, steady-state của Mandate #16, bị áp lên p99 **client-side** trong lúc **cố ý** đẩy quá trần. Sai cả điểm đo lẫn chế độ tải. |
| Số không tái lập được | Trần "174,75 RPS @ 328 user" không có artifact thô đi kèm. |

Bộ mới đo bằng script, không bằng ảnh chụp màn hình: mỗi stage 7 phút, cửa sổ đo là
**300 giây cuối** (bỏ ramp), generator chạy **ngoài cluster** qua CloudFront để không
tranh CPU với hệ đang được đo, và snapshot node-set + hash ở mọi stage.

Cổng SLO dùng đúng bốn ngưỡng trong `SLO.md`, query lấy nguyên từ `slo-dashboard.json`:
browse ≥ 99,5% · browse p95 < 1s · cart ≥ 99,5% · checkout ≥ 99,0%.

## Quyết định 1 — throughput đọc từ client, không đọc từ span metrics

Giữa bài phát hiện `frontend_total_rate` (span metrics) **không dùng được làm số tuyệt đối**.
Stage 800 user của một arm báo throughput *thấp hơn* stage 600 user, trong khi Locust
offered giống hệt. Đối chiếu từng `span_name` thì mọi route giảm đúng **cùng hệ số 1,688×**.
Nguyên nhân nằm trong log `otel-gateway`:

```
07:18:01Z memorylimiter  "Memory usage is above soft limit. Forcing a GC."  cur_mem_mib=495
07:18:10Z queue_sender   "Exporting failed. Dropping data."                 dropped_items=8645
07:19:00Z queue_sender   "Exporting failed. Dropping data."                 dropped_items=8365
07:19:18Z queue_sender   "... larger than max 4194304"                      dropped_items=10100
```

Quyết định: **tỉ lệ** (success rate, latency) đọc từ Prometheus như cũ — mất mát đồng đều
thì tử/mẫu cùng co nên tỉ lệ còn đúng. **Con số tuyệt đối** (RPS) đọc từ CSV Locust, đo tại
người dùng, không qua pipeline nào (`scripts/mandate-19/client_truth.py`).

Kèm theo: generator là closed-loop có think time (`between(1,10)`), nên offered RPS bị chặn
bởi *số user / think time* chứ không bởi sức hệ. Vì vậy **trần phải đọc theo số user giữ được
SLO**; RPS là con số dẫn xuất báo cáo kèm, không phải biến độc lập.

## Quyết định 2 — trần thật

Đo trên node-set cố định, hash ghi trong `infra.txt` từng stage.

| Users | served RPS (client) | browse | cart | checkout | Verdict |
|---:|---:|---:|---:|---:|---|
| 600 | 121,7 | 99,632% | 100% | 99,96% | PASS |
| 800 | 164,1 | 99,977% | 99,991% | 100% | PASS |
| **1000** | **202,4** | **99,610%** | **100%** | **99,89%** | **PASS ← trần** |
| 1400 | 238,8 | 99,585% | 99,988% | **29,21%** | FAIL |
| 1800 | 298,2 | 99,019% | 99,991% | 7,12% | FAIL |
| 2400 | 342,4 | 84,763% | 99,982% | 0,02% | FAIL |

**Trần = 1000 user đồng thời / 202,4 RPS phục vụ.** Cao hơn ~3× con số 328 user mà bản
ADR cũ ghi. Điều gãy trước tiên **không phải browse mà là checkout** — rơi thẳng từ 99,89%
xuống 29,21% chỉ trong một nấc tải.

## Quyết định 3 — nút thắt: ba nguyên nhân, không phải một

### 3.1. `email` — bão hoà hàng đợi, không phải CPU

| Điểm đo (stage 1400 user) | p95 |
|---|---:|
| span **client** `POST` checkout → email | **15 000 ms** (= route timeout Envoy) |
| span **server** email | **391 ms** |

14,6 giây chênh lệch là **thời gian xếp hàng**, không phải xử lý — đúng loại bão hoà
directive gọi tên (*"không phải chậm, mà cạn: connection/queue depth"*).

`checkout` gọi `sendOrderConfirmation` **đồng bộ** (`src/checkout/main.go:473`) và không
đặt deadline riêng, nên hàng đợi email ăn trọn budget request → **504**. Ở stage vỡ:
**3 432 / 5 431 đơn hỏng = 82% toàn bộ lỗi client**.

Nguyên nhân sức chứa: email là Ruby/Sinatra trên Puma (MRI có GIL), **1 replica**, limit CPU
**100m = 0,1 core**, trong khi tải là 14,7 rps × 391 ms ≈ 5,8 request đồng thời.

**Nới:** HPA 2..8 @60% + request 25m→75m, limit 100m→**600m** (PR #656).

**Kết quả đo lại (arm `tuned2`, cùng stage 1400 user):**

| | baseline | tuned (#649) | tuned2 (#656) |
|---|---:|---:|---:|
| checkout thành công | 29,21% | 36,62% | **98,18%** |

Nút thắt này coi như đã xử: checkout thôi là thứ gãy trước tiên.

### 3.2. Kết nối bị ghim vào một pod — nguyên nhân khiến "thêm replica" vô dụng

Đây là phát hiện quan trọng nhất. `kubectl top pod` khi `product-catalog` ở **11 replica**:

```
xxhsp 353m · cw8nx 136m · pzcxg 11m · TÁM pod còn lại 1-2m
```

`product-reviews` y hệt: 313m / 254m / 85m / 4m.

Service ClusterIP trả về **một VIP**; gRPC giữ **một kết nối TCP dài hạn**; kube-proxy ghim
kết nối đó vào **một pod**. Pod do HPA sinh ra *sau* khi kết nối đã dựng thì **không bao giờ**
nhận traffic. HPA lại thấy CPU **trung bình 48%** nên ngừng scale, trong khi pod nóng chính
là pod làm vỡ deadline và sinh `HTTP 500` trên `/api/products/[id]`.

Đối chứng ngay trong cụm: `frontend` trải đều **123–138m**, vì hop `frontend-proxy → frontend`
đã đi qua `frontend-headless`. Pattern đúng đã có sẵn trong repo, chưa áp cho hop
`frontend → backend`.

**Nới:** Service headless + `round_robin` phía client (PR #660). Phải **cả hai vế** — headless
mà giữ `pick_first` thì vẫn ghim IP đầu; `round_robin` mà giữ ClusterIP thì DNS chỉ trả 1 VIP.

Sau khi checkout được xử ở §3.1, **đây trở thành ràng buộc kế tiếp**: ở arm `tuned2` stage
1400 user, checkout đã lên 98,18% nhưng browse tụt còn 96,47% — tức thứ gãy đã dịch từ luồng
tiền sang luồng duyệt hàng, đúng chỗ nút thắt này nằm.

### 3.3. Deadline gRPC 500ms là cò súng quá nhạy

Log frontend ở stage vỡ: `4 DEADLINE_EXCEEDED: Deadline exceeded after 0.500s`.
`product-catalog` p95 server-side chỉ **6,9 ms** — deadline không thấp so với trung vị, nó
quá sát **đuôi**. Không có retry nên timeout thành lỗi cứng: **311 × HTTP 500** +
**431 × HTTP 503** = 742 lỗi, đúng phần kéo browse xuống 99,06%.

Deadline tồn tại là đúng (REL-17-02: gRPC-js không có deadline mặc định, upstream treo sẽ
giữ mọi request browse). Chỉ chỉnh **ngưỡng** 500 → 1200 ms, vẫn fail-fast, vẫn chặn treo.

### 3.4. Right-size request theo cả hai chiều

| Service | Đo được | Hành động |
|---|---|---|
| `accounting` | throttle **86,1%** — consumer MSK duy nhất ghi đơn vào RDS | req 50m→150m, limit 200m→600m |
| `recommendation` | throttle 18,1%, nằm trong mẫu số SLI browse | req 100m→150m, limit 500m→700m |
| `ad` | dùng 17–21m nhưng giữ chỗ 100m, throttle 0% | req 100m→**30m** (trả chỗ) |

## Quyết định 4 — load-shedding

### Phân lớp route

| Route | Class | Khi vượt trần |
|---|---|---|
| `/api/checkout` | `checkout_protected` | không dùng browse bucket |
| `/api/cart` | `cart_protected` | không dùng browse bucket |
| `/api/products/<id>` | `product_detail_protected` | được bảo vệ — cart/checkout phải đọc product trước |
| `/` và catch-all | `browse_shedable` | chủ động trả `429` |

### Bằng chứng cơ chế chạy thật

Bắn overload qua **đúng đường public CloudFront**:

| Kiểm tra | Kết quả |
|---|---|
| `GET /api/products` | **7/8 → HTTP/2 429** kèm `x-techx-load-shed: browse` |
| Envoy `browse_rate_limiter` | `rate_limited: 19449` · `enforced: 19449` · `ok: 6221` |
| Bucket bảo vệ luồng tiền | `local_rate_limiter.rate_limited:` **0** |
| `/api/products/<id>`, `/api/cart` lúc overload | **200**, không 429 |

Trong ladder, ở stage 2400 user (2,4× trần): **3 641 × 429** trên route shedable,
**0 × 429** trên route protected.

**Đính chính:** runbook cũ đòi header `x-envoy-ratelimited: true`. Yêu cầu đó **bất khả thi**
— filter `local_ratelimit` không phát header đó (chỉ filter *global* ratelimit mới có). Bằng
chứng đúng là `x-techx-load-shed: browse`, và nó có thật.

### Hiệu chỉnh budget — sửa một regression do chính chúng tôi gây ra

Bucket là **per-replica**, nên budget tổng = `tokens_per_fill × số replica proxy`. PR #649 nới
proxy 8 → 12 để nâng trần, và vô tình nâng luôn budget shed 400 → 600:

| Arm | proxy max | shedable offered @2400 | 429 | browse @2400 | Hệ quả |
|---|---:|---:|---:|---:|---|
| baseline | 8 | 110,7 rps | **3 641** | **84,8%** | shed đúng, protected 0×429 |
| tuned | 12 | 112,8 rps | **0** | 95,4% | không shed → 1 713 × HTTP 500 |
| tuned2 | 12 | — | **0** | **63,4%** | không shed → browse sụp |

Dòng `tuned2` là bằng chứng rõ nhất: sau khi checkout được nới, tải dồn hết sang browse, và
vì lớp shed không còn kích hoạt nên browse rơi tự do xuống 63,4% — thấp hơn hẳn baseline
84,8% ở cùng mức tải. Nhiều replica hơn mà **mất** khả năng xuống mềm là ngược chiều YC#4.

Hiệu chỉnh `tokens_per_fill` 50 → **33** (12 × 33 = 396 ≈ 8 × 50 = 400), `max_tokens` 100 → 66.

**Hạn chế còn lại, không giấu:** budget vẫn trôi theo số replica. Sửa đúng về kiến trúc là
bucket dùng chung toàn cluster (`local_cluster_rate_limit` của Envoy) — nằm trong
`envoy.tmpl.yaml`, tức trong image, phải rebuild. Ghi nhận là việc còn mở.

## Điều đã thử và KHÔNG hiệu quả — ghi lại để không ai làm lại

Nới `maxReplicas` hot path (frontend 8→16, checkout 8→14, proxy 8→12, catalog 8→12) rồi đo
lại đủ 8 stage: **trần không đổi**, vẫn 1000 user; RPS ở trần 202,8 vs 202,4 — trong sai số.

Lý do ở §3.2: replica thêm vào là dung lượng **traffic không tới được**. Nới trần replica là
điều kiện cần, không phải điều kiện đủ; nó chỉ có giá trị sau khi đường đi của traffic được sửa.
Tệ hơn, một mình nó còn làm **yếu** lớp shed (§4).

## Kết quả sau khi sửa đúng nguyên nhân — arm `tuned3`

Phân bố đã sửa được thật (`kubectl top pod`, cùng mức tải 600 user):

| `product-catalog` | Trước | Sau |
|---|---|---|
| Phân bố CPU | `353m · 136m · 11m · **1m × 8**` | `55m · 31m · 20m · 15m` |
| Lệch nóng/lạnh | **353×** | **3,7×** |
| Pod nhận traffic | **2/11** | **4/4** |

Log frontend xác nhận `remote_addr=10.0.39.121:8080` — IP pod trực tiếp, không còn ClusterIP.

| Users | servedRPS base → tuned3 | checkout base → tuned3 | browse | 429 |
|---:|---|---|---:|---:|
| 1400 | 238,8 → **277,7** | 29,21% → **99,55%** | 97,390% | 0 |
| 1800 | 298,2 → **355,7** | 7,12% → **99,18%** | 97,325% | 30 |
| 2400 | 342,4 → **442,3** | 0,02% → **88,59%** | 95,872% | 186 |

**Ba cải thiện đo được:** checkout ở 1800 user `7,12% → 99,18%`; throughput ở 2400 user
**+29%** trên **cùng 9 node**; và lớp shed hoạt động trở lại (`tuned2` có **0 × 429** ở cùng
mức tải, `tuned3` có 30 và 186).

**Nhưng theo cổng 4/4 nghiêm ngặt, YC#2 CHƯA ĐẠT.** `browse` dính ~1–2% lỗi ở **mọi** mức tải,
kể cả 400 user, nên chỉ stage 200 user qua được cả bốn cổng.

Đây là một **đánh đổi có thật**, không phải lỗi triển khai: `pick_first` vô tình cung cấp
**cách ly** — mỗi frontend ghim vào một backend riêng, backend quá tải chỉ ảnh hưởng phần
frontend ghim vào nó. `round_robin` xoá cách ly để dùng hết dung lượng, nên khi backend chạm
trần thì **mọi** request cùng chịu. Đổi lại là +29% RPS.

Lỗi còn lại là `DEADLINE_EXCEEDED after 1.200s`, dồn thành burst ~8 giây **ngay trước** mỗi lần
HPA scale-up (09:22:27→35 rồi scale 09:22:56; 09:28:51→58 rồi scale 09:29:11) — độ trễ phản
ứng của HPA, giờ mới lộ ra vì tín hiệu CPU không còn bị pha loãng bởi 8 pod rỗng.

## Trần cuối cùng KHÔNG còn nằm ở phần mềm

Ở stage 2400 user: **13 pod Pending** (8 `frontend`, 2 `frontend-proxy`, 3 `product-catalog`).

```
0/9 nodes are available:
  4 node(s) didn't match Pod's node affinity/selector   <- 4 node t3.large managed
  1 Insufficient cpu                                    <- tầng elastic đã cạn
node limits have been exhausted for nodepool (flash-sale-spot-arm64)
label "techx.io/arch" does not have known values (typo of "kubernetes.io/arch"?)
```

CPU thật cùng lúc: node elastic `…5-127` **99%**, `…34-80` 62% — trong khi **bốn node
`t3.large` managed ở 18–58%**.

`values-mandate13.yaml` giam 10 workload hot path bằng
`nodeSelector: { techx.io/workload: elastic, techx.io/arch: arm64 }`. Bốn node managed không
mang label `techx.io/workload` nên **không bao giờ** nhận được pod hot-path.

> **Đòn bẩy tiếp theo, và nó đúng nghĩa "nâng trần bằng hiệu suất, không thêm node": 8 vCPU
> đã trả tiền đang nằm không.** Image đã multi-arch nên hot path chạy được trên `t3.large`.
> **Chưa làm** vì nó sửa thiết kế Mandate #13 của CDO01 (ghim Graviton để tiết kiệm chi phí) —
> cần thống nhất trước, không đơn phương.

## Khoảng trống quan sát phát hiện kèm (không chặn Mandate #19)

| Vấn đề | Chi tiết |
|---|---|
| cAdvisor chết 7/8 node | `Get "https://10.0.x.x:10250/metrics/cadvisor": context deadline exceeded`. Chỉ node chứa Prometheus có metric container. Panel *"Pod count — hot-path services"* vì thế luôn `No data` và **không được dùng làm bằng chứng**. Số per-pod trong ADR này lấy từ metrics-server (`kubectl top`), không từ Prometheus. |
| Karpenter không cấp thêm được node elastic | `node limits have been exhausted for nodepool (flash-sale-spot-arm64)`. Trần cứng tầng elastic arm64 = **4 node** (`flash-sale-spot-arm64` 2 + `elastic-ondemand-fallback-arm64` 2) — CDO01 đặt cố ý để giữ chi phí, **không phải lỗi cấu hình**. ⚠️ **Đính chính bản đầu:** ADR này từng ghi nguyên nhân là *"NodePool không khai báo `techx.io/arch` trong `requirements`"* — sai. Karpenter in lý do từ chối của *từng* NodePool rồi gộp một khối; dòng `label "techx.io/arch" does not have known values` thuộc về pool **amd64** (`flash-sale-spot`, `elastic-ondemand-fallback`), và với chúng đó là hành vi **đúng**. Hai pool arm64 đã có label ở `template.metadata.labels` (`spot-nodepool.yaml:88`, `ondemand-fallback-nodepool.yaml:92`); Karpenter đưa static label của template vào requirements của node sẽ tạo. Bằng chứng: node elastic `…5-127` chạy **99% CPU** tại đúng snapshot đó. |
| SLI checkout từng mù | Panel SLO đo trên span **nội bộ** service checkout, nên request timeout ở tầng trên vô hình: ở 2400 user, 8 875/8 877 đơn hỏng mà dashboard vẫn báo `checkout_success = 100%`. Đã chuyển sang đo ở **biên** frontend (PR #649). |

## Hệ quả

- Trần đã biết và tái lập được bằng lệnh, không bằng ảnh chụp.
- Ba nút thắt đã xác định bằng số đo, không bằng suy đoán; hai trong ba là **connection/queue**,
  không phải CPU — nên mọi phản xạ "thêm replica / thêm node" đều không chạm tới chúng.
- Cơ chế xuống mềm đã chứng minh chạy thật trên đường public, và đã hiệu chỉnh lại theo trần đo được.
- Ràng buộc "không thêm node" được tôn trọng: NodePool `limits` chặn cấp thêm; ở stage vượt trần
  có pod `Pending` với lý do `node limits have been exhausted` — đó là bằng chứng ràng buộc còn hiệu lực.

## Ràng buộc được giữ nguyên

- Không thay đổi flagd: `/flagservice` giữ nguyên trong Envoy, `values-flagd-sync.yaml` không bị đụng.
- Storefront public / cổng vận hành private tiếp tục theo Directive #1.
- Filter `envoy.filters.http.fault` (kênh BTC bơm sự cố) giữ nguyên.

## Việc còn mở

1. Bucket shed dùng chung toàn cluster (`local_cluster_rate_limit`) — cần rebuild image proxy.
2. Sửa cAdvisor 7/8 node để có metric container toàn cụm.
3. Nâng `limits.nodes` của NodePool arm64 (trần cứng hiện tại 4 node) — cần cân với ngân sách, vì
   đây là trần cố ý của CDO01 chứ không phải lỗi. Xem đính chính ở bảng trên.
4. `checkout → email` vẫn là lời gọi đồng bộ không deadline riêng; nên bọc timeout riêng để hàng
   đợi của một service phụ trợ không bao giờ ăn được trọn budget của luồng tiền.

## Tham chiếu

- [Báo cáo trần thông lượng Mandate #19](../mandate-19-throughput-ceiling-report.md)
- [`docs/evidence/mandate-19/real-2026-07-30/`](../evidence/mandate-19/real-2026-07-30/) — evidence canonical
- [`scripts/mandate-19/README.md`](../../scripts/mandate-19/README.md) — cách tái lập
- [Runbook staged rollout](../runbooks/mandate-19-staged-rollout.md)
- `gitops/infrastructure/hpa-hotpath.yaml` · `gitops/infrastructure/backend-headless-services.yaml`
- `phase3 - information/deploy/values-prod.yaml`
- `phase3 - information/techx-corp-platform/src/frontend-proxy/envoy.tmpl.yaml`
- `phase3 - information/techx-corp-platform/src/frontend/gateways/rpc/grpcChannel.ts`

---

**Người ký:** CDO01 — TF3
**Ngày ký:** 30/07/2026
