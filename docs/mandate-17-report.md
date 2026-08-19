# Mandate #17 — Chịu được sự cố, khoanh được kẻ xâm nhập

**Task Force:** TF3 · **Cluster:** `techx-corp-tf3` · **Namespace:** `techx-tf3`
**Ngày báo cáo:** 31/07/2026
**Phân công:** CDO-02 phụ trách YC#1 + YC#2 (Reliability) · CDO-01 phụ trách YC#3 + YC#4 (Security)

> Đây là **report chủ** của Mandate #17, gộp cả bốn yêu cầu. Hai bản chi tiết theo trụ nằm ở
> §7 Phụ lục. Nếu chỉ đọc một file, đọc file này.

---

## 1. Kết luận điều hành

| # | Yêu cầu | Trạng thái | Ghi chú |
|---|---|---|---|
| 1 | Sống qua một dependency chết | ✅ **ĐẠT** | deadline + fallback trên 5 gateway, đang chạy live |
| 2 | Chịu được mất cả một AZ | ⚠️ **ĐẠT MỘT PHẦN** | **2 lần diễn tập thật, kết quả đối chứng nhau.** Cart đạt 100 % khi Valkey primary ở AZ khác; gãy 100 % khi primary nằm trong AZ bị mất (`REL-17-07`) |
| 3 | Khoanh mạng (NetworkPolicy) | ✅ **ĐẠT** | `default-deny-all` live, lateral movement + egress Internet đều bị chặn (kiểm lại độc lập) |
| 4 | Least-privilege RBAC / ServiceAccount | ✅ **ĐẠT** | SA riêng từng service, SA `default` không còn binding nào |

**Ba trong bốn yêu cầu đạt.** YC#2 đạt một phần và **chúng tôi không làm tròn con số đó** — bài
diễn tập mất AZ thật đã làm gãy luồng cart, số liệu nằm ở §3.

Phần "Phải nộp" của Directive cho phép mentor chọn **giết một dependency HOẶC chặn một AZ**.
Đường thứ nhất đã sẵn sàng nghiệm thu (§2); đường thứ hai sẽ gãy ở cart và §3 nói rõ vì sao.

---

## 2. YC#1 — Sống qua một dependency chết ✅

**Cách làm (REL-17-02):** gRPC-js **không có deadline mặc định** — một backend treo sẽ giữ
request của frontend vô hạn và kéo sập cả trang. Mỗi gateway được gắn deadline riêng theo đúng
đặc tính của nó, cộng fallback trả nội dung suy giảm thay vì lỗi.

| Gateway | Deadline | Khi vượt hạn |
|---|---|---|
| `Ad.gateway.ts` | **300 ms** | bỏ quảng cáo, trang vẫn render |
| `Currency.gateway.ts` | **500 ms** | giữ giá gốc |
| `ProductCatalog.gateway.ts` | **500 ms** | lỗi rõ ràng, **không treo** |
| `ProductReview.gateway.ts` | **500 ms** | ẩn khối review |
| `ProductReview` — trợ lý AI | **15 000 ms** | gọi Bedrock, **chậm là bản chất** nên tách ngưỡng riêng |

Ngưỡng AI tách riêng là điểm cố ý: ép 500 ms lên một lời gọi LLM sẽ làm tính năng đó không bao
giờ chạy được. Deadline phải theo bản chất từng phụ thuộc, không phải một con số cho tất cả.

