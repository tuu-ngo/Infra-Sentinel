# Mandate #19 — Kế hoạch đóng YC#2 (nâng trần, không thêm node)

**Trạng thái:** YC#2 báo **chưa qua**. Đây là kế hoạch để đóng nó, viết từ số đo của 4 vòng
ladder chứ không phải phỏng đoán.

**Ký:** CDO01 — TF3 · 30/07/2026

---

## 1. Chẩn đoán — chỉ MỘT cổng đang chặn

Cổng đánh giá có 4 điều kiện. Ở bản `tuned3`, xét từng stage:

| Stage | RPS | browse% | browse p95 | cart% | checkout% | Cổng trượt |
|---:|---:|---:|---:|---:|---:|---|
| u200 | 40,6 | 99,850 | ✅ | 99,892 | 99,888 | — **PASS** |
| u400 | 80,9 | **98,944** | ✅ | 100 | 99,731 | browse |
| u600 | 122,2 | **99,008** | ✅ | 100 | 99,929 | browse |
| u800 | 158,7 | **98,160** | ✅ | 100 | 99,690 | browse |
| u1000 | 173,3 | **98,583** | ✅ 389,7ms | 100 | 99,667 | browse |
| u1400 | 277,7 | **97,390** | ✅ | 99,995 | 99,549 | browse |
| u1800 | 355,7 | **97,325** | ✅ | 99,992 | 99,176 | browse |
| u2400 | 445,3 | **96,043** | ✅ | 99,787 | **89,402** | browse + checkout |

**Ba kết luận rút thẳng từ bảng này:**

1. **`browse_success` là cổng duy nhất chặn ở u400–u1800.** cart, checkout và browse p95 đều qua.
   `browse p95 = 389,7ms` so với ngưỡng 1000ms — dư **2,6 lần** biên. Không phải bài toán tốc độ.

2. **`tuned3` thật ra khoẻ hơn baseline rất nhiều ở nơi quan trọng nhất.** Ở u1800:
   checkout **7,125% → 99,176%**, throughput **298 → 356 RPS**. Nhưng vì thước đo là "stage cao
   nhất qua **cả 4** cổng", một cổng trượt là xoá sạch phần còn lại.

3. **Trần đo được của `tuned3` (u200) THẤP HƠN baseline (u1000).** Phải nói thẳng điều này chứ
   không giấu: theo đúng thước đo của directive, bản tối ưu **làm tụt trần**. Lý do nằm ở §2.

---

## 2. Vì sao browse hỏng — hai chế độ khác hẳn nhau

Tách lỗi theo thời điểm trong cửa sổ đo thì lộ ra **hai bài toán khác nhau**, và chúng cần hai
cách chữa khác nhau:

### Chế độ A — u400 → u1000: lỗi dồn thành cụm ngắn, hệ **chưa** bão hoà

| Stage | Cụm lỗi | Dài | Vị trí trong cửa sổ đo |
|---|---|---:|---|
| u400 | `09:22:27 → 09:22:35` | **8s** | +263s (giữa cửa sổ) |
| u600 | `09:28:51 → 09:29:56` | 65s | +204s |
| u800 | `09:34:12 → 09:37:02` | 170s | +90s |
| u1000 | `09:43:58 → 09:44:12` | **14s** | +240s |

> ⚠️ **Không được dùng lý do "nhiễu lúc tăng tải".** Cụm lỗi nằm **+90s đến +263s vào giữa cửa sổ
> đo**, tức đã qua giai đoạn ổn định từ lâu. Đây là sự kiện steady-state thật.

Tài nguyên tại u1000 lúc đó **còn thừa nhiều**:

```
frontend-hpa          cpu:  79%/65%    2/16 →  10 replica   (còn 6)
product-catalog-hpa   cpu:  61%/65%    2/12 →   8 replica   (dưới cả ngưỡng)
product-reviews-hpa   cpu:  77%/75%    2/6  →   2 replica   ← trên ngưỡng mà KHÔNG scale
```

**Hệ không hết sức. Nó bị gián đoạn.** 580 lỗi `/api/products/[id]` dồn trong **14 giây** rồi
sạch hoàn toàn — đó là dấu hiệu của **thay đổi tập endpoint**, không phải quá tải.

**Nguyên nhân xác định được:**

`round_robin` được ship ở PR #660/#664 **mà không kèm `retryPolicy`**. Xem
`src/frontend/gateways/rpc/grpcChannel.ts` — service config hiện chỉ có `loadBalancingConfig`,
không có `methodConfig`.

Đây là chỗ đánh đổi bị bỏ sót:

