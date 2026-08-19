# Mandate #19 — Kịch bản trả lời mentor

Tài liệu **nội bộ để chuẩn bị nói**, không phải sản phẩm nộp. Mục tiêu: mở miệng ra là có số,
và mỗi số đều chỉ được về một file trong repo.

**Nguyên tắc xuyên suốt: nói thật con số, kể cả con số xấu.** Ba lỗi tự phát hiện trong bài này
(lỗi phương pháp đo, lỗi tự phá cơ chế shed, lỗi đọc log Karpenter) đều **chủ động khai trước**.
Mentor tìm ra trước mình thì mất toàn bộ độ tin cậy của những con số còn lại.

---

## 0. Ba mươi giây mở đầu

> Directive #19 có 4 yêu cầu, chúng em đạt **3**, và **yêu cầu #2 báo là chưa qua**.
>
> Trần thật là **1000 user / 202,4 RPS** — cao hơn con số cũ trong repo khoảng **3 lần**, vì con
> số cũ đo sai phương pháp. Sau khi tối ưu, ở **cùng 9 node** hệ chạy **442,3 RPS ở 2400 user,
> tăng 29%**. Khi vượt trần 3 lần, hệ hy sinh 104 nghìn request browse để giữ **luồng tiền ở
> 99,95%** — không sập.
>
> Cái em muốn báo rõ nhất không phải con số, mà là **thứ gãy trước không phải browse mà là
> checkout**, và **hai trong ba nút thắt không phải CPU** — nên mọi phản xạ "thêm replica, thêm
> node" đều không chạm tới chúng.

Dừng. Để mentor hỏi.

---

## 1. Câu chắc chắn bị hỏi

### ❓ "Sao trần của em 202 RPS mà báo cáo khác trong repo ghi 76 RPS / 400 user?"

**Đây là câu nguy hiểm nhất — trong repo đang có BA con số.** Trả lời:

> Ba con số đo ba thứ khác nhau, không mâu thuẫn:
>
> | Nguồn | Trần | Đo gì |
> |---|---|---|
> | `docs/evidence/report.md` bản gốc | 328u / 174,75 RPS | tác giả **đã tự rút lại**, không có CSV |
> | PR #634 | 400u / **76,2 RPS** | **RPS tức thời** đọc từ *một* ảnh Grafana |
> | Báo cáo của em | 1000u / **202,4 RPS** | **trung bình duy trì 300 giây**, từ CSV Locust |
>
> **76,2 là kim đồng hồ tại một giây; 202,4 là quãng đường đi trong 5 phút.** Bắn cùng một tải mà
> đọc bằng hai thước thì ra hai số khác nhau, cả hai đều không sai.
>
> Nhưng điểm quyết định không nằm ở đó: **cả hai bài đo cũ đều để node trôi 9 → 10 → 11 giữa bài.**
> Directive #19 đòi *"không thêm node"* — bài đo mà số node thay đổi thì không dùng làm gốc so sánh
> được, bất kể con số bao nhiêu. Em không nói bài cũ sai; nó trả lời **câu hỏi khác**.

📄 `docs/mandate-19-nghiem-thu.md` §1

---

### ❓ "Vì sao yêu cầu #2 chưa qua? Em sửa mà không hiệu quả à?"

Trả lời theo **đúng thứ tự này**, đừng đảo:

