# Postmortem 0016 — Product Reviews `DEADLINE_EXCEEDED` trong lúc synthetic load, HPA scale nhưng pod mới không Ready kịp (28/07/2026)

**Ngày điều tra:** 28/07/2026

**Múi giờ:** Asia/Ho_Chi_Minh (+07); các mốc Kubernetes UTC được ghi kèm `Z`

**Phạm vi:** `frontend` → gRPC `product-reviews:GetProductReviews`

**Mức độ:** suy giảm một tính năng không critical; chưa có bằng chứng storefront/checkout bị downtime

**Trạng thái:** nguyên nhân sự cố đã khoanh vùng; **P2 + admission-control cho P3 đã LIVE trên production**
(28/07/2026 — [PR #531](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/531) merge → build → bump-image
[#535](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/535)/[#538](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/538)
merge → ArgoCD Synced/Healthy, verify qua `kubectl` — xem §11.4). **P4 đã đo bằng dữ liệu thật (§12). P0 +
P1 đã thực hiện bằng load test có kiểm soát trên production, capacity-arrival gap tái hiện được và fix
hoạt động đúng thiết kế; phát hiện thêm root cause AI chậm là AWS Bedrock throttle, không phải bug
product-reviews (§13).** **P3 đầy đủ (tách executor/deployment AI riêng thật) và P5 (deadline review theo
p99) vẫn CHƯA làm** — incident **chưa đủ điều kiện đóng** theo §8, nhưng phần lớn evidence đã đủ.

**Loại thay đổi của tài liệu này:** ban đầu docs-only; §11 bổ sung 28/07/2026 mô tả một PR code đề xuất
P2 + admission-control nội-process cho P3 (không đổi manifest/HPA/cluster — chỉ app code). PR đã qua một
vòng self-review + một vòng review độc lập tìm ra nhiều gap thật (xem §11) — **PR vẫn đang chờ review từ
người trước khi merge**, chưa merge nghĩa là chưa vào pipeline build/deploy.

---

## TL;DR

Trace Jaeger lúc **17:08:43.547 (+07)** cho thấy `frontend` gọi
`otel.demo.ProductReviewService/GetProductReviews` và bị:

```text
4 DEADLINE_EXCEEDED: Deadline exceeded after 0.501s
name resolution: 0.001s
remote_addr=172.20.242.200:3551
```

Đây không phải bằng chứng khách thật truy cập web tăng đột biến. Root span của chính trace là
`load-generator: user_get_product_reviews`, trùng với task Locust trong
[`locustfile.py`](<../../phase3 - information/techx-corp-platform/src/load-generator/locustfile.py>).
Vì vậy, kết luận đúng là:

- **Có liên quan tới tải tăng:** HPA đã thấy CPU vượt target và yêu cầu scale `product-reviews` từ 2 lên 3 pod
  lúc 17:06:20.
- **Tải gây trace này là synthetic load của Locust**, không phải bằng chứng organic traffic từ người dùng.
- Pod thứ ba bị chậm scheduling, mất khoảng 12 giây pull image, sau đó readiness probe tiếp tục fail. Tại
  17:08:43, pod này chưa Ready nên hai pod cũ vẫn phải xử lý tải.
- `frontend` chủ động đặt deadline rất ngắn, **500 ms**. Khi server không trả trước deadline, request bị hủy
  đúng thiết kế fail-fast.
- `product-reviews` dùng một gRPC worker pool 10 thread cho cả RPC đọc review nhanh và RPC AI/Bedrock chậm.
  Đây là rủi ro head-of-line blocking đáng xử lý, nhưng chưa có metric queue/thread tại đúng thời điểm để
  khẳng định một RPC AI cụ thể đã chặn span trong ảnh.

Phương án an toàn nhất không downtime không phải là tăng deadline ngay. Thứ tự khuyến nghị:

1. Với load test có lịch: **pre-scale trước khi bắn tải**, chỉ bắt đầu khi replica bổ sung đã Ready.
2. Giữ rolling strategy `maxUnavailable: 0`, quan sát theo stage và rollback qua GitOps nếu gate fail.
3. Tách RPC AI chậm sang deployment/service riêng theo kiểu parallel deploy rồi mới chuyển traffic.
4. Chỉ hiệu chỉnh deadline sau khi có p99 đúng cửa sổ và ngân sách latency end-to-end; không dùng tăng
   deadline để che queue/saturation.

---

## 1. Người dùng nhìn thấy gì?

### 1.1 Trace bị lỗi

Span được chọn trong Jaeger:

| Thuộc tính | Giá trị |
|---|---|
| Trace start | 28/07/2026 17:08:43.547 (+07) |
| Root operation | `load-generator: user_get_product_reviews` |
| Client service | `frontend` |
| RPC | `otel.demo.ProductReviewService/GetProductReviews` |
| Peer | `product-reviews:3551` |
| Span duration | 502.31 ms |
| gRPC status | `4 DEADLINE_EXCEEDED` |
| Name resolution | 1 ms |

`name resolution: 0.001s` và việc client đã có `remote_addr` loại trừ giả thuyết DNS là nguyên nhân chính của
span này. Deadline hết sau khoảng 501 ms, gần như đúng bằng cấu hình 500 ms trong code.

### 1.2 Mức ảnh hưởng

API route product reviews không bắt riêng lỗi timeout:

- [`ProductReview.gateway.ts`](<../../phase3 - information/techx-corp-platform/src/frontend/gateways/rpc/ProductReview.gateway.ts>)
  đặt `PRODUCT_REVIEWS_DEADLINE_MS = 500` và reject promise nếu gRPC trả lỗi.
- [`pages/api/product-reviews/[productId]/index.ts`](<../../phase3 - information/techx-corp-platform/src/frontend/pages/api/product-reviews/[productId]/index.ts>)
  `await` lời gọi này mà không có nhánh xử lý `DEADLINE_EXCEEDED`.
- [`ProductReview.provider.tsx`](<../../phase3 - information/techx-corp-platform/src/frontend/providers/ProductReview.provider.tsx>)
  nhận lỗi qua React Query. Widget có thể hiện trạng thái lỗi trong khi phần chính của product page vẫn hoạt động.

Vì vậy lỗi làm endpoint product-review trả lỗi và widget review không tải được; không có bằng chứng nó làm
toàn bộ storefront, cart hoặc checkout downtime. Log frontend cho thấy timeout lặp lại trên cả hai frontend
pod quanh cửa sổ, nên đây không phải chỉ là một span lỗi đơn lẻ. Tuy nhiên chưa lưu được raw count đầy đủ của
đúng cửa sổ, vì vậy tài liệu này không tự đặt số request lỗi.

---

## 2. Timeline đã đối chiếu

| Thời gian +07 | UTC | Bằng chứng / diễn biến |
|---|---|---|
| 17:06:20 | 10:06:20Z | HPA `product-reviews-hpa` scale Deployment từ 2 lên 3 do CPU trên target. |
| 17:06:20–17:06:57 | 10:06:20–10:06:57Z | Pod mới ban đầu `FailedScheduling` vì topology/taint/affinity, sau đó mới schedule được. |
| 17:07:01–17:07:14 | 10:07:01–10:07:14Z | Pull image mất 12.101 giây; container bắt đầu chạy. |
| từ 17:07:27 | từ 10:07:27Z | Readiness probe không kết nối được `10.0.47.210:3551` trong timeout 2 giây. |
| **17:08:43.547** | **10:08:43.547Z** | Trace trong ảnh bị `DEADLINE_EXCEEDED` sau 0.501 giây. Pod thứ ba chưa Ready. |
| khoảng 17:11 | khoảng 10:11Z | HPA ghi nhận scale về 2 sau cửa sổ tải; pod bổ sung không đóng góp capacity trong cửa sổ trace. |
| 17:54:02 | 10:54:02Z | Snapshot Locust độc lập: 158 virtual users, 34 current RPS. Đây là dữ liệu **sau** incident, không được gán ngược cho trace 17:08. |

Điểm quan trọng của timeline: HPA không “không chạy”. Nó đã phản ứng trước trace hơn hai phút, nhưng capacity
mới đến trễ và chưa vượt readiness gate. Trong khoảng đó hệ thống vẫn chỉ có hai endpoint Ready.

---

## 3. Phân tích nguyên nhân

### 3.1 Chuỗi lỗi

```text
Locust tạo synthetic request
  → frontend gọi GetProductReviews
  → tải trên 2 pod hiện hữu làm HPA yêu cầu pod thứ 3
  → pod thứ 3 vướng scheduling + image pull + readiness
  → chỉ 2 pod Ready tiếp tục nhận request
  → một số RPC không hoàn thành trước 500 ms
  → gRPC client hủy với DEADLINE_EXCEEDED
  → API route không phân loại lỗi, trả lỗi cho widget
```

### 3.2 Nguyên nhân trực tiếp đã xác nhận

1. **Deadline client là 500 ms.**

   [`ProductReview.gateway.ts`](<../../phase3 - information/techx-corp-platform/src/frontend/gateways/rpc/ProductReview.gateway.ts>)
   dùng cùng deadline này cho `GetProductReviews` và `GetAverageProductReviewScore`. Span 502.31 ms khớp trực
   tiếp với guard này.

2. **Capacity tại thời điểm trace vẫn là hai pod Ready.**

   Live endpoints trước/sau điều tra cho thấy hai endpoint ổn định. Pod thứ ba được HPA tạo nhưng readiness
   chưa pass trong cửa sổ xảy ra lỗi.

3. **Lỗi phát sinh dưới synthetic load.**

   Root span `load-generator: user_get_product_reviews` khớp task weight 2 tại `locustfile.py`. Không được đổi
   cách diễn đạt thành “khách truy cập web đông” nếu chưa có ALB/CloudFront hoặc access-log evidence tách khỏi
   load generator.

### 3.3 Yếu tố góp phần có bằng chứng mạnh

- HPA scale theo CPU với `minReplicas: 2`, `maxReplicas: 6`, target 75% trong
  [`hpa-hotpath.yaml`](../../gitops/infrastructure/hpa-hotpath.yaml). CPU là tín hiệu trễ: chỉ scale sau khi
  tải đã tới.
- Pod elastic có hard topology constraints. Khi không có capacity hợp lệ sẵn, scheduler/Karpenter cần thời
  gian tìm hoặc tạo chỗ chạy.
- Image pull cộng startup/readiness làm pod mới không thể hấp thụ spike ngay cả sau khi HPA đã đổi desired
  replicas.
- Snapshot CPU sau sự cố từng cho thấy phân phối không đều giữa hai pod. Đây là tín hiệu cần kiểm tra
  connection balancing của gRPC, không phải bằng chứng đủ để kết luận nó là nguyên nhân duy nhất.

### 3.4 Rủi ro kiến trúc cần tách khỏi điều đã xác nhận

[`product_reviews_server.py`](<../../phase3 - information/techx-corp-platform/src/product-reviews/product_reviews_server.py>)
khởi tạo một `ThreadPoolExecutor(max_workers=10)` cho toàn bộ gRPC server. Pool này phục vụ chung:

- đọc danh sách review;
- tính average score;
- `AskProductAIAssistant`, có thể chờ LLM/Bedrock lâu hơn nhiều.

Thiết kế này cho phép RPC AI chậm chiếm worker mà RPC đọc review cần. Locust file cũng chạy đồng thời
`get_product_reviews` (weight 2) và `ask_product_ai_assistant` (weight 1). Đây là một bulkhead gap thực tế.

Tuy nhiên hiện chưa có metric về active workers, queue depth hoặc trace link chứng minh đúng span 17:08 bị
chờ sau một request AI. Do đó:

- được phép ghi: **“shared pool có thể khuếch đại saturation và cần tách”**;
- chưa được phép ghi: **“Bedrock là root cause đã xác nhận”**.

### 3.5 Những giả thuyết đã loại trừ hoặc chưa đủ chứng cứ

| Giả thuyết | Kết luận |
|---|---|
| DNS chậm | Loại trừ cho span này: name resolution chỉ 1 ms. |
| Pod crash/OOMKilled | Không thấy restart/OOM ở hai pod đang Ready trong snapshot điều tra. |
| HPA hỏng | Loại trừ: có event scale 2→3; vấn đề là capacity chưa Ready kịp. |
| Organic web traffic tăng | Chưa có bằng chứng; trace được tạo bởi Locust. |
| DB là root cause | Chưa đủ chứng cứ đúng cửa sổ. |
| Bedrock trực tiếp chặn span | Có rủi ro shared pool nhưng chưa có queue/thread evidence để xác nhận. |

---

## 4. “Có phải lượng truy cập web nhiều không?”

**Câu trả lời ngắn:** tải tăng đã kích hoạt lỗi, nhưng trace này là tải test từ Locust, không chứng minh khách
thật đang vào website nhiều.

### 4.1 Điều biết chắc

- Tên root operation là task synthetic `user_get_product_reviews`.
- HPA scale vì CPU vượt target, nên hai pod thực sự chịu pressure.
- Log quanh cửa sổ có cả request đọc review và request AI.

### 4.2 Điều không được suy ra

- `158 users` không đồng nghĩa `158 RPS`.
- Snapshot Locust lúc 17:54:02 có 158 virtual users nhưng chỉ khoảng 34 current RPS toàn bài test. Snapshot
  này cách trace khoảng 45 phút, nên không đại diện chính xác cho 17:08.
- Số users mặc định trong Deployment là 10; giá trị 158 cho thấy run đã được chỉnh tay qua Locust UI/API.
  Cần lưu cấu hình run nếu muốn tái tạo.

### 4.3 Khoảng trống observability

Truy vấn Prometheus tại thời điểm điều tra trả một số rate lớn hơn rất nhiều raw Locust, đồng thời có nhiều
series gateway/host cho cùng metric. Dấu hiệu này phù hợp với việc cumulative OTLP series bị cộng lặp hoặc
temporality/label chưa được chuẩn hóa. Vì vậy:

- không dùng các rate đó làm số “web traffic thực” trong postmortem;
- raw Locust CSV, access logs và trace đúng cửa sổ là source of truth cho lần tái hiện;
- cần xử lý duplicate-series/temporality trước khi dùng dashboard Prometheus để tuyên bố pass/fail RPS.

---

## 5. Guardrail hiện có và vì sao vẫn lỗi

### 5.1 Những lớp đang làm đúng

- Frontend và product-reviews đều có hai replica nền.
- Cả hai workload dùng `RollingUpdate` với `maxUnavailable: 0`, `maxSurge: 1` trong
  [`values-prod.yaml`](<../../phase3 - information/deploy/values-prod.yaml>).
- Có PDB `minAvailable: 1` cho frontend và product-reviews trong
  [`pdb-checkout.yaml`](../../gitops/infrastructure/pdb-checkout.yaml).
- Product-reviews có gRPC readiness probe; traffic không bị gửi vào pod chưa sẵn sàng.
- Deadline 500 ms ngăn một dependency không critical giữ frontend request vô thời hạn.

### 5.2 Vì sao các lớp này chưa đủ

- HPA phản ứng sau tín hiệu CPU, không thể hấp thụ spike tức thời nếu không có spare Ready.
- `maxUnavailable: 0` bảo vệ rollout, không tạo sẵn capacity cho flash load.
- Readiness probe bảo vệ traffic khỏi pod hỏng; nó không làm pod khởi động nhanh hơn.
- PDB `minAvailable: 1` chỉ bảo vệ disruption tự nguyện, không cam kết luôn giữ cả hai replica khi overload.
- Deadline fail-fast giới hạn blast radius nhưng biến request chậm thành lỗi có chủ đích.

### 5.3 Mitigation đã có nhưng chưa đủ để đóng incident

Commit `a19174e5` ngày 28/07:

- tăng CPU request của product-reviews từ 100m lên 150m;
- tăng `consolidateAfter` của hai elastic NodePool từ 3 phút lên 10 phút.

Snapshot live sau điều tra đã thấy CPU request 150m và `consolidateAfter: 10m`. Đây là cải thiện hợp lý để
giảm CFS-throttle/eviction churn. Tuy nhiên trace trong tài liệu xảy ra sau khi commit đã tồn tại và vẫn cho
thấy cold scale/readiness gap. Vì vậy không được dùng riêng commit này để đánh dấu incident “Done”.

---

## 6. Phương án khắc phục an toàn nhất, không downtime

### Nguyên tắc

1. Không thay core checkout/cart để chữa một widget không critical.
2. Thêm capacity trước khi đổi traffic.
3. Mọi thay đổi đi qua GitOps, có diff nhỏ và rollback được.
4. Không route request vào pod/service mới trước khi readiness pass.
5. Không tăng deadline để che saturation.
6. Không chạy load test khi cluster đang rollout, scale-down hoặc thiếu node headroom.

### P0 — Khóa bằng chứng trước khi thay đổi

Không sửa production trước khi lưu được một run có thể tái tạo:

- thời gian bắt đầu/kết thúc theo UTC và +07;
- Locust users, spawn rate, duration, host và exact locustfile revision;
- raw Locust CSV;
- Jaeger trace IDs của success và timeout;
- `kubectl get hpa`, pod Ready, pod placement và Events trong đúng cửa sổ;
- CPU throttling, gRPC latency/error theo pod;
- traffic source tách load-generator khỏi organic ingress.

Việc này không tạo downtime và ngăn tối ưu sai dựa trên snapshot 17:54.

### P1 — Mitigation vận hành cho lần load test kế tiếp

**Đây là bước ít rủi ro nhất và nên làm trước:**

1. Tạm đặt `product-reviews-hpa.spec.minReplicas: 3` bằng GitOps cho cửa sổ benchmark đã lên lịch.
2. Chờ Deployment có đủ `3/3 Ready`; xác minh pod thứ ba đã schedule trên node hợp lệ và gRPC readiness pass.
3. Chỉ bắt đầu ramp Locust sau khi capacity đã ổn định.
4. Giữ nguyên `maxReplicas: 6`, CPU target và deadline ở lần chạy đầu để chỉ thay một biến.
5. Sau bài test, scale về baseline bằng một Git revert/PR riêng nếu evidence cho thấy 2 replica đủ cho traffic
   bình thường.

Thay `minReplicas` từ 2 lên 3 chỉ **thêm** pod, không thay thế hai pod đang phục vụ. Nếu pod thứ ba lại Pending,
load test phải dừng ở preflight; hệ thống hiện tại vẫn tiếp tục chạy trên hai pod cũ.

Không hạ CPU target, tăng max replicas hoặc tăng worker count cùng lúc. Làm nhiều thay đổi sẽ mất khả năng biết
thay đổi nào có tác dụng và có thể tăng contention với DB pool.

### P2 — Phân loại lỗi ở frontend nhưng giữ đúng semantics

API route nên bắt riêng:

- gRPC `DEADLINE_EXCEEDED`;
- gRPC `UNAVAILABLE`.

Nó cần ghi span/event có cấu trúc và trả một trạng thái “dependency temporarily unavailable” ổn định cho widget.
Không nên trả `200 []` một cách âm thầm: danh sách rỗng có nghĩa “sản phẩm chưa có review”, khác với “dịch vụ
review đang lỗi”. Che lỗi thành success sẽ làm sai UX và làm mất SLO signal.

Rollout frontend vẫn dùng `maxUnavailable: 0`, `maxSurge: 1`. Vì thay đổi chỉ chuẩn hóa error handling cho
widget đã có nhánh error, core page không cần dừng. Nếu muốn đổi response contract, phải dùng contract tương
thích ngược hoặc hai-phase rollout; không đổi shape một lần trong lúc pod cũ và mới cùng tồn tại.

### P3 — Sửa root architectural risk bằng bulkhead

Tách `AskProductAIAssistant` khỏi RPC đọc review:

1. Tạo deployment/service mới cho AI assistant, chưa nhận production traffic.
2. Chờ service mới Ready và chạy smoke request trực tiếp.
3. Canary một phần request AI hoặc chuyển endpoint AI bằng config/feature flag.
4. Giữ `GetProductReviews` và `GetAverageProductReviewScore` trên pool/service nhanh.
5. Quan sát error, latency, worker saturation và Bedrock timeout.
6. Chỉ xóa đường cũ sau một cửa sổ ổn định; rollback bằng cách trỏ AI về service cũ.

Parallel deploy giúp không thay pod product-reviews đang phục vụ. Nó cũng tạo bulkhead thật: request LLM chậm
không chiếm cùng 10 worker với request đọc review.

Phương án nhỏ hơn là tăng `max_workers`, nhưng **không được chọn mặc định**: database pool hiện cũng hữu hạn và
nhiều worker hơn có thể chỉ đẩy queue xuống DB/Bedrock, tăng CPU throttling và làm tail latency xấu hơn.

### P4 — Điều tra và cải thiện tốc độ scale

- Đo riêng: pending duration, image pull duration, app start duration, time-to-readiness.
- Dùng pre-scale để ép node/capacity xuất hiện trước sự kiện dự báo được.
- Kiểm tra image cache/pull policy và node headroom; không nới readiness để đưa pod chưa mở port vào Service.
- Giữ `startupProbe` là một cải thiện lifecycle/telemetry nếu cần, nhưng không coi nó là cách làm ứng dụng
  Ready nhanh hơn.
- Kiểm tra gRPC connection distribution. Nếu xác nhận long-lived connection làm lệch tải, thử
  headless service + client-side `round_robin` ở staging/canary trước; không đổi thẳng production vì đây là
  thay đổi routing.

### P5 — Deadline chỉ được chỉnh sau đo đạc

500 ms đang là fail-fast budget có chủ đích. Tăng lên 750 ms hoặc 1 giây có thể làm ít lỗi hơn nhưng cũng:

- giữ frontend request và worker lâu hơn;
- tăng concurrent in-flight requests;
- che queue saturation;
- đẩy tail latency về phía người dùng.

Chỉ đề xuất deadline mới khi có p95/p99 của RPC nhanh ở đúng load target và có end-to-end latency budget. Giá
trị mới phải được coi là một hypothesis qua canary, không phải “fix” mặc định.

---

## 7. Runbook rollout không downtime

### 7.1 Preflight

```bash
kubectl -n techx-tf3 get deploy frontend product-reviews
kubectl -n techx-tf3 get hpa product-reviews-hpa
kubectl -n techx-tf3 get pdb frontend-pdb product-reviews-pdb
kubectl -n techx-tf3 get pod -l opentelemetry.io/name=product-reviews -o wide
kubectl -n techx-tf3 get events --sort-by=.lastTimestamp
```

Điều kiện bắt đầu:

- tất cả replica hiện tại Ready, không restart bất thường;
- không có rollout khác đang chạy;
- node placement đáp ứng topology constraints;
- cấu hình Locust và cửa sổ evidence đã được chốt.

### 7.2 Thứ tự thay đổi

1. PR/commit chỉ tăng capacity nền cho cửa sổ benchmark.
2. Argo CD sync đúng revision.
3. Chờ replica bổ sung Ready; nếu Pending/readiness fail thì không bắn tải.
4. Chạy từng stage Locust với cấu hình đã lưu, không chỉnh users giữa stage mà không ghi lại.
5. Lưu raw CSV + trace + Events sau từng stage.
6. Thay đổi application/bulkhead ở PR khác, rollout canary/rolling sau khi capacity ổn định.

### 7.3 Gate quan sát

Không tự đặt threshold mới trong postmortem. Trước run phải ghi rõ target stage và acceptance criteria. Tối
thiểu cần kiểm:

- Ready replicas không tụt dưới baseline;
- không restart/OOM/Pending kéo dài ngoài cửa sổ khởi tạo đã đo;
- không có regression mới ở cart/checkout;
- số `DEADLINE_EXCEEDED` của product reviews giảm về acceptance target đã thống nhất;
- p95/p99 lấy từ raw load output và trace đúng cửa sổ;
- HPA desired/current, CPU throttling và distribution theo pod;
- AI latency/error tách khỏi read-review latency/error.

### 7.4 Rollback

- Dừng ramp Locust trước.
- Revert đúng Git commit thay đổi gần nhất; không `kubectl edit` để tránh drift.
- Sync Argo CD về revision trước.
- Chờ rollout status và xác minh endpoint Ready.
- Việc giảm temporary `minReplicas` chỉ thực hiện sau khi request đã về baseline; không scale-in giữa stage.

Với `maxUnavailable: 0`, một rollout thiếu surge capacity có thể **stalled** nhưng không được làm mất pod cũ.
Đây là trạng thái an toàn hơn việc ép rollout tiếp khi scheduler chưa tìm được chỗ.

---

## 8. Tiêu chí đóng incident

Incident chỉ được đánh dấu `Resolved` khi có đủ:

- [ ] Một run có thể tái tạo với raw Locust CSV và cấu hình load cố định.
- [ ] Trace IDs success/failure và Kubernetes Events cùng exact time window.
- [ ] Pod bổ sung Ready trước load hoặc time-to-readiness đã nằm trong budget được thống nhất.
- [ ] Product-review timeout đạt acceptance target ở tất cả stage bắt buộc.
- [ ] Core browse/cart/checkout không regression.
- [ ] AI traffic được tách bulkhead, hoặc có evidence chứng minh shared pool không gây contention tại target.
- [ ] Dashboard/Prometheus duplicate-series gap đã được xử lý trước khi dùng RPS metric làm nguồn pass/fail.
- [ ] Có bằng chứng rollback rehearsal hoặc rollback path đã được xác minh.

Việc “đổi config xong” hoặc “Grafana đang xanh” không tự động thoả các tiêu chí trên.

---

## 9. Action items đề xuất

| Ưu tiên | Action | Loại | Downtime dự kiến | Evidence hoàn thành |
|---|---|---|---|---|
| P0 | Lưu exact-window Locust CSV, config, trace IDs và K8s Events | Observability | Không | Evidence pack tái tạo được |
| P0 | Tách organic ingress khỏi load-generator trong traffic dashboard | Observability | Không | Query/dashboard có `traffic_source` rõ ràng |
| P1 | Pre-scale product-reviews trước scheduled load, gate trên replica Ready | GitOps/Ops | Không | 3/3 Ready trước ramp |
| P1 | Chuẩn hóa mapping `DEADLINE_EXCEEDED`/`UNAVAILABLE`, không giả `200 []` | Frontend | Không với rolling update | Widget degraded đúng semantics, trace có marker |
| P2 | Tách AI assistant sang deployment/service riêng | Architecture | Không với parallel deploy | Read-review không dùng chung AI worker pool |
| P2 | Đo startup/readiness và xử lý scheduling/image pull bottleneck | Platform | Không | Time-to-ready breakdown |
| P2 | Xác minh gRPC connection distribution, canary `round_robin` nếu cần | Reliability | Không với canary | Per-pod request/CPU balance |
| P2 | Sửa OTLP/Prometheus duplicate-series hoặc temporality | Observability | Không | RPS khớp raw generator/access logs |
| P3 | Review deadline bằng p99 và latency budget, chỉ sau các bước trên | App/SLO | Không với canary | Decision record có before/after |

---

## 10. Kết luận vận hành

Sự cố này là một **capacity-arrival gap dưới synthetic load**:

- HPA phát hiện tải nhưng replica mới không Ready đủ nhanh;
- deadline 500 ms biến tail latency thành lỗi có kiểm soát;
- shared worker pool với AI là rủi ro khuếch đại cần bulkhead;
- chưa có căn cứ nói organic web traffic tăng.

Can thiệp ít rủi ro nhất là pre-scale trước load test và giữ nguyên các biến khác để đo lại. Sửa bền vững nhất
là tách đường AI chậm khỏi đường đọc review nhanh bằng parallel deployment. Tăng deadline ngay chỉ làm biểu
đồ ít đỏ hơn, không giải quyết việc capacity đến trễ hoặc worker bị tranh chấp.

---

## 11. Cập nhật triển khai (28/07/2026)

**Đề xuất trong [PR #531](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/531), CHƯA merge**
(không đổi manifest/HPA/cluster, chỉ app code — khi merge sẽ đi qua pipeline `build-push-ecr.yml` +
bump-image PR hiện có, không tay `helm upgrade`):

- **P2 — phân loại lỗi ở frontend, giữ semantics:**
  [`pages/api/product-reviews/[productId]/index.ts`](<../../phase3%20-%20information/techx-corp-platform/src/frontend/pages/api/product-reviews/[productId]/index.ts>)
  và [`pages/api/product-reviews-avg-score/[productId]/index.ts`](<../../phase3%20-%20information/techx-corp-platform/src/frontend/pages/api/product-reviews-avg-score/[productId]/index.ts>)
  giờ bắt riêng gRPC `DEADLINE_EXCEEDED`/`UNAVAILABLE`, trả `503 { error: "DEPENDENCY_UNAVAILABLE" }` thay
  vì để lỗi rơi xuống thành 500 không phân loại. Lỗi khác vẫn `throw` để `InstrumentationMiddleware` xử lý
  như cũ (không đổi hành vi ngoài hai mã lỗi này).
  - **Bug phát hiện thêm khi verify (ngoài phạm vi §6 gốc):**
    [`utils/Request.ts`](<../../phase3%20-%20information/techx-corp-platform/src/frontend/utils/Request.ts>)
    (dùng chung cho MỌI gateway phía client) trước đây **không kiểm tra `response.ok`** — parse JSON body
    bất kể status code rồi coi là thành công. Nếu không vá, response `503 { error }` ở trên sẽ bị client
    nuốt thành "thành công" và rơi về `[]` — đúng anti-pattern §6/P2 cấm ("không trả 200 [] âm thầm"), chỉ
    khác là ở tầng client thay vì route handler. Đã thêm kiểm tra `!response.ok` → `throw`. Đã rà toàn bộ
    `pages/api/*` (grep `res.status(4`/`res.status(5`) xác nhận không có route nào cố ý dựa vào hành vi cũ.
- **P3 — admission control (một phần, interim, KHÔNG phải bulkhead thật):**
  [`product_reviews_server.py`](<../../phase3%20-%20information/techx-corp-platform/src/product-reviews/product_reviews_server.py>)
  thêm `threading.BoundedSemaphore` (`AI_ASSISTANT_MAX_CONCURRENCY`, mặc định `4`, env-tunable) quanh
  `AskProductAIAssistant`. Vượt cap → chờ tối đa `AI_ASSISTANT_ADMISSION_TIMEOUT_SECONDS` (mặc định
  **0.05s**, xem lý do đổi từ 2s ở §11.1 blocker 1) rồi shed nhanh bằng `FALLBACK_SUMMARY_MESSAGE` có sẵn.
  **Đây KHÔNG đảm bảo "≥6 worker luôn rảnh cho reads"** — semaphore chỉ chạy TRONG handler, tức SAU khi
  `ThreadPoolExecutor` (FIFO) đã phát task cho 1 worker rồi; nó không sắp lại thứ tự queue dùng chung. Dưới
  backlog AI lớn, read RPC vẫn phải chờ phía sau các task AI đã nộp trước nó trong cùng queue — xem số đo
  thật ở §11.1. Không đổi `max_workers` (đúng khuyến nghị §6: không dùng tăng worker làm fix mặc định).
  **P3 đầy đủ (tách executor/service AI riêng thật) vẫn CHƯA làm** — cần routing change + canary, không
  làm trong PR này.
- **Câu hỏi rate-limit ở `values-prod.yaml` (Mandate #19, `frontend-proxy`):** đã kiểm tra —
  `BROWSE_RATE_LIMIT_ENFORCED_PERCENT` và `LOCAL_RATE_LIMIT_ENFORCED_PERCENT` đều `"0"` (shadow mode,
  không enforce), nên **không phải nguyên nhân** của lỗi trong postmortem này. Đây cũng là component
  `frontend-proxy` (Envoy, biên browse traffic) chứ không nằm trên đường gọi `frontend → product-reviews`
  qua gRPC nội bộ.

### 11.1 Review độc lập trên PR #531 (28/07/2026) — 5 gap tìm được, đã xử lý

Một review độc lập (không phải người viết PR) chấm **NO-GO** với 5 blocker cụ thể. Cả 5 đều verify được và
đúng; đã sửa và push lên cùng PR:

1. **Semaphore là admission control, không phải bulkhead thật — CONFIRMED bằng grpc server thật, không
   phải giả lập.** `BoundedSemaphore` chỉ acquire được SAU KHI `ThreadPoolExecutor` dùng chung đã phát RPC
   cho 1 worker theo FIFO; nó không chặn được một backlog AI lớn xếp hàng trước 1 read RPC trong cùng
   queue. Đã dựng lại bằng `grpc.server(futures.ThreadPoolExecutor(max_workers=10))` thật (không phải
   `threading.Semaphore` tự chế) chạy đúng pattern cap=4/admission=0.05s, bắn N request AI đồng thời rồi đo
   độ trễ 1 `FastRead` đến giữa lúc burst:

   | N request AI đồng thời | Độ trễ FastRead đo được |
   |---|---|
   | 10 | ~34 ms |
   | 30 | ~178 ms |
   | 100 | **~758 ms — VƯỢT** `PRODUCT_REVIEWS_DEADLINE_MS=500ms` |

   Kết luận: mitigation này giúp thật với burst vừa (≤30 AI request đồng thời), nhưng **không đảm bảo**
   dưới backlog AI lớn/bền — đúng như blocker nêu. Đã sửa comment trong code + tài liệu này để không còn
   overclaim "đảm bảo ≥6 worker rảnh" — giờ ghi rõ đây là admission control có giới hạn, P3 đầy đủ (tách
   executor/service) vẫn là fix cần làm để có isolation thật.
2. **React Query retry mặc định (3 lần, backoff) có thể tự khuếch đại tải vào đúng lúc dependency đang
   quá tải** — mở widget 1 lần có thể bắn tới 4 lần × 2 query = 8 request trong lúc outage. Đã sửa
   [`ProductReview.provider.tsx`](<../../phase3%20-%20information/techx-corp-platform/src/frontend/providers/ProductReview.provider.tsx>):
   thêm `retry` riêng cho cả 2 query — **không retry khi lỗi có `status === 503`** (đã biết dependency
   unavailable, retry ngay chỉ tổ tạo thêm tải), lỗi khác vẫn được retry tối đa 2 lần như trước.
3. **Trạng thái ghi "đã triển khai" trong khi PR chưa merge** — sai, đã sửa dòng trạng thái đầu tài liệu +
   phần mở §11 thành "đề xuất qua PR #531, chưa merge/build/deploy".
4. **Tài liệu ghi admission timeout mặc định 2s trong khi code đã đổi thành 0.05s** (từ lần tự-review
   trước) — tài liệu bị quên cập nhật sau khi sửa code. Đã đồng bộ lại, hiện tài liệu và code đều ghi
   `0.05s`.
5. **`Request.ts` gọi `JSON.parse` trước khi kiểm tra `response.ok`** — một response lỗi không đảm bảo là
   JSON (vd 500/502 dạng HTML từ framework) sẽ làm `JSON.parse` ném `SyntaxError` thô, mất luôn HTTP status
   mà bản vá này cần giữ lại. Đã bọc `try/catch` quanh `JSON.parse`, giữ `response.status` dù body không
   parse được. Verify bằng HTTP server thật (không mock) với đúng 4 case blocker yêu cầu — JSON error, text
   error, empty 204, success — cả 4 pass (xem §11.2).

### 11.2 Test local đã chạy (chưa chạy trên cluster/production)

- `tsc --noEmit`: sạch (chạy lại sau mọi sửa ở §11.1).
- `next build` (production build thật): thành công (chạy lại sau mọi sửa).
- `next start` cục bộ với `PRODUCT_REVIEWS_ADDR` trỏ vào địa chỉ đen (blackhole) +
  `PRODUCT_REVIEWS_DEADLINE_MS=300`: cả hai endpoint vẫn trả đúng `503 { "error": "DEPENDENCY_UNAVAILABLE" }`
  sau khi thêm retry policy; trang `/product/:id` (SSR) vẫn `200` — không regression.
- `utils/Request.ts` biên dịch riêng (`tsc` standalone) rồi chạy với 1 HTTP server thật (Node `http`,
  không mock `fetch`) qua đúng 4 case blocker 5 nêu — JSON error (503), text/HTML error (500), empty
  success (204), success (200) — cả 4 đúng như kỳ vọng, không còn `SyntaxError` rò ra ngoài.
- Blocker 1: dựng `grpc.server` + `ThreadPoolExecutor` THẬT (không phải giả lập bằng `threading.Semaphore`
  tay) để đo, số liệu ở bảng §11.1.
- Không import/chạy được `product_reviews_server.py` nguyên bản cục bộ — `database.py` mở `psycopg2` pool
  thật tới `DB_CONNECTION_STRING` ngay lúc import module, không có Postgres/RDS cục bộ để trỏ vào. Không
  thay thế được test tích hợp thật (cần cluster + Bedrock + RDS).
- Chưa chạy: pytest/integration cho product-reviews trên cluster thật, load test Locust theo runbook §7,
  `helm template` (không cần — không đổi chart/values lần này).

### 11.3 Review vòng 2 trên PR #531 (28/07/2026) — 2 gap correctness/rollout mới, đã xử lý

Vòng review thứ hai (sau khi 5 gap ở §11.1 đã sửa) đánh giá NO-GO nhẹ vì 2 vấn đề mới, cả 2 verify đúng:

1. **Không tương thích old/new client trong rolling rollout — đây chính là điều §6-P2 gốc đã cảnh báo
   trước ("nếu muốn đổi response contract, phải dùng contract tương thích ngược hoặc hai-phase rollout;
   không đổi shape một lần trong lúc pod cũ và mới cùng tồn tại") mà lần triển khai đầu đã bỏ sót.**
   `frontend` rollout `maxUnavailable:0, maxSurge:1` nên pod cũ/mới cùng tồn tại một lúc; body lỗi
   `503 { error: "DEPENDENCY_UNAVAILABLE" }` (JSON) từ pod MỚI, nếu bị 1 tab trình duyệt đang chạy bundle
   client CŨ nhận (do Service cân tải qua cả pod cũ/mới), sẽ bị `Request.ts` **phiên bản cũ** parse
   `JSON.parse` vô điều kiện thành "thành công" → `ProductReview.provider.tsx` biến thành `[]` → hiển thị
   "No reviews yet" — **đúng chính lỗi semantics PR này được tạo ra để ngăn**, chỉ là tái diễn qua đường
   version-skew khi deploy thay vì qua Request.ts bug (đã vá ở §11.1 blocker 5).
   **Đã sửa:** đổi body lỗi 503 từ JSON sang **plain text** (`res.status(503).send('DEPENDENCY_UNAVAILABLE')`)
   ở cả hai route. `JSON.parse` trên chuỗi plain text KHÔNG hợp lệ JSON sẽ luôn ném lỗi — cả client cũ lẫn
   mới đều `throw` đúng, không còn client nào "thành công" âm thầm. Verify bằng test thật: biên dịch riêng
   cả bản `Request.ts` HIỆN TẠI và bản gốc TRƯỚC PR (`git show origin/main:...`) từ TypeScript, chạy cả
   hai chống lại 1 HTTP server thật trả `503` plain text — cả bản cũ và bản mới đều `throw`, không còn
   route nào "swallow" thành success.
2. **`Request.ts` (bản sửa ở §11.1 blocker 5) nuốt luôn lỗi parse của response 2xx.** Bản vá blocker 5 bọc
   `try/catch` quanh `JSON.parse` để không rò `SyntaxError` từ body lỗi non-JSON — nhưng bọc luôn cho CẢ
   response `200`, nghĩa là nếu server trả `200` với body hỏng/không phải JSON (bug thật), code cũ sẽ nuốt
   lỗi và coi là "thành công" với `data=undefined` — regression so với hành vi gốc (trước mọi PR này, một
   `200` với body hỏng vốn dĩ ĐÃ ném lỗi qua `JSON.parse` không bọc). **Đã sửa:** đưa nhánh `!response.ok`
   lên trước; chỉ bọc `try/catch` cho non-2xx (nơi đã có status code thật để phân loại), nhánh thành công
   giữ nguyên `JSON.parse` không bọc như code gốc — một `200` body hỏng vẫn `throw` đúng như trước khi có
   PR này. Verify bằng test thật: 1 route giả `200` + body `<not json>` → xác nhận vẫn `throw SyntaxError`,
   không bị nuốt thành success; route thành công bình thường vẫn hoạt động đúng cho cả client cũ/mới.

Ngoài 2 điểm trên, review vòng 2 cũng lưu ý PR title/description gọi semaphore là "bulkhead" trong khi
code/docs (§11.1) đã tự nhận đây chỉ là admission control — đã sửa PR description + comment trên GitHub
cho khớp thuật ngữ.

Commit sửa vòng 2 + test (biên dịch/chạy `Request.ts` cũ và mới chống 1 HTTP server thật, `tsc --noEmit`,
`next build`, live functional test qua `PRODUCT_REVIEWS_ADDR` đen) — không regression.

### 11.4 Deploy thật (28/07/2026) — PR #531 + #533 (Trivy CVE) + #535/#538 (bump-image) đã merge

PR #531 (P2 + admission control) đã được review và merge vào `main`. Build image sau merge fail Trivy
gate vì 2 CVE HIGH sẵn có trong dependency (không liên quan code sửa): `brace-expansion` (CVE-2026-14257)
và `postcss` (GHSA-r28c-9q8g-f849) — cả 2 đã có bản vá, xử lý ở PR #533 (bump version qua `overrides` có
sẵn trong `package.json`). Build lại pass. Bot tạo PR bump-image #535 (`frontend`) và #538 (`product-reviews`,
phải trigger `workflow_dispatch` scoped thủ công vì lần build đầu fail ở job `frontend` khiến job tạo PR bị
skip dù `build-scan (product-reviews)` đã pass). Cả 2 đã merge, ArgoCD auto-sync **Synced/Healthy**, verify
trực tiếp trên cluster (`kubectl`, profile read-only `nvtank-readonly`): `frontend` 3/3 Ready 0 restart
(HPA đang scale theo CPU, không liên quan), `product-reviews` 2/2 Ready 0 restart, storefront CloudFront
vẫn `200`. **P2 + admission control giờ đã LIVE trên production.**

## 12. P4 — đo startup/readiness thật (28/07/2026, dữ liệu từ chính đợt rollout trên)

Tận dụng đúng lúc rollout PR #531 lên production để đo P4 bằng dữ liệu thật thay vì suy đoán (nguồn:
`kubectl get events`/`get pod -o json` qua tunnel SSM, profile read-only).

### 12.1 Time-to-Ready breakdown — 2 pod đầu của `product-reviews`

| Pod | Created→Scheduled (pending) | Pulling→Pulled | Started→Ready (app+probe) | **Tổng Created→Ready** |
|---|---|---|---|---|
| `...4d5wp` (pod đầu tiên) | **39s** (2 lần `FailedScheduling`: topology spread + taint + node affinity, phải chờ Karpenter tạo node mới) | 11.7s | 22s | **77s** |
| `...vrxqm` (pod thứ hai) | **0s** (schedule tức thì — node từ Karpenter đã sẵn) | 5.6s | 21s | **29s** |

**Bằng chứng trực tiếp cho khuyến nghị P1 (pre-scale):** pod ĐẦU của một scale event mất 77s để Ready,
chủ yếu do phải chờ Karpenter launch node mới từ đầu (`elastic-ondemand-fallback-4lmlh`, node
`ip-10-0-37-137` — instance `t3a.medium`, `capacity-type: on-demand`, tức Karpenter fallback từ spot sang
on-demand lúc đó). Pod THỨ HAI, chạy ngay sau khi node đã tồn tại, chỉ mất 29s — nhanh hơn 2.7 lần. Đây
đúng là cơ chế P1 khai thác: pre-scale trước khi bắn tải để "trả phí" node-provisioning TRƯỚC cửa sổ đo,
không phải trong lúc đo.

### 12.2 So sánh với `frontend`

| Pod | Created→Scheduled | Pulling→Pulled | Started→Ready | Tổng |
|---|---|---|---|---|
| `...d4vlw` | 0s | 18.3s | 12s | 32s |
| `...v79n7` | 0s | 18.2s | 11s | 31s |

`frontend` không bị pending (schedule tức thì cả 2 lần) nhưng pull image chậm hơn `product-reviews` rõ
rệt (~18s vs ~6-12s) — image `frontend` nặng hơn nhiều (227MB vs 65MB). App-start-to-Ready của `frontend`
(~11-12s) cũng nhanh hơn `product-reviews` (~21-22s) — hợp lý vì `product-reviews` init nhiều hơn (gRPC
server, Bedrock client, DB connection pool, flagd provider).

### 12.3 Node headroom lúc đo

`kubectl top nodes` lúc đo: CPU 1-19%, memory 3-58% trên các node hiện có — khớp với ghi nhận cost-review
trước đó (cluster ~45% CPU **request** nhưng chỉ ~6.7% dùng thật). Nghĩa là nút thắt của time-to-Ready
**không phải** thiếu CPU/memory trên node hiện có, mà là **thiếu sẵn 1 node mới khi cần** — đúng bản chất
"capacity-arrival gap" §3 đã kết luận, giờ có số đo thật xác nhận thay vì suy luận định tính.

### 12.4 Chưa đo được (cần thêm)

- Connection distribution giữa các pod gRPC (P4 gốc có đề cập) — cần Prometheus/Grafana query per-pod
  request rate trong lúc có tải thật, chưa làm ở đợt này vì không có tải đủ lớn tại thời điểm rollout.
- Startup breakdown chi tiết BÊN TRONG container (`product-reviews` mất 21-22s giữa Started và Ready —
  chưa tách được bao nhiêu là app init code chạy thật vs. bao nhiêu là do `readinessProbe`
  `initialDelaySeconds:5, periodSeconds:10` tự nó làm chậm phép đo, vd. app có thể Ready ở giây thứ 16
  nhưng probe attempt tiếp theo chỉ rơi vào giây 25 → số đo Ready là do lịch probe, không phải do app
  chậm). Cần thêm log timestamp "server started" bên trong app để tách 2 nguyên nhân.

## 13. P0 + P1 — load test có kiểm soát trên production (28/07/2026)

Thực hiện đúng runbook §7: preflight → PR pre-scale (P1) → chờ Ready → chạy Locust theo từng stage, không
đổi biến giữa stage mà không ghi lại → lưu evidence → revert pre-scale.

### 13.1 Preflight (§7.1)

Trước khi đổi gì: `frontend` 2/2 Ready, `product-reviews` 2/2 Ready, không restart bất thường, PDB
(`frontend-pdb`, `product-reviews-pdb`, `frontend-proxy-pdb`) đều `minAvailable:1`, không có ArgoCD sync
nào đang chạy (`Synced`/`Healthy`), không rollout nào khác đang diễn ra. Đạt điều kiện bắt đầu.

### 13.2 P1 — pre-scale

PR [#543](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/543): `product-reviews-hpa.minReplicas`
2→3, đánh dấu tạm thời ngay trong annotation. Merge xong, ArgoCD sync tới đúng revision (verify bằng
`status.sync.revision` khớp `git rev-parse origin/main`), chờ `kubectl rollout status` — pod thứ 3
(`product-reviews-67bbd5c84f-nw6qv`) lên `3/3 Ready`, 0 restart. Đạt điều kiện §7.2 bước 3 trước khi bắn
tải.

### 13.3 Locust — 3 stage, dùng REST API của load-generator (`kubectl port-forward svc/load-generator 8089`,
không qua route public — đúng Mandate #1)

| Stage | Users | Spawn rate | Thời lượng | RPS đo được | `fail/s` | CPU product-reviews | HPA |
|---|---|---|---|---|---|---|---|
| 1 | 60 | 3/s | 3 phút | ~14-17 | **0.0 suốt** | 19-40% | không scale (3/3 giữ nguyên) |
| 2 | 200 | 10/s | 6 phút | ~38-45 | **0.0 suốt** | 25-45% | không scale (3/3 giữ nguyên) |
| 3 | 500 | 20/s | 7 phút | ~92-118 | 0-0.6 (đỉnh lúc scale) | tới **94%/75%** | **scale 3→4** (HPA `SuccessfulRescale`) |

Stage 1+2 hoàn toàn sạch (0 lỗi cả 2 cửa sổ) — hệ thống hấp thụ tốt tới 200 user đồng thời sau khi CPU
request tăng 100m→150m (commit `a19174e`) làm HPA "khó" scale hơn trước (cần tải lớn hơn mới chạm 75%
target so với lúc incident gốc).

### 13.4 Stage 3 — tái hiện đúng capacity-arrival gap, fix hoạt động đúng thiết kế

Ở 500 user, CPU vượt target → HPA scale `product-reviews` 3→4. Pod thứ 4
(`product-reviews-67bbd5c84f-6pvx4`) đi qua đúng chuỗi sự kiện như §12 đã đo: `FailedScheduling` (topology
spread + taint + node affinity) → Karpenter tạo node mới (`elastic-ondemand-fallback-grsxp`) →
`Scheduled` sau ~16-18s → pull image 11.8s → `Started` → readiness probe fail lần đầu → **Ready sau ~69s
kể từ lúc bắt đầu FailedScheduling** — khớp tầm với con số 77s ở §12 (chênh lệch do node headroom sẵn có
khác nhau giữa 2 lần đo). Trong đúng cửa sổ pod thứ 4 chưa Ready, `fail/s` nhích lên 0.3-0.6 rồi về 0 ngay
khi pod Ready — **đúng cơ chế "capacity-arrival gap" §3 mô tả, tái hiện được bằng tải thật**.

Khác biệt quan trọng so với sự cố gốc: lỗi trong cửa sổ này được client Locust ghi nhận là
**`503 Service Unavailable` cho `/api/product-reviews/*`** (xác nhận qua `stats/requests` API của Locust
lẫn log `product-reviews` — không thấy `500` mới nào phát sinh sau lúc deploy), đúng route `catch` mới
thêm ở P2 — **không còn rơi về `500` không phân loại như trước khi vá**. `checkout`, `cart`,
`product-catalog` (`kubectl get pod`) **0 restart suốt cả 3 stage**.

### 13.5 Phát hiện mới (ngoài phạm vi §6 gốc): AWS Bedrock throttle, không phải bug product-reviews

Đọc log `product-reviews` (`kubectl logs`) trong đúng cửa sổ Stage 3, thấy rõ:

```text
WARNING [guardrails.fallback] - Retrying __main__.call_candidate_bedrock in 0.4s seconds as it raised
ThrottlingException: An error occurred (ThrottlingException) when calling the Converse operation
(reached max retries: 4): Too many requests, please wait before trying again.
```

Đây là **AWS Bedrock tự giới hạn tốc độ (rate limit) trên API `Converse`** khi nhiều câu hỏi AI gửi đồng
thời — không phải lỗi ở code product-reviews. Giải thích đúng lý do trace `ask_product_ai_assistant`
trong Jaeger mất 15-25 giây (gần sát `PRODUCT_AI_DEADLINE_MS=15000`) và có nhiều span lỗi: mỗi lần
`ThrottlingException` là 1 lần retry (`tenacity`, decorator `@with_fallback`) trước khi rơi về
`FALLBACK_SUMMARY_MESSAGE`. **Đây KHÔNG làm hỏng trải nghiệm người dùng** — `AskProductAIAssistant` luôn
trả response hợp lệ (thật hoặc fallback), không phải lỗi HTTP.

**Bằng chứng admission control (PR #531) đang hoạt động đúng thiết kế dưới tải thật:** cùng cửa sổ, log
xuất hiện lặp lại hàng trăm dòng:

```text
WARNING - AskProductAIAssistant: concurrency limit (4) reached, shedding load for product_id:X
```

Xác nhận cơ chế semaphore cap=4 đang chủ động shed bớt request AI dư thay vì để tất cả dồn vào Bedrock
(vốn đã throttle) làm tình hình tệ hơn — đúng mục đích thiết kế ở §11.1.

### 13.6 Dọn dẹp sau test

Dừng Locust (`/stop`) rồi swarm lại baseline. Revert PR
[#545](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/545): `product-reviews-hpa.minReplicas`
3→2, đúng kế hoạch tạm thời đã ghi ở PR #543 (không giữ làm baseline mới nếu không có evidence riêng cho
việc đó).

### Còn thiếu để đóng incident theo §8

- ✅ P0 — evidence pack thật đã lấy (§13): Locust config/kết quả từng stage, Events/HPA đúng cửa sổ, log
  `product-reviews` xác nhận nguyên nhân (Bedrock throttle) tách biệt khỏi capacity-arrival gap.
- ✅ P1 — đã áp dụng thật cho lần load test này (§13.2), đã revert sau khi xong (§13.6).
- ✅ P4 — đã đo (§12), dữ liệu thật.
- **P3 đầy đủ** (tách executor/deployment AI riêng thật + canary) — **vẫn CHƯA làm, vẫn là việc quan
  trọng nhất còn lại**. §11.1 blocker 1 + §13.4/§13.5 giờ có bằng chứng kép: admission control giảm thiệt
  hại nhưng (a) không đảm bảo cô lập dưới backlog lớn (§11.1), và (b) root cause thật của độ trễ AI là
  Bedrock rate limit — tách AI ra service/executor riêng sẽ giúp cấu hình concurrency/backoff cho path AI
  độc lập khỏi path đọc nhanh, không phải chỉ giảm blast radius.
- **P5** (deadline review) — giờ CÓ số liệu thật để làm: p95/p99 của Stage 2 (200 user, sạch) làm baseline
  "khoẻ mạnh", so với Stage 3 (500 user, có capacity-arrival gap) để quyết định deadline hợp lý — **chưa
  làm phép tính chính thức**, cần trích p95/p99 chính xác từ Locust CSV (chưa export) thay vì chỉ nhìn
  RPS/fail tổng hợp đã ghi ở đây.
- Nên xin quota tăng cho Bedrock `Converse` API (§13.5) nếu muốn AI assistant chịu được tải tương đương
  Stage 3 mà không throttle — việc này ngoài phạm vi CDO02/postmortem này (thuộc AIO02).
