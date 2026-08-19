# Drill AZ 30/07/2026 — HUỶ GIỮA CHỪNG, bắn nhầm AZ

> **Đọc file này trước khi đọc bất kỳ file evidence nào trong thư mục.**
> Đây **KHÔNG** phải bằng chứng nghiệm thu Mandate 17 req#2. Bài diễn tập đã bị
> huỷ sau ~75 giây vì experiment nhắm sai Availability Zone.

## Tóm tắt

| | |
|---|---|
| Định bắn | `ap-southeast-1b` (`subnet-045de0d768b5c49f1`) |
| Thực tế bắn | **`ap-southeast-1c`** (`subnet-0fdf5cd134c155b94`) |
| Experiment | `EXPLrvN7DigSFBzBer` (template `EXT9JSZivevPf3Hoe`) |
| Chạy | 16:25:53Z → 16:27:11Z (**~78 giây**, `duration` thiết kế là PT5M) |
| Dừng bởi | Người vận hành, theo tiêu chí ABORT §7 của runbook |
| Rollback | ✅ cả 2 subnet về `acl-0c7e1cead7edbc9f3`; storefront `200/200` |

## Vì sao nhắm sai

CloudTrail:

```
14:26:59Z  UpdateExperimentTemplate
           IP        185.165.240.72
           key       access key DÀI HẠN của IAM user dùng chung cdo-2-admin-team
                     (giá trị đầy đủ tra trong CloudTrail — cố ý không chép vào đây)
           userAgent Terraform/1.15.4 ... os/windows      <- apply CHẠY LOCAL
           đổi target -> subnet 1c
```

Tra lại bằng:

```bash
aws cloudtrail lookup-events --region ap-southeast-1 \
  --lookup-attributes AttributeKey=EventName,AttributeValue=UpdateExperimentTemplate
```

Đối chiếu: `13:09:36Z CreateExperimentTemplate` từ `130.131.202.36` bằng **credential tạm
thời** (`ASIA…`, tức OIDC của GitHub Actions) — workflow đã tạo **đúng 1b**. Sau đó
**1h17m**, một máy Windows khác chạy `terraform apply` local bằng **key dài hạn dùng
chung**, ngoài đường `plan → duyệt → apply`, và ghi đè thành 1c. Máy chủ trì drill
(`116.110.17.193`) không đụng vào: file local trùng `main`,
`default = "ap-southeast-1b"`, không tfvars, không `TF_VAR`.

Bản `04-template-before.txt` chụp lúc 16:19 **đã chứa subnet 1c**, nhưng lúc đó không ai
đối chiếu số subnet với AZ mong muốn. Đó là chỗ đáng lẽ chặn được.

## Đọc `10-external-probe.log` cho đúng

691 mẫu. **KHÔNG phải mọi lỗi trong log đều do drill.**

| Mốc | Nội dung | Nguyên nhân |
|---|---|---|
| 16:26:15 – 16:26:32 | `500`, rồi `000` timeout trên `/api/products` và `/api/cart` | ✅ **do fault 1c** |
| 16:27:33 | một `500` lẻ | dư chấn hồi phục |
| **16:32:45 – 16:32:52** | ba `500` trên `/api/products` | ❌ **KHÔNG do drill** — fault đã tắt 5 phút. `product-catalog` bão hoà CPU, HPA scale 2→3 lúc 16:33; kèm readiness timeout ở `product-reviews`, `recommendation`, `checkout`. Mọi pod `0 restarts`. |
| 16:34:56 trở đi | toàn `200` | đã ổn định |

`/` luôn giữ `200` suốt bài nhờ cache CloudFront — **không được dùng riêng nó làm bằng
chứng "vẫn sống"**, phải xem các path `/api/*`. Nếu probe chỉ ping `/`, bài này đã "pass"
một cách sai hoàn toàn.

### Dòng gốc (log đầy đủ đã xoá; đây là phần có giá trị)

Cột: `<utc>  <mã / ms cho />  <mã / ms cho /api/products>  <mã / ms cho /api/cart>`

```
2026-07-30T16:26:07Z  200 0.127639  200 0.116019  200 0.127224   <- bình thường
2026-07-30T16:26:15Z  200 0.127664  500 1.297727  500 5.747290   <- FAULT bắt đầu cắn
2026-07-30T16:26:24Z  200 0.199329  200 0.125431  500 5.801469
2026-07-30T16:26:32Z  200 0.201837  000 10.001352 000 10.001649  <- timeout hoàn toàn
2026-07-30T16:27:33Z  200 0.233339  500 1.339209  200 0.121820   <- dư chấn sau khi dừng
2026-07-30T16:32:45Z  200 0.142554  500 1.353205  200 0.146522   <- KHÔNG do drill
2026-07-30T16:32:49Z  200 0.120773  500 1.329825  200 0.125456      (CPU product-catalog
2026-07-30T16:32:52Z  200 0.158613  500 1.331061  200 0.106138       + HPA scale 2->3)
2026-07-30T16:34:56Z  200 0.135077  200 0.123470  200 0.123131   <- đã ổn định
2026-07-30T16:35:07Z  200 0.200567  500 1.358628  200 0.195700   <- vẫn còn lác đác
2026-07-30T16:35:11Z  200 0.101201  500 1.312986  200 0.220252
```

Tổng 691 mẫu: 6 lỗi `5xx`, 1 lần `000` timeout.

**Việc phát sinh riêng:** `/api/products` còn trả `500` lác đác tới tận 16:35, tức **8 phút
sau khi fault tắt**. `product-catalog` bão hoà CPU chứ không phải do drill — nhưng nó cho
thấy dịch vụ này thiếu headroom ở mức tải bình thường. Cần điều tra riêng, ngoài Mandate 17.

## Phát hiện thật, dù bài bị huỷ

**`frontend` (2/2) và `frontend-proxy` (2/2) nằm trọn trong 1c.** Mất 1c là mất toàn bộ
cửa vào storefront — probe đã chứng minh bằng số. Đây là **lỗ hổng req#2 thật**, và bài
1b theo kế hoạch sẽ không bao giờ phát hiện.

Danh sách service dồn hết vào đúng một AZ (đo 30/07):

```
1a : accounting, grafana
1b : ad, aiops-engine, fraud-detection, image-provider, jaeger, llm,
     opensearch, recommendation
1c : flagd, frontend(2), frontend-proxy(2), prometheus
```

## Việc phải làm trước khi diễn tập lại

1. Chốt với team: **không `terraform apply` local vào state production**. Hỏi ai chạy
   lúc 21:26 giờ VN và vì sao đổi sang 1c.
2. Access key **dài hạn** của IAM user dùng chung `cdo-2-admin-team` xuất hiện từ **3 IP**
   khác nhau trong một ngày → CloudTrail không quy trách nhiệm được cho người cụ thể.
   Đường đúng là OIDC/credential tạm như GitHub Actions đang dùng.

> **Lưu ý khi viết evidence:** không chép giá trị access key ID vào tài liệu trong repo —
> gitleaks (rule `aws-access-token`) sẽ chặn PR, và **cách xử lý đúng là bỏ giá trị đó đi,
> KHÔNG phải thêm fingerprint vào `.gitleaksignore`**. Mô tả bằng lời và trỏ về CloudTrail
> là đủ để tái lập.
3. Đưa template về 1b và **xác minh bằng máy** ngay trước khi bắn —
   `drill-capture.ps1 -Phase before` nay tự so AZ của template với AZ mục tiêu và chặn.
4. Sửa placement `frontend` / `frontend-proxy` (finding riêng, không thuộc drill).