> **Bản vá không sai, và có hiệu quả đo được.** Phân bố tải lệch từ **353 lần xuống 3,7 lần**.
> Ở 1800 user checkout đi từ **7,12% lên 99,18%**. Throughput **+29% trên cùng 9 node**.
>
> Chưa qua vì cổng đánh giá là **"stage cao nhất qua cả 4 SLO"** — nhị phân. Sau khi sửa, hệ **đổi
> chế độ hoạt động**: trước đây traffic dồn vào 2/11 pod, giờ trải đều 11 pod. Nhưng `minReplicas`,
> ngưỡng HPA 65%, hạn chờ 1200ms **vẫn là bộ tham số hiệu chỉnh cho chế độ cũ**.
>
> Cổng trượt **chỉ có một**: `browse_success`. cart, checkout và browse p95 đều qua — p95 là
> **389,7ms** so với ngưỡng 1000ms, dư 2,6 lần biên. Không phải bài toán tốc độ.
>
> Và em xác định được **hệ không hết sức, nó bị gián đoạn**. Lỗi không rải đều mà dồn thành cụm
> ngắn rồi tự tắt, trong khi tài nguyên còn thừa: lúc 1000 user thì `product-catalog` chỉ ở
> **61%/65%** với 8/12 pod, `frontend` 79%/65% với 10/16 pod.
>
> Nguyên nhân là **bản vá của em còn thiếu một mảnh**: `round_robin` được ship mà không kèm
> `retryPolicy`. Với `pick_first` thì một pod bị thay chỉ ảnh hưởng client ghim vào nó; với
> `round_robin` thì **mọi** client đều dính một phần. Mà `dns_min_time_between_resolutions_ms`
> đang là 5000, nên sau khi một pod biến mất client còn gửi vào địa chỉ chết tới 5 giây —
> **khớp đúng cụm lỗi 8 giây** đo được. Không có retry thì mỗi lần như vậy là 500 tới thẳng người dùng.

⚠️ **Nếu mentor hỏi ngược: "vậy trần MỚI của em là bao nhiêu?"** — trả lời thẳng, đừng né:

> Theo đúng thước đo directive thì bản tối ưu có trần **u200**, tức **thấp hơn** baseline u1000.
> Em không giấu con số này. Nó thấp vì browse dính ~1% lỗi ở gần như mọi mức tải do đúng cái
> thiếu `retryPolicy` em vừa nói. Nhưng ở nơi quan trọng nhất thì bản mới khoẻ hơn hẳn: ở 1800
> user checkout đi từ **7,12% lên 99,18%** và throughput từ 298 lên 356 RPS.

**Nếu mentor gặng "vậy sao không chỉnh luôn rồi đo lại?"**

> **~2,5–3 giờ**, và em không dám nói chắc: **~55%** nếu chỉ thêm `retryPolicy` và giảm churn;
> **~70%** nếu nới được `product-reviews` — nó đang là service cấp hẹp nhất hot path
> (`maxReplicas` 6 trong khi frontend 16, catalog 12) và sinh **73–81% lỗi browse** ở tải cao;
> **~85%** nếu CDO01 đồng ý mở 4 node `t3.large` cho hot path. Qua được 1800 user thì **dưới 25%**
> nếu không mở node — lúc đó `frontend` đã **16/16 kịch trần ở 142% CPU**.
>
> Kế hoạch chi tiết em viết sẵn ở `docs/mandate-19-ke-hoach-yc2.md`, có cả việc phải làm TRƯỚC là
> chẩn đoán 503 của `product-reviews` — vì nếu nó đến từ cạn connection pool thì thêm replica còn
> **làm tệ hơn**.

⚠️ **Đừng dùng lý do "thước đo không công bằng" để xin điểm.** Có thể nêu (checkout 7,12% → 99,18%
vẫn tính 0 điểm) nhưng phải kèm ngay: *"Em nêu cho đủ hai mặt, không dùng để đòi PASS. Cổng là cổng,
em báo là chưa qua."*

📄 `docs/mandate-19-nghiem-thu.md` §5

---

### ❓ "Nút thắt là gì? Sao không thêm replica cho xong?"