**Đang chạy thật:**
```
frontend image = ...techx-corp@sha256:0e9997d6e40bacdd68a3aac7f7df87a142fbd4e2beb3ef84741297b736fbc042
```
(khớp `imageOverride.digest` trong `deploy/values-prod.yaml` — code fallback đã lên production;
xem ghi chú chống revert ở đó về PR #448/#450 và PM-129)

**Mentor nghiệm thu thế nào:** giết `ad` hoặc `recommendation` rồi mở storefront — trang vẫn
render, chỉ thiếu khối tương ứng. Trong bài diễn tập AZ ở §3, **cả `ad` và `recommendation` đều
chết thật** (chúng nằm trọn trong AZ bị cô lập) và `/` cùng `/api/products` giữ nguyên `200` với
độ trễ không đổi — đó là YC#1 được chứng minh bằng sự cố thật, không phải bằng mô phỏng.

---

## 3. YC#2 — Chịu được mất cả một AZ ⚠️

### 3.1. Nền tảng đã có

- 10/10 service ra tiền chạy ≥2 replica; **PDB đủ cho toàn bộ luồng** (`cart`, `checkout`,
  `payment`, `shipping`, `quote`, `currency`, `product-catalog`, `product-reviews`, `frontend`,
  `frontend-proxy`, `cloudflared`, `otel-gateway` — 15 PDB).
- Anti-affinity REL-17-04 tách Grafana ≠ Prometheus theo AZ.
- Datastore managed đều multi-AZ (RDS, ElastiCache replication group, MSK RF=3).

### 3.2. Diễn tập thật bằng AWS FIS — không phải cordon/drain

Directive tự phân biệt với #3: *"#3 là bảo trì **có kế hoạch**; đây là **chết bất ngờ**"*.
`kubectl cordon`+`drain` evict lịch sự, tôn trọng PDB, chạy preStop — nó chứng minh #3, **không
phải #17**. Vì vậy chúng tôi dựng hạ tầng chaos thật:

- `infra/live/production/fis-chaos-experiments.tf` — role `tf3-fis-experiment`, alarm dừng khẩn
  `tf3-fis-stop-storefront-5xx`, template `EXT9JSZivevPf3Hoe`
  (`aws:network:disrupt-connectivity`, `scope=availability-zone`, `PT5M`).
- Rollout scope riêng `m17-fis` trong `terraform-apply.yml`.
- Runbook + khung evidence: `docs/runbooks/mandate-17-fis-az-drill.md`.

### 3.3-A. Lần diễn tập cuối (31/07, `EXPJazdMDpevoHeDJr`) — chạy trọn `PT5M`

Khác lần trước ở một điểm quyết định: **Valkey primary lúc này nằm ở 1c**, không phải 1b.
Bài chạy hết 5 phút, kết thúc trạng thái `completed` (không phải bị dừng), NACL trả nguyên trạng.

Tỷ lệ thành công **tính riêng trong cửa sổ fault** (17:59:34–18:04:34, 115 mẫu mỗi đường):

| Đường | Thành công | SLO | Kết quả |
|---|---|---|---|
| `/api/cart` | **115/115 = 100,00 %** | ≥99,5 % | ✅ **ĐẠT** |
| `/` | 114/115 = 99,13 % | ≥99,5 % | ⚠️ hụt — đúng **1 mẫu**, `000` tại giây fault bắt đầu |
| `/api/products` | 108/115 = 93,91 % | ≥99,5 % | ❌ **KHÔNG ĐẠT** |

**`/api/cart` đạt 100 % là kết quả quan trọng nhất của bài này.** Ghép với lần 30/07 (cart hỏng
100 % khi primary ở 1b), hai phép đo đối chứng cho kết luận chính xác:

> Hệ **chịu được mất một AZ** — **trừ khi** AZ đó chứa Valkey primary. Khi đó cart gãy hơn 70
> giây vì client mất quá lâu để phát hiện kết nối chết (`REL-17-07`).

Đây không phải suy đoán: cùng một bài, cùng một AZ mục tiêu, chỉ khác vị trí primary, và kết quả
lật hoàn toàn.

**Về 7 lỗi trên `/api/products`** — không quy hết cho việc mất AZ được, và chúng tôi nói rõ:
- Cả 7 đều có độ trễ **~1,30–1,33 giây, đều bất thường** — dấu hiệu chạm một ngưỡng cố định.
- **Cùng dấu vân tay đó đã xuất hiện khi KHÔNG có fault nào**: 30/07 lúc 16:32:45/49/52 và
  16:35:07/11 (`500` với 1,31–1,36 s), giữa hai lần bắn. Tức là lỗi chập chờn có sẵn.
- Trong bài thì nó **dồn cục** — 7 lỗi trong 40 giây cuối, dày hơn nền.
- Log frontend cho `code: 14 UNAVAILABLE — round_robin: No connection established,
  Last error: null`, **không kèm địa chỉ** → resolver trả về **zero address**, tức Service đích
  có 0 endpoint. Suốt bài, `checkout` đúng là **0 endpoint** (`REL-17-09`).
- **Giả thuyết mạnh nhưng chưa chứng minh:** frontend khởi tạo mọi gRPC gateway ở tầng module,
  nên một kênh hỏng có thể trồi lên ở route không liên quan. `pages/api/products/index.ts` chỉ
  gọi `ProductCatalogService`, mà `product-catalog` và `currency` đều sống (1a+1c) — nên nguyên
  nhân **không** nằm trong chuỗi phụ thuộc trực tiếp của route đó. Cần điều tra riêng.

### 3.3-B. Lần diễn tập 30/07 — Valkey primary ở 1b

Đo từ **ngoài cluster** (vòng lặp curl trên máy người trực — bằng chứng này sống sót kể cả khi
drill làm gãy Prometheus/Jaeger):

```
                        /        /api/products    /api/cart
17:26:13  (trước)     200          200              200
17:26:15  FAULT       200          200              500   ← gãy ngay
17:26:23              200          200              500
   ... 8/8 mẫu liên tiếp, không mẫu nào phục hồi ...
17:27:13              200          200              500
17:28:53  (sau)       200          200              200
```

| Đường | Kết quả |
|---|---|
| Browse — `/`, `/api/products` | ✅ **ĐẠT** — `200` suốt bài, độ trễ **không đổi** (0,12–0,24 s) |
| Cart — `/api/cart` | ❌ **KHÔNG ĐẠT** — `500` ở 100% mẫu, độ trễ 5–6,5 s |
| Checkout | chưa đo — dừng bài trước khi kịp |

Bài bị dừng ở **~60 giây** theo tiêu chí ABORT của runbook (5xx liên tiếp > 30 s), không chờ hết
`PT5M`. NACL được FIS trả nguyên trạng (`acl-0c7e1cead7edbc9f3`), storefront hồi phục hoàn toàn.

**`/` giữ `200` suốt bài là nhờ cache CloudFront.** Nếu probe chỉ ping `/`, bài này đã "pass" một
cách sai hoàn toàn. Ba đường đo riêng biệt mới là thứ giữ được tính trung thực của kết luận.

### 3.4. Nguyên nhân gốc — không phải chỗ ai cũng đoán

Nghi vấn đầu tiên là "Valkey không failover". **Sai.** Kiểm bằng `aws elasticache test-failover`
(tái lập được, không cần chaos):

```
17:31:55  test-failover
17:32:22  primary chuyển 1b → 1c        ← AWS mất 27 giây
17:33:34  /api/cart mới hết 500          ← ứng dụng mất thêm hơn 70 giây
```

ElastiCache làm đúng và nhanh. Nút thắt nằm ở client, tại
`src/cart/src/cartstore/ValkeyCartStore.cs:92-104`:

```csharp
options.ReconnectRetryPolicy = new ExponentialRetry(1000);
options.KeepAlive            = 180;   // ← 180 GIÂY
```

`KeepAlive` là chu kỳ StackExchange.Redis ping để phát hiện kết nối chết. Sau failover, node cũ
tụt xuống replica nhưng **kết nối TCP cũ vẫn mở**; client có thể mất tới **3 phút** mới nhận ra,
rồi còn backoff luỹ thừa khi kết nối lại. Cấu hình endpoint hoàn toàn đúng — cart trỏ vào
`master.techx-tf3-valkey...`, tức primary endpoint tự đi theo failover.

**Cart không ghi một dòng log lỗi nào trong suốt thời gian đó.** Chỉ nhìn log thì không bao giờ
tìm ra; phải đo từ ngoài.

→ **`REL-17-07`: hạ `KeepAlive` xuống 5–10 giây.** Một dòng, và nó rút thời gian gãy của cart từ
hơn 70 giây xuống còn cỡ thời gian failover thật.

### 3.5. Hai lỗ hổng khác lộ ra trong lúc diễn tập

**`REL-17-08` — `topologySpreadConstraints` không giữ pod ở đúng chỗ.**
`frontend` và `frontend-proxy` từng có **2/2 replica dồn vào 1c** dù cấu hình đúng tuyệt đối
(`minDomains: 2`, `DoNotSchedule`, `Honor`). Lý do: ràng buộc **chỉ được đánh giá lúc lập lịch**.
Qua nhiều lần rolling update (frontend có 11 ReplicaSet), cụm hội tụ dần về một AZ **mà không vi
phạm gì**. Đã rải lại 1a+1c trước khi bắn, nhưng đây là cân bằng thủ công và **sẽ trôi lại**.
Fix triệt để: descheduler với `RemovePodsViolatingTopologySpreadConstraint`.

*Bài học vận hành: không bao giờ kết luận phân bố AZ từ manifest — phải đếm pod.*

**`REL-17-09` — readiness của `checkout` là bộ khuếch đại sự cố.**
`src/checkout/main.go:162-188` + `:334-346` đặt trạng thái health bằng phép **AND cứng** của ba
upstream (`cart.GetCart` + `currency.GetSupportedCurrencies` + `productCatalog.ListProducts`),
chạy **mỗi 5 giây** với **tổng ngân sách 2 giây cho cả ba lời gọi tuần tự**.

Hệ quả: một cú chớp nháy 2 giây ở bất kỳ upstream nào → checkout trả `NOT_SERVING` → bị gỡ khỏi
Service → **0 endpoint** → toàn bộ luồng đặt hàng biến mất. Đã quan sát thấy thật, và nó tự hồi
phục sau ~4 phút mà không ai can thiệp. Ngoài ra `ListProducts` liệt kê toàn bộ catalog **mỗi 5
giây trên mỗi replica** — health check tự bơm tải vào chính service dễ nghẽn nhất.

Ý định của REL-02 ("đừng nhận traffic khi không phục vụ được") là đúng; cách cài đặt biến nó
thành nguồn sự cố. Fix: timeout riêng cho từng dependency, nới ngân sách, đổi sang một RPC rẻ,
và chỉ hạ cờ sau nhiều chu kỳ trượt liên tiếp thay vì một lần.

### 3.6. Giới hạn nói thẳng

- **Chỉ diễn tập 1b, chưa diễn tập 1a.** Toàn VPC dùng **một NAT Gateway đặt ở 1a**, ba private
  subnet chung một route table trỏ vào nó, và cả ba VPC endpoint SSM cũng ở 1a. Mất 1a thật sẽ
  đứt egress toàn cluster (tunnel cloudflared rớt, không pull được ECR nên không pod nào khởi
  động được ở bất kỳ AZ nào) — nặng hơn nhiều so với mất workload. Đây là phát hiện của bản rà
  soát hệ thống 29/07, đã ghi nhận và đề xuất xử lý riêng.
- **Không quan sát được self-heal trong cửa sổ đo:** `tolerationSeconds=300` mặc định trùng đúng
  `duration=PT5M`, nên pod ở AZ bị cô lập không kịp bị tạo lại ở AZ khác. Bài này chứng minh
  *replica ở AZ còn lại phục vụ được*, không chứng minh *tạo lại pod kịp trong 5 phút*.
- **Không có metric tầng node/container** trong bài đo: `netpol/prometheus-access` thiếu egress
  cổng 10250 làm 29/34 scrape target chết. Metric ứng dụng vẫn đủ vì otel-gateway push OTLP thẳng
  vào Prometheus. Bằng chứng node lấy từ `kubectl`/EC2 console. Đã chuyển finding cho CDO-01.
- Lần bắn đầu (30/07) **nhắm nhầm AZ 1c** do template bị một `terraform apply` chạy local trên
  máy khác sửa mà không thông báo. Đã dừng sau ~78 giây, rollback sạch, và đã thêm chốt chặn tự
  động so AZ trước mỗi lần bắn. Mốc thời gian đầy đủ + CloudTrail:
  `docs/evidence/mandate-17/drill-evidence/README.md`.

---

## 4. YC#3 — Khoanh mạng (NetworkPolicy) ✅

Chủ trì: **CDO-01**. Chi tiết: `docs/docx_cdo01/mandate-17-network-policy-report.md`.

Tóm tắt: `default-deny-all` (`podSelector: {}`, cả Ingress lẫn Egress) đã apply live qua GitOps
(`gitops/infrastructure/network-policy-default-deny-all.yaml`, commit `9db561e`), bên trên là bộ
NetworkPolicy allowlist theo từng service (33 PolicyEndpoint). Nhu cầu gọi ra ngoài theo FQDN
được giải bằng **egress proxy** riêng (`aiops-egress-proxy`, `product-reviews-egress-proxy`,
`shopping-copilot-egress-proxy`) thay vì mở CIDR rộng.

**Kiểm chứng độc lập bởi CDO-02, chạy live 30/07:**

```
cart → payment:8080                     Operation timed out    ✅ chặn lateral movement
product-reviews → payment:8080          Operation timed out    ✅ chặn lateral movement
product-reviews → product-catalog:8080  open                   ✅ đường hợp lệ vẫn thông
cart → example.com:443                  DNS giải được 104.20.23.154, rồi timed out
                                                               ✅ chặn Internet
storefront                              200, 0.34 s            ✅ không gãy gì
```

Lệnh cuối chứng minh **hai** điều cùng lúc: DNS được allow (nên pod không phải đang chết), và kết
nối ra Internet bị nuốt ở tầng network.

---

## 5. YC#4 — Least-privilege RBAC / ServiceAccount ✅

Chủ trì: **CDO-01**. Chi tiết: `docs/evidence/mandate-17/pm-149-rbac-least-privilege.md`.

Mỗi service dùng ServiceAccount riêng (`techx-frontend`, `techx-cart`, …) thay vì SA `default`
dùng chung; SA `default` đã bị gỡ **toàn bộ** RoleBinding/ClusterRoleBinding; `cloudflared` có SA
riêng. Pod bị chiếm không gọi được K8s API ngoài quyền tối thiểu.

Kiểm bằng `kubectl auth can-i --as=system:serviceaccount:techx-tf3:<sa>` — bằng chứng trong
`docs/evidence/mandate-17/t10/auth-can-i-after.txt`.

Bổ trợ (Directive #5, CDO-01): PSA `restricted` đang enforce thật — trong lúc điều tra bài này,
một pod chẩn đoán tạm đã **bị API server từ chối** vì thiếu `runAsNonRoot`, `capabilities.drop`,
`seccompProfile`. Đó là containment hoạt động ngoài kịch bản, không phải trên slide.

---

## 6. Mentor tự nghiệm thu

### 6.1. Giết một dependency (YC#1)
```bash
kubectl -n techx-tf3 scale deploy/ad --replicas=0
curl -s -o /dev/null -w '%{http_code}\n' https://d2tn71186d7ilz.cloudfront.net/
kubectl -n techx-tf3 scale deploy/ad --replicas=1
```
Kỳ vọng: `200` xuyên suốt, trang thiếu khối quảng cáo.

### 6.2. Chặn một AZ (YC#2)
```bash
aws fis start-experiment --experiment-template-id EXT9JSZivevPf3Hoe --region ap-southeast-1
```
Kỳ vọng **trung thực**: browse giữ `200`; **`/api/cart` sẽ trả `500`** cho tới khi `REL-17-07`
được sửa. Trước khi chạy, đọc `docs/runbooks/mandate-17-fis-az-drill.md` §0 và §2.

### 6.3. Containment (YC#3)
```bash
kubectl -n techx-tf3 exec deploy/cart -- nc -vz -w 5 payment 8080
kubectl -n techx-tf3 exec deploy/product-reviews -- nc -vz -w 5 product-catalog 8080
kubectl -n techx-tf3 exec deploy/product-reviews -- nc -vz -w 5 payment 8080
kubectl -n techx-tf3 exec deploy/cart -- nc -vz -w 5 example.com 443
```
Dùng `nc` chứ **không** dùng `curl`: image `cart` không có `curl`, và lệnh `curl` sẽ trả
"executable file not found" — một lỗi exec, **không phải bằng chứng bị chặn**.

### 6.4. RBAC (YC#4)
```bash
kubectl auth can-i --list --as=system:serviceaccount:techx-tf3:default -n techx-tf3
```

---

## 7. Việc còn mở

| Mã | Nội dung | Mức |
|---|---|---|
| `REL-17-07` | `KeepAlive` 180 s → 5–10 s trong `ValkeyCartStore.cs` | 🔴 chặn YC#2 |
| `REL-17-09` | Readiness `checkout`: tách timeout từng dep, bỏ AND cứng, đổi `ListProducts` | 🔴 nguồn sự cố |
| `REL-17-08` | Descheduler chống trôi topology spread | 🟠 |
| `REL-17-05` | Luồng ra tiền tập trung trên số ít node spot (giao thoa Mandate 13) | 🟠 |
| — | `netpol/prometheus-access` thiếu egress 10250 → 29/34 scrape target chết | 🟠 CDO-01 |
| — | Kyverno chặn mọi ReplicaSet mới của `checkout` (thiếu chữ ký Cosign) | 🟠 Mandate 10 |
| — | NAT + SSM endpoint đơn điểm ở AZ 1a | 🟠 đề xuất riêng |

---

## 8. Phụ lục

| Tài liệu | Nội dung |
|---|---|
| `docs/docx_cdo01/mandate-17-network-policy-report.md` | YC#3 — NetworkPolicy, chi tiết CDO-01 |
| `docs/evidence/mandate-17/pm-149-rbac-least-privilege.md` | YC#4 — RBAC least-privilege |
| `docs/docx_cdo02/mandate-17-reliability-gap-analysis.md` | Phân tích khoảng trống REL-17-01..08 |
| `docs/evidence/mandate-17/rel-17-04-and-req2-az-resilience-2026-07-26.md` | Anti-affinity + phân bố AZ |
| `docs/runbooks/mandate-17-fis-az-drill.md` | Runbook diễn tập + khung evidence |
| `docs/evidence/mandate-17/drill-evidence/` | Evidence thô của bài diễn tập + `README.md` mốc thời gian |
| `docs/evidence/mandate-17/network-policy-pass-fail-test-commands.md` | Ma trận lệnh allow/deny |
| `scripts/chaos/drill-capture.ps1`, `drill-probe.ps1` | Công cụ thu evidence tự động |
| `infra/live/production/fis-chaos-experiments.tf` | Hạ tầng chaos (role, alarm, template) |
