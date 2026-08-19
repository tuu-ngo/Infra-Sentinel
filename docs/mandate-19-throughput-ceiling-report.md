# Mandate #19 — Báo cáo: Biết trần của mình và nâng trần bằng hiệu suất

**Ngày đo:** 30/07/2026
**Người thực hiện:** CDO01 — TF3
**Trụ:** Performance Efficiency · chạm Cost Optimization · Reliability
**ADR:** [`docs/adr/0011-mandate-19-throughput-ceiling-load-shedding.md`](adr/0011-mandate-19-throughput-ceiling-load-shedding.md)
**Evidence canonical:** [`docs/evidence/mandate-19/real-2026-07-30/`](evidence/mandate-19/real-2026-07-30/)
**Video demo xuống mềm:** [`shed-demo/timelapse.mp4`](evidence/mandate-19/real-2026-07-30/shed-demo/timelapse.mp4) · [`.gif`](evidence/mandate-19/real-2026-07-30/shed-demo/timelapse.gif)
**Video vùng trần (arm tuned3):** [`tuned3-ceiling-video/timelapse.gif`](evidence/mandate-19/real-2026-07-30/tuned3-ceiling-video/timelapse.gif)
**Postmortem kèm:** [0017 — product-catalog về 0 replica](postmortem/0017-product-catalog-replicas-zero-hpa-cannot-recover.md)
**Harness tái lập:** [`scripts/mandate-19/`](../scripts/mandate-19/)
**📖 Bản tóm tắt dễ đọc (ảnh + video nhúng):** [`mandate-19-nghiem-thu.md`](mandate-19-nghiem-thu.md)

> **Bản này thay thế hoàn toàn báo cáo cũ.** Số liệu cũ (trần "174,75 RPS @ 328 user")
> đã bị loại — lý do ở §2. Mọi con số dưới đây có artifact thô đi kèm và tái lập được
> bằng lệnh.

---

## 1. Directive hỏi gì

| # | Yêu cầu |
|---|---|
| 1 | Tìm trần THẬT — tăng tải tới khi SLO gãy, xác định chính xác chịu được bao nhiêu |
| 2 | Nâng trần **bằng hiệu suất, không thêm node**; chứng minh requests-per-node tăng |
| 3 | Tìm service **bão hoà sớm nhất** (cạn CPU/mem/connection/queue) và nới nó |
| 4 | Vượt trần thì **xuống mềm** — shed browse, giữ checkout, không sập |

---

## 2. Vì sao phải đo lại từ đầu

Bộ evidence cũ (`pm-152/`, `after/`) không dùng được:

| Vấn đề | Chi tiết |
|---|---|
| **Node-set trôi giữa bài** | `pm-152/test_slo/nodes.jpg` cho thấy **9 → 10 → 11** node. Directive đòi "không thêm node" — mọi claim requests-per-node từ đó mất cơ sở. |
| **Stage quá ngắn** | Nhiều stage 59s–4 phút, dưới protocol 5 phút. |
| **Cổng đánh giá không tồn tại** | Tuyên FAIL bằng "checkout p99 ≤ 300ms". Ngưỡng này **không có trong `SLO.md`** — nó là budget server-side steady-state của Mandate #16, bị áp lên p99 **client-side** trong lúc **cố ý** đẩy quá trần. |
| **Không tái lập được** | Trần "174,75 RPS @ 328 user" không có CSV/JSON thô. |

### Cổng SLO dùng trong bản này

Đúng bốn ngưỡng trong [`SLO.md`](../phase3%20-%20information/onboarding/SLO.md), query lấy
nguyên từ `slo-dashboard.json` (chỉ thay `$__rate_interval` bằng độ dài cửa sổ):

| SLI | Ngưỡng |
|---|---|
| Browse non-5xx | ≥ 99,5% |
| Browse p95 | < 1s |
| Cart success | ≥ 99,5% |
| Checkout success | ≥ 99,0% |

**Không có ngưỡng latency cho checkout trong hợp đồng SLO.** Bản này không tự chế thêm.