| | `pick_first` (trước) | `round_robin` (nay) |
|---|---|---|
| Client giữ kết nối tới | **1** pod | **tất cả** pod |
| Một pod bị thay | chỉ client đang ghim vào nó bị ảnh hưởng | **mọi client** đều dính một phần request |
| Cửa sổ dính lỗi | tới khi backoff xong (~60s, xem postmortem 0017) | tới khi phân giải lại DNS |

`dns_min_time_between_resolutions_ms: 5000` nghĩa là sau khi một pod biến mất, client vẫn có thể
gửi vào địa chỉ chết **tới 5 giây**. **Cụm lỗi 8 giây ở u400 khớp đúng con số này.**

Nói cách khác: bản vá đã đổi **một pod chịu toàn bộ rủi ro** thành **mọi pod chia nhau rủi ro** —
đúng ý đồ về mặt dung lượng, nhưng thiếu lớp đệm bắt buộc đi kèm.

### Chế độ B — u1400 trở lên: bão hoà thật

```
u1800:  frontend-hpa         cpu: 142%/65%   16/16  ← KỊCH TRẦN
        product-catalog-hpa  cpu: 105%/65%   12/12  ← KỊCH TRẦN
        product-reviews-hpa  cpu:  79%/75%    5/6
        13 pod Pending
```

Ở đây lỗi **rải đều suốt cửa sổ**, không còn thành cụm. Và nguồn lỗi **đổi chủ**:

| Stage | `/api/products/[id]` | `/api/product-reviews/[id]` | Tỉ trọng reviews |
|---|---:|---:|---:|
| u1000 | 580 | 149 | 20% |
| u1400 | 577 | **1581** (1224×503 + 357×500) | **73%** |
| u1800 | 539 | **2268** (1926×503 + 342×500) | **81%** |

**`product-reviews` là nguồn lỗi browse lớn nhất ở tải cao, không phải `product-catalog`.**
Và nó là service bị cấp phát hẹp nhất trong toàn hot path:

| Service | maxReplicas | target CPU |
|---|---:|---:|
| frontend | 16 | 65% |
| checkout | 14 | 65% |
| product-catalog | 12 | 65% |
| **product-reviews** | **6** | **75%** |

---

## 3. Kế hoạch — 5 việc, theo đúng thứ tự

> **Nguyên tắc:** việc 0 phải xong trước việc 2, vì nếu đoán sai nguyên nhân 503 thì việc 2 không
> những vô ích mà còn có thể làm tệ hơn.

### Việc 0 — Xác định 503 của `product-reviews` đến từ đâu *(30 phút, bắt buộc trước)*

Ba khả năng, ba cách chữa **ngược nhau hoàn toàn**:

| Giả thuyết | Nếu đúng thì | Thêm replica sẽ |
|---|---|---|
| Semaphore giới hạn đồng thời (PM-0016) từ chối khi đầy | đây là **load shedding có chủ đích** của service | ✅ giúp |
| Bedrock rate-limit, fallback Tier-2 không phủ route này | lỗi ở **tầng LLM**, không phải dung lượng pod | ❌ vô ích |
| Cạn connection pool PostgreSQL (REL-05) | mỗi pod mới lại **mở thêm** connection | 🔴 **làm tệ hơn** |

Cách xác định:

```sh
kubectl -n techx-tf3 logs -l app.kubernetes.io/name=product-reviews --tail=2000 \
  | grep -iE "503|semaphore|rate.?limit|throttl|pool|circuit|bedrock"
```

Đối chiếu thêm: CLAUDE.md ghi rõ Tier-2 fallback **mới chỉ kiểm chứng đường GHI**, đường ĐỌC chưa
test end-to-end. Nếu 503 đến từ Bedrock thì việc này thuộc AIO02, không phải CDO02, và phải bàn giao.

**Không làm việc 2 khi chưa có kết quả việc 0.**

### Việc 1 — Thêm `retryPolicy` cho các hop gRPC **chỉ đọc** *(đòn bẩy cao nhất, rủi ro thấp nhất)*

Đây là mảnh ghép bắt buộc của `round_robin` mà bản trước bỏ sót.

Sửa `src/frontend/gateways/rpc/grpcChannel.ts`:

```jsonc
{
  "loadBalancingConfig": [{ "round_robin": {} }],
  "methodConfig": [{
    // CHỈ service đọc — idempotent, thử lại an toàn.
    // TUYỆT ĐỐI KHÔNG thêm CartService/CheckoutService: AddItem/PlaceOrder
    // không idempotent, thử lại = nhân đôi giỏ hàng hoặc nhân đôi đơn.
    "name": [
      { "service": "oteldemo.ProductCatalogService" },
      { "service": "oteldemo.RecommendationService" },
      { "service": "oteldemo.AdService" },
      { "service": "oteldemo.CurrencyService" }
    ],
    "retryPolicy": {
      "maxAttempts": 3,
      "initialBackoff": "0.05s",
      "maxBackoff": "0.5s",
      "backoffMultiplier": 2,
      // CHỈ UNAVAILABLE = "không kết nối được / endpoint đã biến mất".
      // Không retry DEADLINE_EXCEEDED (server đang chậm, retry làm nặng thêm),
      // không retry INTERNAL (lỗi logic, retry vô nghĩa).
      "retryableStatusCodes": ["UNAVAILABLE"]
    }
  }],
  // Van an toàn BẮT BUỘC. Không có nó, ở chế độ B (bão hoà) retry sẽ
  // nhân tải lên 3 lần và biến quá tải thành sập. Khi tỉ lệ hỏng cao,
  // gRPC tự tắt retry cho tới khi hệ hồi.
  "retryThrottling": { "maxTokens": 100, "tokenRatio": 0.1 }
}
```

Kèm `'grpc.enable_retries': 1` trong `loadBalancedChannelOptions`, và hạ
`dns_min_time_between_resolutions_ms` **5000 → 2000** để rút ngắn cửa sổ địa chỉ chết.

**Vì sao tin việc này trúng đích:** cụm lỗi 8 giây ở u400 khớp đúng độ dài TTL DNS 5s; và toàn bộ
lỗi nằm trên **đường đọc** (`/api/products/[id]`, `/api/product-reviews/[id]`) — đúng những route
mà retry an toàn. `cart` và `checkout` đạt 99,99%+ nên không cần đụng tới.

**Rủi ro:** cần rebuild image (`build-push-ecr.yml`, chỉ dispatch được từ `main`) rồi bump digest.
Đây là chỗ đã tốn thời gian nhiều lần — tính vào lịch.

### Việc 2 — Nới trần `product-reviews` *(chỉ làm nếu việc 0 kết luận là semaphore/CPU)*

`gitops/infrastructure/hpa-hotpath.yaml`:

| Tham số | Nay | Đề xuất | Vì sao |
|---|---:|---:|---|
| `maxReplicas` | 6 | **12** | Nguồn 73–81% lỗi browse ở tải cao, mà lại là service bị cấp hẹp nhất |
| `averageUtilization` | 75% | **65%** | Đồng bộ với cả hot path; 75% khiến nó phản ứng chậm hơn mọi service khác |

**Cảnh báo:** ở u1800 đã có **13 pod Pending**. Nới `maxReplicas` mà không có chỗ đặt pod thì chỉ
đổi "pod không được sinh" thành "pod Pending". Việc này **phụ thuộc việc 4**.

### Việc 3 — Giảm churn ở tải thấp *(rẻ, GitOps thuần, không cần rebuild)*

Chế độ A là lỗi **do thay đổi endpoint**, nên giảm số lần thay đổi là giảm trực tiếp số cụm lỗi:

| Đối tượng | Nay | Đề xuất |
|---|---|---|
| `product-catalog` `minReplicas` | 2 | **4** |
| `product-reviews` `minReplicas` | 2 | **4** |
| `scaleDown.stabilizationWindowSeconds` | 120 | **300** |

`minReplicas` cao hơn ⇒ ở u400–u800 HPA gần như không phải scale ⇒ không có sự kiện churn ⇒ không
có cụm lỗi. Cửa sổ scale-down dài hơn ⇒ bớt dao động lên-xuống-lên.

**Đánh đổi phải nói rõ với CDO02:** giữ thường trực 4 replica thay vì 2 là **tăng chi phí nền**,
trong khi ngân sách TF đang vượt trần. Phải xin ý kiến, không tự quyết.

### Việc 4 — Mở 4 node `t3.large` cho hot path *(việc duy nhất phá được trần u1400+)*

Ở u1800: `frontend` **16/16 kịch trần ở 142% CPU**, `product-catalog` **12/12 ở 105%**, 13 pod
Pending — trong khi 4 node managed ngồi ở 18–58% CPU và **không bao giờ nhận được pod hot path**
vì thiếu label. **Không tuning nào chạm tới được chuyện này.**

Đây đúng nghĩa *"nâng trần bằng hiệu suất, không thêm node"*: **không mua thêm gì, chỉ dùng 8 vCPU
đã trả tiền.** Image đã build đa kiến trúc nên kỹ thuật là chạy được ngay.