> Ba nút thắt, và **hai trong ba thêm replica không giải quyết được**:
>
> **1. `email` — nghẽn hàng đợi, không phải chậm.** Span phía client **15000ms**, span phía server
> **391ms**. Chênh 14,6 giây đó là thời gian **nằm chờ trong hàng đợi**. `checkout` gọi nó **đồng bộ**
> ở `src/checkout/main.go:473`. **3432/5431 đơn hỏng — 82% tổng số lỗi — đến từ một service gửi mail.**
> Nguyên nhân: 1 replica Ruby, mà Ruby MRI có GIL nên thực chất chỉ dùng được 1 core, lại còn bị giới
> hạn 100m CPU.
>
> **2. Kết nối gRPC bị ghim vào một pod.** Đây là cái em thấy đáng nói nhất. `product-catalog` có
> **11 replica**, CPU từng pod: `353m · 136m · 11m · 1m · 1m ...` — **9/11 pod gần như không nhận
> việc gì**. Lý do: ClusterIP trả về **một** VIP, gRPC giữ **một** kết nối TCP dài, kube-proxy ghim
> nó vào một pod. **Thêm replica là vô ích** — đó chính là lý do em nói phản xạ "thêm node" không
> chạm tới vấn đề. Sau khi sửa: `55m · 31m · 20m · 15m`, lệch từ **353× còn 3,7×**.
>
> **3. Hạn chờ gRPC 500ms quá nhạy** trong khi p95 thật của `product-catalog` là **6,9ms** — nới lên
> 1200ms, mất 742 lỗi cứng.

**Nếu hỏi "sửa cái số 2 thế nào?"** — đây là chỗ ghi điểm kỹ thuật:

> Phải làm **cả hai** thứ, làm một cái là vô ích:
> 1. **Service headless** (`clusterIP: None`) để DNS trả về **tất cả** IP pod thay vì một VIP.
> 2. **`round_robin`** trong service config của client — vì mặc định của gRPC là `pick_first`, tức
>    là có 11 địa chỉ nó vẫn chỉ dùng địa chỉ đầu tiên.
>
> Chỉ tạo headless mà quên `round_robin` thì DNS trả 11 IP xong client vẫn ghim vào IP đầu — y hệt cũ.

📄 `docs/mandate-19-nghiem-thu.md` §3 · `gitops/infrastructure/backend-headless-services.yaml` ·
`src/frontend/gateways/rpc/grpcChannel.ts`

---

### ❓ "Chứng minh đi, sao biết em không thêm node?"

> Ba lớp bằng chứng độc lập:
>
> 1. **Mỗi stage lưu số node + `sha256` của tập tên node.** Hash giống nhau ⇒ đúng từng ấy node,
>    đúng những node đó — không phải chỉ đúng số lượng. File `infra.txt` mỗi stage.
> 2. **Ảnh Grafana có panel `Node count — Mean: 9 / Max: 9`**, và **time picker nằm trong ảnh** nên
>    thầy tua lại Prometheus đối chiếu được.
> 3. **Bằng chứng ngược:** ở stage vượt trần có pod `Pending` với lý do
>    `node limits have been exhausted for nodepool`. Tức ràng buộc **đang thực sự chặn**, không phải
>    em tự nguyện không thêm.

📄 `docs/evidence/mandate-19/real-2026-07-30/shed-demo/frames/02-dang-overload.png`

---

### ❓ "Demo xuống mềm đi."

Chạy trước mặt mentor, **một lệnh**:

```sh
kubectl -n techx-tf3 port-forward svc/grafana 23000:80
bash scripts/mandate-19/shed_demo.sh /tmp/demo 120 420
```

Vừa chạy vừa nói:

> Bắn **597 rps, gấp 3 lần trần**, qua **CloudFront công khai** — không phải đường tắt trong cluster.
>
> | Route | Kết quả |
> |---|---|
> | `/api/products` (browse) | 190.378 request → **83.495 lần trả 429** |
> | `/` (browse) | 47.358 → **20.769 lần 429** |
> | `/api/cart` | 4.389 request → **1 lỗi** (99,977%) |
> | `/api/checkout` | 4.388 request → **1 lỗi** (99,977%) |
>
> Hy sinh **104 nghìn** request browse để giữ luồng tiền **99,95%**.
>
> Và đây là bằng chứng đúng cơ chế em nói chứ không phải hệ tự chết: counter Envoy cho thấy bucket
> browse chặn **19.539** lần, còn bucket bảo vệ luồng tiền chặn **0 lần trên 148.919 request** —
> nó **không chạm tới một lần nào**.