### Protocol đo

| Hạng mục | Giá trị |
|---|---|
| Thời lượng stage | 420s; **cửa sổ đo = 300s cuối** (bỏ ramp) |
| Generator | **ngoài cluster** (Docker trên máy vận hành), đi qua CloudFront công khai |
| Vì sao ngoài cluster | Generator trong cluster tranh CPU với chính hệ đang đo, và ở tải cao còn kích Karpenter cấp node — đã đo được node trôi **7 → 10** khi bắn tải |
| Profile | port nguyên từ `src/load-generator/locustfile.py`, `wait_time = between(1,10)` |
| Snapshot mỗi stage | `node_count`, `node_set_sha256`, `kubectl get hpa`, `top nodes` → `infra.txt` |

---

## 3. Một lỗi phương pháp đã phải sửa giữa chừng — đọc trước khi xem số

Ban đầu tôi lấy `frontend_total_rate` (span metrics trong Prometheus) làm "served RPS". **Sai.**

Phát hiện ra vì stage 800 user báo throughput **thấp hơn** stage 600 user, trong khi Locust
offered giống hệt. Đối chiếu từng `span_name` thì **mọi route giảm đúng cùng hệ số 1,688×**
— dấu hiệu mất mát đồng đều, không phải hệ chậm đi. Log `otel-gateway`:

```
07:18:01Z memorylimiter  "Memory usage is above soft limit. Forcing a GC."  cur_mem_mib=495
07:18:10Z queue_sender   "Exporting failed. Dropping data."                 dropped_items=8645
07:19:00Z queue_sender   "Exporting failed. Dropping data."                 dropped_items=8365
07:19:18Z queue_sender   "... larger than max 4194304"                      dropped_items=10100
```

**Cách xử:**

| Loại số | Nguồn | Lý do |
|---|---|---|
| Tỉ lệ (success rate, latency) | Prometheus span metrics | mất mát đồng đều → tử/mẫu cùng co → tỉ lệ còn đúng |
| Tuyệt đối (RPS) | **CSV Locust** | đo tại người dùng, không qua pipeline nào |

Script: [`scripts/mandate-19/client_truth.py`](../scripts/mandate-19/client_truth.py).

**Lưu ý khi đọc "RPS":** generator là closed-loop có think time, nên offered RPS bị chặn bởi
*số user / think time* chứ không bởi sức hệ. Vì vậy **trần đọc theo SỐ USER** giữ được SLO;
RPS là con số dẫn xuất báo cáo kèm.

---

## 4. YC#1 — Trần THẬT

Arm `baseline` = cấu hình production trước mọi tuning của mandate này.

| Users | served RPS | browse | cart | checkout | Verdict |
|---:|---:|---:|---:|---:|---|
| 200 | 40,9 | 99,258% | 100% | 99,89% | FAIL¹ |
| 400 | 76,0 | 99,498% | 100% | 100% | ~biên |
| 600 | 121,7 | 99,632% | 100% | 99,96% | PASS |
| 800 | 164,1 | 99,977% | 99,991% | 100% | PASS |
| **1000** | **202,4** | **99,610%** | **100%** | **99,89%** | **PASS ← TRẦN** |
| 1400 | 238,8 | 99,585% | 99,988% | **29,21%** | FAIL |
| 1800 | 298,2 | 99,019% | 99,991% | 7,12% | FAIL |
| 2400 | 342,4 | 84,763% | 99,982% | 0,02% | FAIL |

¹ 200 user FAIL do node-churn thoáng qua (80 lỗi dồn trong 6 giây lúc Karpenter
consolidate node), không do tải. Chi tiết trong `baseline/u200/locust_failures.csv`.

> ### Trần = **1000 user đồng thời · 202,4 RPS phục vụ**
> Cao hơn ~3× con số 328 user trong báo cáo cũ.

**Thứ gãy trước tiên không phải browse mà là CHECKOUT** — rơi thẳng 99,89% → 29,21% chỉ
trong một nấc tải. Browse lúc đó vẫn còn 99,585%.