**Chặn:** sửa thiết kế Mandate #13 của CDO01 (ghim Graviton để tiết kiệm). **Phải thống nhất
trước, không đơn phương.** Lựa chọn mềm hơn nếu CDO01 không đồng ý gỡ hẳn: chỉ gỡ ghim cho
**`frontend`** (service kịch trần nặng nhất, 142%), giữ nguyên phần còn lại.

---

## 4. Lịch và xác suất — nói thẳng

| Việc | Thời gian | Cần rebuild image? | Cần ai đồng ý |
|---|---|---|---|
| 0 — chẩn đoán 503 | 30 ph | không | — |
| 1 — retryPolicy | 45 ph | **có** | — |
| 2 — nới product-reviews | 10 ph | không | — |
| 3 — giảm churn | 10 ph | không | **CDO02** (chi phí nền) |
| 4 — mở 4 node | 20 ph | không | **CDO01** (thiết kế M#13) |
| Đo lại 4 stage quyết định | 45 ph | — | — |
| **Tổng** | **~2,5 – 3 giờ** | | |

Stage đo lại: **u1000 · u1200 · u1400 · u1600**. Bỏ u200–u800 (đã biết chỉ trượt vì churn, việc 3
xử lý), bỏ u1800+ (chắc chắn cần việc 4).

**Mục tiêu thực tế: đưa trần từ u1000 lên u1400** ⇒ 202,4 → ~278 RPS ⇒ **+37% trên cùng 9 node**.
Đủ để đóng YC#2.

### Xác suất — và vì sao không phải 100%

| Kịch bản | Ước lượng qua u1400 |
|---|---:|
| Chỉ việc 1 + 3 (không đụng ai) | **~55%** |
| Việc 1 + 2 + 3 (nếu việc 0 xác nhận semaphore) | **~70%** |
| Thêm việc 4 | **~85%** |
| Qua được u1800 | **<25% nếu không có việc 4** |

**Ba điều có thể làm hỏng, đã lường trước:**

1. **Việc 0 có thể lật ngược việc 2.** Nếu 503 đến từ Bedrock rate-limit thì thêm replica không
   giúp gì, và bài toán chuyển sang AIO02 (Tier-2 fallback đường đọc chưa từng được kiểm chứng).
2. **Retry có thể phản tác dụng ở chế độ B.** `retryThrottling` là van an toàn, nhưng nó chỉ giảm
   thiệt hại chứ không loại bỏ. Vì vậy đo u1000→u1400 trước, **không nhảy thẳng u1800**.
3. **Việc 2 có thể chỉ đổi hình dạng vấn đề** từ "không đủ replica" thành "pod Pending", nếu việc
   4 chưa xong.

**Không hứa 4/4.** Kế hoạch này đủ cơ sở để tin là qua được u1400; u1800 thì phải mở được node
mới nói chuyện tiếp.

---

## 5. Cách nghiệm thu

Mỗi stage vẫn phải giữ nguyên giao thức đo đã dùng — nếu đổi cách đo giữa chừng thì con số mới
không so được với 4 vòng cũ:

```sh
# cùng harness, cùng cửa sổ 300s, generator NGOÀI cluster qua CloudFront
bash scripts/mandate-19/run_stage_external.sh <out>/u1400 1400 420
python3 scripts/mandate-19/client_truth.py <out>          # RPS lấy từ CSV, KHÔNG từ span
```

Điều kiện tuyên bố YC#2 đạt — phải đủ **cả ba**:

1. Có stage **cao hơn u1000** qua **cả 4 cổng** SLO.
2. `node_count = 9` và **`node_set_sha256` khớp** với vòng baseline — đúng từng ấy node, đúng
   những node đó.
3. RPS/node tăng so với **202,4 / 9 = 22,5 rps/node**.

Nếu trượt: ghi lại đúng cổng nào trượt và ở stage nào, **không lùi ngưỡng để cho qua**.

---

## 6. Việc này KHÔNG được phép đụng vào

Nhắc lại vì mọi thay đổi ở đây đều nằm trong hot path:

- `/flagservice` trong Envoy và `values-flagd-sync.yaml` — **giữ nguyên tuyệt đối**.
- Filter `envoy.filters.http.fault` — giữ nguyên.
- **Không `kubectl apply` tay.** Toàn bộ qua PR + ArgoCD.
- Không thêm `retryPolicy` cho `CartService` / `CheckoutService` — không idempotent.

---

**Liên quan:** [báo cáo tóm tắt](mandate-19-nghiem-thu.md) ·
[báo cáo đầy đủ](mandate-19-throughput-ceiling-report.md) ·
[ADR 0011](adr/0011-mandate-19-throughput-ceiling-load-shedding.md) ·
[kịch bản trả lời mentor](mandate-19-kich-ban-tra-loi-mentor.md)