⚠️ **Chủ động giải thích trước khi bị hỏi** (nếu không sẽ bị bắt bẻ):

> Thầy sẽ thấy **browse success trên Grafana không tụt** dù shed đang chạy. Đúng thiết kế: 429 bị
> chặn ngay tại Envoy nên không tới được `frontend`, mà `SLO.md` định nghĩa browse SLI là **non-5xx**
> — 429 không phải 5xx. Nghĩa là **shed hy sinh browse mà không đốt error budget**.
>
> Panel *"Pod count"* hiện `No data` — đó là **lỗi hạ tầng quan sát có sẵn** (cAdvisor chết 7/8 node),
> không phải bằng chứng pod không scale. Số replica thật nằm trong `infra.txt`.

📄 `docs/evidence/mandate-19/real-2026-07-30/shed-demo/README.md`

---

## 2. Ba lỗi PHẢI tự khai trước

Khai chủ động thì là năng lực tự kiểm; bị phát hiện thì là che giấu.

### 🔴 Lỗi 1 — Đo throughput sai phương pháp

> Ban đầu em lấy throughput từ Prometheus. **Sai.** Phát hiện vì stage **800 user báo throughput
> THẤP HƠN stage 600 user**, trong khi máy bắn tải gửi y hệt nhau.
>
> Em đối chiếu từng route thì thấy **mọi route giảm đúng cùng một hệ số 1,688 lần** — hệ chậm đi thì
> không thể đều tăm tắp như vậy, đó là dấu hiệu **mất dữ liệu**. Log `otel-gateway` xác nhận:
> `Exporting failed. Dropping data. dropped_items=8645`. Bộ giới hạn bộ nhớ của collector đang **vứt
> span** dưới tải.
>
> Cách xử: **tỉ lệ phần trăm** vẫn đọc từ Prometheus — mất đều thì tử số mẫu số cùng co nên tỉ lệ
> vẫn đúng; còn **con số tuyệt đối đọc từ CSV của máy bắn tải**, tức đo tại người dùng, không đi qua
> đường ống nào.

**Vì sao đây là điểm cộng:** nó cho thấy em **không tin số một cách mù quáng** và biết dùng một
nghịch lý nhỏ để lần ra lỗi hệ thống đo.

### 🔴 Lỗi 2 — Tự tay phá cơ chế shed của chính mình

> Ở PR #649 em nâng `maxReplicas` của proxy từ 8 lên 12 cho hệ chịu tải tốt hơn. Việc đó **vô tình
> tắt cơ chế xuống mềm**.
>
> Lý do: filter `local_ratelimit` của Envoy là token bucket **của từng replica**, nên ngân sách tổng
> = `tokens_per_fill × số replica`. Nâng 8 → 12 replica là nâng ngân sách 400 → 600, vượt quá tải
> thật nên **không còn chặn gì nữa**. Đo được: baseline chặn 3641 lần, sau khi "tối ưu" chặn **0
> lần**, và browse sập xuống 63,4%.
>
> Đã hiệu chỉnh lại ở PR #658: `tokens_per_fill` 50 → 33.
>
> **Bài học em rút ra:** thông số shed **không được phép** phụ thuộc vào số replica. Việc còn mở là
> chuyển sang bucket dùng chung toàn cluster.

### 🔴 Lỗi 3 — Đọc sai log Karpenter