---

## 5. YC#3 — Nút thắt: ba nguyên nhân, hai trong ba không phải CPU

### 5.1. `email` — bão hoà **hàng đợi**

| Điểm đo (stage 1400 user) | p95 |
|---|---:|
| span **client** `POST` checkout → email | **15 000 ms** = route timeout Envoy |
| span **server** email | **391 ms** |

**14,6 giây chênh lệch là thời gian XẾP HÀNG, không phải xử lý.** Đúng loại bão hoà
directive gọi tên: *"không phải chậm — mà cạn: connection/queue depth"*.

Vì sao nó kéo sập checkout: `checkout` gọi `sendOrderConfirmation` **đồng bộ**
(`src/checkout/main.go:473`), không đặt deadline riêng → hàng đợi email ăn trọn budget
request → **504**. Ở stage vỡ: **3 432/5 431 đơn hỏng = 82% toàn bộ lỗi client**.

Sức chứa: Ruby/Sinatra trên Puma (MRI có GIL), **1 replica**, limit CPU **100m = 0,1 core**,
trong khi tải là 14,7 rps × 391 ms ≈ **5,8 request đồng thời**.

**Nới (PR #656):** HPA 2..8 @60% · request 25m→75m · limit 100m→**600m**.

**Kết quả đo lại — checkout ở stage 1400 user:**

| baseline | tuned (#649) | tuned2 (#656) |
|---:|---:|---:|
| 29,21% | 36,62% | **98,18%** |

### 5.2. Kết nối bị ghim vào một pod — **lý do "thêm replica" không có tác dụng**

`kubectl top pod` khi `product-catalog` đang ở **11 replica**:

```
xxhsp 353m · cw8nx 136m · pzcxg 11m · TÁM pod còn lại 1-2m
```

`product-reviews` y hệt: 313m / 254m / 85m / 4m.

**Cơ chế:** Service ClusterIP trả về **một VIP** → gRPC giữ **một kết nối TCP dài hạn** →
kube-proxy ghim kết nối đó vào **một pod**. Pod do HPA sinh ra *sau* khi kết nối đã dựng
thì **không bao giờ** nhận traffic.

Hệ quả kép: HPA thấy CPU **trung bình 48%** nên ngừng scale, trong khi pod nóng chính là pod
làm vỡ deadline và sinh `HTTP 500` trên `/api/products/[id]`.

**Đối chứng ngay trong cụm:** `frontend` trải đều **123–138m** — vì hop
`frontend-proxy → frontend` đã đi qua `frontend-headless` từ trước. Pattern đúng đã có sẵn
trong repo, chỉ chưa áp cho hop `frontend → backend`.

**Nới (PR #660):** Service headless + `round_robin` phía client. Phải **cả hai vế** —
headless mà giữ `pick_first` thì vẫn ghim IP đầu; `round_robin` mà giữ ClusterIP thì DNS chỉ
trả 1 VIP, không có gì để xoay.

### 5.3. Deadline gRPC 500ms là cò súng quá nhạy

Log frontend ở stage vỡ: `4 DEADLINE_EXCEEDED: Deadline exceeded after 0.500s`.

`product-catalog` p95 server-side chỉ **6,9 ms** — deadline không thấp so với trung vị, nó
quá sát **đuôi**. Không có retry nên timeout thành lỗi cứng: **311 × HTTP 500**
(`/api/products/[id]`) + **431 × HTTP 503** (`/api/product-reviews/[id]`) = 742 lỗi.

Deadline tồn tại là đúng (REL-17-02). Chỉ chỉnh **ngưỡng** 500 → 1200 ms.

### 5.4. Right-size request theo **cả hai chiều**

| Service | Đo được | Hành động |
|---|---|---|
| `accounting` | throttle **86,1%** — consumer MSK **duy nhất** ghi đơn vào RDS | req 50m→150m · limit 200m→600m |
| `recommendation` | throttle 18,1%, nằm trong mẫu số SLI browse | req 100m→150m · limit 500m→700m |
| `ad` | dùng 17–21m nhưng **giữ chỗ 100m**, throttle 0% | req 100m→**30m** (trả chỗ) |

`accounting` throttle 86,1% là phát hiện độc lập đáng lưu ý: throttle ở đó nghĩa là **đơn đã
đặt xong vẫn nằm chờ trong topic**.

---

## 6. YC#2 — Nâng trần: điều KHÔNG hiệu quả và điều hiệu quả

### 6.1. Nới `maxReplicas` một mình: KHÔNG hiệu quả

Arm `tuned` (PR #649): frontend 8→16, checkout 8→14, proxy 8→12, catalog 8→12. Đo lại đủ 8 stage:

| Users | baseline RPS | tuned RPS | Δ |
|---:|---:|---:|---:|
| 1000 (trần) | 202,4 | 202,8 | +0,4 |
| 1400 | 238,8 | 240,2 | +1,4 |

**Trần không đổi — vẫn 1000 user.** Lý do ở §5.2: replica thêm vào là dung lượng
**traffic không tới được**.

Tệ hơn, một mình nó còn **làm yếu lớp shed** (§7.2).

### 6.2. Nới nút thắt `email`: dịch được điểm gãy

Arm `tuned2` (PR #656):

| Users | browse | cart | checkout | Verdict |
|---:|---:|---:|---:|---|
| 800 | 99,635% | 99,991% | 99,95% | PASS |
| **1000** | **99,629%** | **100%** | **99,96%** | **PASS** |
| 1400 | 96,465% | 100% | **98,18%** | FAIL (browse) |

Checkout ở 1400 lên **98,18%** (từ 29,21%) — nút thắt §5.1 đã xử. Nhưng trần vẫn 1000 user
vì **ràng buộc dịch sang browse**, đúng chỗ nút thắt §5.2 nằm.

### 6.3. Sửa đúng nguyên nhân — arm `tuned3` (PR #660 + #664)

Bật `round_robin` trên Service headless. **Phân bố đã sửa được thật**, đo bằng `kubectl top pod`
cùng ngày, cùng mức tải 600 user:

| `product-catalog` | Trước (ClusterIP + `pick_first`) | Sau (headless + `round_robin`) |
|---|---|---|
| Phân bố CPU | `353m · 136m · 11m · **1m × 8**` | `55m · 31m · 20m · 15m` |
| Tỉ lệ nóng/lạnh | **353×** | **3,7×** |
| Pod nhận traffic | **2/11** | **4/4** |

Log frontend xác nhận: `remote_addr=10.0.39.121:8080` — **IP pod trực tiếp**, không còn ClusterIP.

Kết quả ladder `tuned3`:

| Users | servedRPS base → tuned3 | checkout base → tuned3 | browse tuned3 | 429 |
|---:|---|---|---:|---:|
| 1000 | 202,4 → 173,2 | 99,89% → 99,67% | 98,583% | 0 |
| 1400 | 238,8 → **277,7** | 29,21% → **99,55%** | 97,390% | 0 |
| 1800 | 298,2 → **355,7** | 7,12% → **99,18%** | 97,325% | 30 |
| 2400 | 342,4 → **442,3** | 0,02% → **88,59%** | 95,872% | 186 |

**Ba thứ cải thiện rõ rệt:**

1. **Checkout** — ở 1800 user: `7,12% → 99,18%`. Luồng tiền giờ sống sót ở mức tải mà trước
   đây nó gần như chết hẳn.
2. **Throughput ở tải cao** — 2400 user: `342,4 → 442,3 RPS` (**+29%**) trên **cùng 9 node**.
3. **Xuống mềm hoạt động trở lại** — 429 xuất hiện ở 1800/2400 (30 và 186) sau khi hiệu chỉnh
   budget (#658); arm `tuned2` có **0 × 429** ở cùng mức tải.

### 6.4. Nhưng theo cổng 4/4 nghiêm ngặt thì YC#2 **CHƯA ĐẠT** — và vì sao

`browse` dính **~1–2% lỗi ở MỌI mức tải**, kể cả 400 user. Cổng đòi ≥ 99,5%, nên chỉ stage
200 user PASS. Xét thuần theo "stage cao nhất qua cả 4 cổng", trần **tụt** chứ không tăng.

Không tô hồng: đây là một **đánh đổi có thật** mà bản vá tạo ra.

`pick_first` vô tình cung cấp **cách ly**: mỗi pod frontend ghim vào một pod backend riêng, nên
khi một backend quá tải thì chỉ phần frontend ghim vào nó bị ảnh hưởng — phần còn lại vẫn sạch.
`round_robin` xoá cách ly đó: mọi frontend dùng chung toàn bộ backend, nên khi backend chạm
trần thì **mọi** request cùng chịu. Đổi lại là dung lượng được dùng hết — thấy rõ ở +29% RPS.

Lỗi còn lại dồn thành từng cụm ngắn (8–170 giây tuỳ stage) rồi tự tắt, trong khi tài nguyên tại
thời điểm đó **còn thừa nhiều** — ở u1000: `frontend-hpa cpu 79%/65%` mới 10/16 replica,
`product-catalog-hpa cpu 61%/65%` mới 8/12, tức **dưới cả ngưỡng scale**. Đây không phải dấu hiệu
cạn dung lượng.

> ⚠️ **Đính chính:** bản trước của mục này suy luận *"pod bão hoà → sinh lỗi → ~25s sau HPA thêm
> pod → lỗi dừng"*. Chuỗi nhân quả đó tự mâu thuẫn với chính số liệu: cụm lỗi ở stage u400 **tắt
> lúc 09:22:35**, còn HPA scale-up mãi **09:22:56** — lỗi đã hết **21 giây trước** khi có pod mới,
> nên pod mới không thể là thứ chữa nó.

**Nguyên nhân đúng:** `round_robin` được ship **không kèm `retryPolicy`** (xem `grpcChannel.ts` —
service config chỉ có `loadBalancingConfig`, không có `methodConfig`). Với `pick_first` cũ, một
pod bị thay chỉ ảnh hưởng client đang ghim vào nó; với `round_robin`, **mọi** client đều dính một
phần. `dns_min_time_between_resolutions_ms: 5000` nghĩa là sau khi một pod biến mất, client còn
gửi vào địa chỉ chết tới 5 giây — khớp đúng độ dài cụm lỗi 8 giây ở u400. Không có `retryPolicy`,
mỗi lần như vậy là lỗi 500 tới thẳng người dùng. Chi tiết và kế hoạch vá:
[`mandate-19-ke-hoach-yc2.md`](mandate-19-ke-hoach-yc2.md).

### 6.5. Trần thật sự bị chặn bởi cái gì — đã xác định

Ở stage 2400 user, **13 pod Pending** (8 `frontend`, 2 `frontend-proxy`, 3 `product-catalog`):

```
0/9 nodes are available:
  4 node(s) didn't match Pod's node affinity/selector   <- 4 node t3.large managed
  1 Insufficient cpu                                    <- tầng elastic đã cạn
node limits have been exhausted for nodepool (flash-sale-spot-arm64)
label "techx.io/arch" does not have known values (typo of "kubernetes.io/arch"?)
```

CPU thật từng node cùng lúc đó:

| Node | CPU |
|---|---|
| `…5-127` (elastic) | **99%** |
| `…34-80` (elastic) | 62% |
| `…24-177` (**managed**) | 58% |
| `…8-134` (**managed**) | 49% |
| `…26-153` (**managed**) | 29% |
| `…43-83` (**managed**) | 18% |

`values-mandate13.yaml` giam 10 workload hot path bằng
`nodeSelector: { techx.io/workload: elastic, techx.io/arch: arm64 }`. **Bốn node `t3.large`
managed không mang label `techx.io/workload` nên không bao giờ nhận được pod hot-path** — chúng
ngồi ở 18–58% CPU trong khi node elastic chạm 99% và 13 pod xếp hàng.

Karpenter cũng không cấp thêm được node elastic — nhưng **chỉ vì `limits` đã cạn**:

| NodePool arm64 | `limits.nodes` | `limits.cpu` |
|---|---:|---:|
| `flash-sale-spot-arm64` | 2 | 16 |
| `elastic-ondemand-fallback-arm64` | 2 | 8 |
| **Trần cứng tầng elastic arm64** | **4** | **24** |

> **⚠️ Đính chính so với bản đầu của báo cáo này.** Bản đầu viết NodePool "không khai báo
> `techx.io/arch` trong `requirements` nên không biết cách tạo node thoả nodeSelector". **Sai.**
> Karpenter in lý do từ chối của *từng* NodePool rồi gộp thành một khối, và hai dòng đó thuộc về
> hai pool khác nhau:
>
> ```
> node limits have been exhausted for nodepool (flash-sale-spot-arm64)   <- pool arm64
> label "techx.io/arch" does not have known values                       <- pool AMD64
> ```
>
> Dòng thứ hai nói về `flash-sale-spot` và `elastic-ondemand-fallback` (amd64) — hai pool đó thật
> sự không mang label `techx.io/arch`, và **đó là hành vi đúng**: pod ghim arm64 không nên rơi vào
> node amd64. Hai pool **arm64** đã có sẵn label ở `template.metadata.labels`
> (`gitops/karpenter/spot-nodepool.yaml:88`, `ondemand-fallback-nodepool.yaml:92`), và Karpenter
> đưa static label trong template vào requirements của node sẽ tạo — không cần lặp lại ở
> `requirements`.
>
> Bằng chứng thực nghiệm mạnh hơn cả đọc cấu hình: node elastic `…5-127` chạy **99% CPU** ngay tại
> snapshot này. Nếu label thiếu thật thì tầng elastic đã rỗng, và bản tuned3 442,3 RPS không thể
> tồn tại. **Việc cần làm vì thế cũng đổi**: không phải "sửa `requirements`" (không có gì để sửa)
> mà là nâng `limits.nodes`, hoặc gỡ ghim arm64 cho một phần hot path.

> **Đây là đòn bẩy tiếp theo, và nó đúng nghĩa "nâng trần bằng hiệu suất, không thêm node":
> 8 vCPU đã trả tiền đang nằm không.** Image đã multi-arch (`build-push-ecr.yml` build
> `linux/amd64,linux/arm64`) nên về kỹ thuật hot path chạy được trên `t3.large`.
> Chưa làm vì nó sửa thiết kế Mandate #13 của CDO01 (ghim Graviton để tiết kiệm chi phí) —
> cần thống nhất trước, không đơn phương.

### 6.6. Ràng buộc "không thêm node" được tôn trọng

Ở stage vượt trần, pod hot-path ở trạng thái `Pending` với lý do:

```
Failed to schedule pod, node limits have been exhausted for nodepool (flash-sale-spot-arm64);
node limits have been exhausted for nodepool (elastic-ondemand-fallback-arm64)
```

Karpenter `limits` chặn cấp thêm node — đó là bằng chứng ràng buộc còn hiệu lực, không phải sự cố.

---

## 7. YC#4 — Xuống mềm

### 7.1. Cơ chế chạy thật, đo qua đường public

| Kiểm tra | Kết quả |
|---|---|
| `GET /api/products` lúc overload | **7/8 → HTTP/2 429** kèm `x-techx-load-shed: browse` |
| Envoy `browse_rate_limiter` | `rate_limited: 19449` · `enforced: 19449` · `ok: 6221` |
| Bucket bảo vệ luồng tiền | `local_rate_limiter.rate_limited:` **0** |
| `/api/products/<id>`, `/api/cart` lúc overload | **200**, không 429 |

Trong ladder, stage 2400 user (2,4× trần): **3 641 × 429** trên route shedable,
**0 × 429** trên route protected.

**Điểm cần giải thích với mentor:** browse success trên Grafana **không tụt** khi shed hoạt
động. Đúng thiết kế — 429 bị chặn tại Envoy nên không tới frontend, và `SLO.md` định nghĩa
browse SLI là **non-5xx**, mà 429 không phải 5xx. Shed hy sinh browse **mà không đốt SLO**.

**Đính chính:** runbook cũ đòi header `x-envoy-ratelimited: true`. Yêu cầu đó **bất khả thi**
— filter `local_ratelimit` không phát header đó (chỉ filter *global* ratelimit mới có). Bằng
chứng đúng là `x-techx-load-shed: browse`.

### 7.2. Regression do chính chúng tôi gây ra — và bản sửa

Bucket là **per-replica**, nên budget tổng = `tokens_per_fill × số replica proxy`.
PR #649 nới proxy 8 → 12 và vô tình nâng luôn budget shed 400 → 600:

| Arm | proxy max | 429 @2400 user | browse @2400 |
|---|---:|---:|---:|
| baseline | 8 | **3 641** | 84,8% |
| tuned | 12 | **0** | 95,4% |
| tuned2 | 12 | **0** | **63,4%** |

Dòng `tuned2` là bằng chứng rõ nhất: sau khi checkout được nới, tải dồn hết sang browse, và
vì lớp shed **không còn kích hoạt**, browse rơi tự do xuống 63,4% — thấp hơn hẳn baseline
84,8% ở cùng mức tải. **Nhiều replica hơn mà mất khả năng xuống mềm là ngược chiều YC#4.**

**Sửa (PR #658):** `tokens_per_fill` 50 → **33** (12 × 33 = 396 ≈ 8 × 50 = 400 của baseline),
`max_tokens` 100 → 66.

**Hạn chế còn lại:** budget vẫn trôi theo số replica. Sửa đúng về kiến trúc là bucket dùng
chung toàn cluster (`local_cluster_rate_limit`) — nằm trong image, phải rebuild.

---

## 8. Khoảng trống quan sát phát hiện kèm

| Vấn đề | Chi tiết | Ảnh hưởng tới bài này |
|---|---|---|
| **cAdvisor chết 7/8 node** | `Get "https://10.0.x.x:10250/metrics/cadvisor": context deadline exceeded` | Panel *"Pod count — hot-path services"* luôn `No data` → **không dùng làm bằng chứng**. Số per-pod lấy từ metrics-server. |
| **NodePool thiếu `techx.io/arch`** | `label "techx.io/arch" does not have known values (typo of "kubernetes.io/arch"?)` — 10 workload hot path `nodeSelector` vào label mà NodePool không khai báo | Karpenter không cấp được node cho hot path. Mandate #13, CDO01. |
| **SLI checkout từng mù** | Panel SLO đo trên span **nội bộ** checkout → request timeout ở tầng trên vô hình. Ở 2400 user: **8 875/8 877 đơn hỏng** mà dashboard vẫn báo `checkout_success = 100%` | Đã sửa (PR #649): đo ở **biên** frontend. |

---

## 9. Trạng thái theo từng yêu cầu

| YC | Trạng thái | Bằng chứng |
|---|---|---|
| **1. Tìm trần THẬT** | ✅ **Đạt** | **1000 user / 202,4 RPS**. 4 arm × 8 stage, cửa sổ đo 300s cuối, node-set hash mỗi stage, generator ngoài cluster. Cao hơn ~3× con số cũ |
| **2. Nâng trần không thêm node** | 🟡 **Một phần** | Throughput ở tải cao **+29%** (342,4 → 442,3 RPS @2400) trên **cùng 9 node**, và checkout @1800 `7,12% → 99,18%`. **Nhưng** theo cổng 4/4 nghiêm ngặt thì trần **không tăng** — browse dính ~1–2% lỗi ở mọi mức tải. Không tuyên PASS |
| **3. Xử nút thắt** | ✅ **Đạt** | Ba nút thắt tìm bằng số đo, hai trong ba là connection/queue. `email`: checkout @1400 **29,21% → 99,55%**. Phân bố `product-catalog`: **353× → 3,7×** lệch |
| **4. Xuống mềm** | ✅ **Đạt** | 104.264 × 429 trên browse, luồng tiền **99,95%**, Envoy `rate_limited: 19.539` vs `0`. Regression budget đã tìm ra và sửa — 429 hoạt động trở lại ở `tuned3` (30 @1800, 186 @2400) sau khi `tuned2` có **0** |

### Nói thẳng về YC#2

Bản vá **chạm đúng nguyên nhân** — phân bố tải đã sửa được, và hệ phục vụ nhiều hơn 29% trên
cùng số node. Nhưng nó tạo ra một **đánh đổi có thật**: `pick_first` vô tình cung cấp cách ly
giữa các pod frontend, `round_robin` xoá cách ly đó để dùng hết dung lượng. Kết quả là browse
chịu ~1% lỗi đều đặn thay vì lỗi dồn cục bộ.

Và trần cuối cùng **không nằm ở phần mềm nữa**: 13 pod Pending vì hot path bị `nodeSelector`
giam vào tầng elastic đã cạn, trong khi **4 node `t3.large` managed ngồi ở 18–58% CPU** và
không bao giờ nhận được pod hot-path (§6.5).

## 10. Tái lập

```sh
# tunnel EKS + prometheus
kubectl -n techx-tf3 port-forward svc/prometheus 29090:9090

# một stage
bash scripts/mandate-19/run_stage_external.sh <arm> <users> 420 300

# tổng hợp client-side
python3 scripts/mandate-19/client_truth.py <thư-mục-arm>

# demo xuống mềm + video
kubectl -n techx-tf3 port-forward svc/grafana 23000:80
bash scripts/mandate-19/shed_demo.sh <out-dir> 120 420
```

Chi tiết: [`scripts/mandate-19/README.md`](../scripts/mandate-19/README.md).

---

## 11. Việc còn mở — xếp theo tác động

| # | Việc | Vì sao |
|---|---|---|
| **1** | **Cho hot path dùng được 4 node `t3.large` managed** — gỡ/nới `nodeSelector` trong `values-mandate13.yaml` | **8 vCPU đã trả tiền đang nằm không** trong khi node elastic chạm 99% và 13 pod xếp hàng. Đúng nghĩa "nâng trần bằng hiệu suất, không thêm node". Image đã multi-arch nên chạy được trên amd64. **Cần thống nhất với CDO01** vì sửa thiết kế Mandate #13 (ghim Graviton để tiết kiệm) |
| **2** | Nâng `limits.nodes` của NodePool arm64 (hiện `flash-sale-spot-arm64` = 2, `elastic-ondemand-fallback-arm64` = 2 ⇒ trần cứng **4 node**) | Karpenter báo `node limits have been exhausted for nodepool (flash-sale-spot-arm64)`. Đây là trần **cố ý** của CDO01 để giữ chi phí, nên phải cân với ngân sách chứ không nâng vô điều kiện. ~~Bổ sung `techx.io/arch` vào `requirements`~~ — đính chính: label đã có sẵn ở `template.metadata.labels`, xem §6.5 |
| 3 | Giảm độ trễ HPA cho `product-catalog` (nâng `minReplicas` hoặc hạ target) | Burst lỗi ~8s xảy ra đều đặn ~25 giây **trước** mỗi lần scale-up |
| 4 | Bucket shed dùng chung toàn cluster (`local_cluster_rate_limit`) | Budget hiện vẫn trôi theo số replica proxy — cần rebuild image |
| 5 | Sửa cAdvisor 7/8 node | Panel *"Pod count"* chết, không có metric container toàn cụm |
| 6 | Bọc timeout riêng cho `checkout → email` | Hàng đợi service phụ trợ không được phép ăn trọn budget luồng tiền |
| 7 | Xem lại `replicasManagedExternally` (postmortem 0017) | 10 service có lỗ hổng "về 0 là kẹt vĩnh viễn"; `frontend` rơi vào đó là mất storefront |

---

**Ký:** CDO01 — TF3 · 30/07/2026