> Trong bản báo cáo đầu em viết *"NodePool arm64 thiếu khai báo `techx.io/arch` nên Karpenter không
> tạo được node"*. **Sai, và em đã sửa.**
>
> Karpenter in lý do từ chối của **từng** NodePool rồi gộp thành một khối, em đọc thành một lý do
> chung. Dòng `label "techx.io/arch" does not have known values` là nói về pool **amd64** — hai pool
> đó thật sự không có label này, và **đó là hành vi đúng**: pod đã ghim arm64 thì không nên rơi vào
> node amd64.
>
> Hai pool arm64 **đã có** label ở `template.metadata.labels`, và Karpenter tự đưa static label của
> template vào ràng buộc của node sắp tạo. Lý do thật nằm ở dòng trên: `node limits have been
> exhausted` — `limits.nodes: 2` đã dùng hết.
>
> Cách kiểm chứng nhanh nhất mà em đáng ra phải nghĩ tới ngay: **node elastic đang chạy 99% CPU**.
> Nếu label thiếu thật thì tầng elastic đã rỗng, và bản 442 RPS không thể tồn tại.

---

## 3. Câu khó — chuẩn bị sẵn

### ❓ "Trần cuối cùng là do đâu? Còn tối ưu được nữa không?"

> **Trần cuối không còn nằm ở phần mềm.** Ở 2400 user có **13 pod xếp hàng không xin được chỗ**,
> trong khi:
>
> | Node | CPU | Hot path dùng được? |
> |---|---:|---|
> | elastic `…5-127` | **99%** | ✅ đã cạn |
> | managed `…24-177` | 58% | ❌ |
> | managed `…8-134` | 49% | ❌ |
> | managed `…26-153` | 29% | ❌ |
> | managed `…43-83` | 18% | ❌ |
>
> `values-mandate13.yaml` ghim 10 workload hot path vào `nodeSelector: {techx.io/workload: elastic,
> techx.io/arch: arm64}`. **Bốn node `t3.large` không mang nhãn đó nên vĩnh viễn không nhận được pod
> hot path.** Kết quả: **8 vCPU đã trả tiền đang nằm không** trong khi tầng elastic nghẹt ở 99%.
>
> Đây đúng là đòn bẩy tiếp theo, và nó **đúng nghĩa "nâng trần bằng hiệu suất, không thêm node"** —
> không mua thêm gì, chỉ dùng thứ đã trả tiền. Image đã build đa kiến trúc nên kỹ thuật là chạy được.
>
> **Em chưa làm** vì nó sửa thiết kế Mandate #13 của CDO01 — ghim Graviton để tiết kiệm chi phí. Cần
> thống nhất trước, không đơn phương đổi thiết kế của người khác.

### ❓ "Nghe nói hôm nay hệ sập 42 phút?"

Nói thẳng, đừng vòng vo:

> Đúng. `product-catalog` bị đưa về **0 replica**, `/api/products` trả 500 trong **42 phút**. Em đã
> viết postmortem 0017.
>
> Hai điều em học được, và cả hai đều đáng lo hơn bản thân sự cố:
>
> 1. **HPA không bao giờ scale từ 0 lên** — nó coi `replicas: 0` là "autoscaling đã tắt", kể cả khi
>    `minReplicas: 2`. Nó hiện `cpu: <unknown>` vì không còn pod nào để đo. Vòng tự khoá.
> 2. **GitOps cũng không cứu được**, vì chart bỏ hẳn field `replicas` khi bật
>    `replicasManagedExternally`. Không có `replicas` trong desired state thì ArgoCD không có gì để
>    khôi phục. `kubectl scale` là đòn bẩy **duy nhất** — tức phải làm tay, trái quy ước của chính repo.
>
> **Rủi ro còn lại: 10 service đang bật cờ đó.** `frontend` hoặc `frontend-proxy` rơi vào trạng thái
> này là **mất toàn bộ storefront**. Em xếp đây là việc phải sửa thiết kế chứ không vá vội.
>
> Luồng tiền không bị ảnh hưởng — `cart` và `checkout` giữ 200 suốt sự cố.

**Nếu hỏi "vì sao 42 phút?"** — đây là chi tiết đáng kể vì nó là bẫy cho cả team:

> ~40 phút là phát hiện + chẩn đoán, khôi phục chỉ mất 2 phút sau khi có quyền ghi. Chỗ mất thời gian
> nhất: `~/.kube/config` **hardcode `AWS_PROFILE: nvtank-readonly` bên trong `exec.env`**. Biến môi
> trường đặt ở shell **không thắng được** giá trị đó, nên làm đúng theo tài liệu vẫn nhận `Forbidden`
> mà thông báo lỗi không hề gợi ý vì sao. Em đã ghi cách đi vòng vào CLAUDE.md.

### ❓ "Em có đụng gì tới flagd không?"

> Không. `/flagservice` giữ nguyên trong Envoy, `values-flagd-sync.yaml` không bị đụng, filter
> `envoy.filters.http.fault` giữ nguyên. Cơ chế xuống mềm dùng `local_ratelimit` ở **route riêng**,
> không liên quan tới đường đọc flag.

### ❓ "Em apply tay bao nhiêu lần?"

> Mọi thay đổi cấu hình đều qua PR và ArgoCD. **Một ngoại lệ duy nhất**: `kubectl scale` để khôi phục
> `product-catalog` trong sự cố — và như em nói ở trên, đó là đòn bẩy duy nhất tồn tại, chính điều đó
> là phát hiện của postmortem 0017.

### ❓ "Vì sao checkout gãy trước browse? Không phải browse mới là thứ tải nặng à?"

> Em cũng nghĩ vậy trước khi đo, và đây là chỗ số liệu bác bỏ trực giác.
>
> Browse đọc, nhẹ, và co giãn tốt. Checkout thì **gọi chuỗi service đồng bộ**, trong đó có `email` —
> một service phụ trợ 1 replica, Ruby, giới hạn 100m CPU. Khi `email` nghẽn hàng đợi, nó giữ luôn
> goroutine của checkout, và **hàng đợi của một service gửi mail ăn trọn ngân sách thời gian của
> luồng tiền**.
>
> Đó là lý do việc còn mở #6 của em là **bọc hạn chờ riêng cho `checkout → email`**: một service phụ
> trợ không bao giờ được phép kéo sập đường ra tiền.

---

## 4. Nếu chỉ được nói 3 câu

1. **Trần thật là 1000 user / 202,4 RPS, cao hơn con số cũ 3 lần** — vì con số cũ đo sai phương pháp
   và để node trôi 9→10→11.
2. **Hai trong ba nút thắt không phải CPU** — là connection pinning và queue. Thêm node không chạm
   tới chúng; sửa đúng chỗ thì được **+29% RPS trên cùng 9 node**.
3. **Yêu cầu #2 em báo chưa qua**, và em nói rõ còn thiếu gì, mất bao lâu, xác suất bao nhiêu — chứ
   không tô cho đủ 4/4.

---

## 5. Bảng tra nhanh — số nào ở file nào

| Cần chứng minh | Mở file |
|---|---|
| Trần 1000u / 202,4 RPS | `docs/mandate-19-nghiem-thu.md` §2 |
| Không thêm node | `.../shed-demo/frames/02-dang-overload.png` (`Node count Mean 9 / Max 9`) |
| Nút thắt `email` | báo cáo §3.1 |
| Connection pinning `353m·136m·11m·1m×8` | `.../roundrobin-proof/before-after.txt` |
| Xuống mềm 597 rps | `.../shed-demo/README.md` |
| Counter Envoy 19.539 vs 0 | `.../shed-demo/counters.txt` |
| Trần cuối là hạ tầng | `.../ceiling-root-cause.txt` |
| Sự cố 42 phút | `docs/postmortem/0017-...md` |
| Quyết định + đánh đổi | `docs/adr/0011-...md` |
| Tái lập toàn bộ | `scripts/mandate-19/README.md` |

---

**Ký:** CDO01 — TF3 · 30/07/2026
