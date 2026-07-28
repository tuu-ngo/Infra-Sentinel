# Mandate 12 — Yêu cầu và gap analysis

> **Trạng thái:** READY FOR REVIEW · discovery chỉ đọc hoàn tất; deployment bị block pending gates.

## 1. Mục tiêu

Mandate 12 yêu cầu audit trail của TF3 không thể bị vô hiệu hóa bằng ba cách:

- **Làm mù:** dừng hoặc thay đổi đường ghi log trước khi hành động.
- **Làm hụt:** hoạt động ở resource/API chưa được ghi, đặc biệt đọc S3 object hoặc secret.
- **Làm mỏng/sửa:** log không đủ nội dung để điều tra, hoặc bị thêm/xóa/sửa sau khi giao.

Ngoài ra log phải được giữ đủ lâu cho một cuộc tấn công kéo dài nhiều ngày.

## 2. Bốn yêu cầu và bằng chứng bắt buộc

| Yêu cầu | Kết quả cần đạt | Bằng chứng mentor |
|---|---|---|
| Không có cửa sổ mù | Operator không thể tắt/xóa/đổi coverage mà không bị chặn hoặc báo động | Thử `StopLogging`/`DeleteTrail`; có deny hoặc alert, actor/time và trail status |
| Đóng coverage gap | Đọc S3 object, đọc secret và thay đổi cấu hình quan trọng đều có vết | `GetObject`, `GetSecretValue` canary và config-change event |
| Toàn vẹn mật mã | Log/digest không thể bị sửa/xóa âm thầm; chain gap bị phát hiện | CloudTrail log file validation và `validate-logs` |
| Retention | Có thời gian giữ rõ ràng và không thể rút ngắn tùy tiện | Object Lock/retention/lifecycle evidence |

## 3. Mandate 4 chỉ là tài liệu tham khảo

`MANDATE-4_BTC.md` là đề tham khảo, **không phải work đã hoàn thành** và không được dùng làm bằng chứng hay baseline triển khai. Mandate 12 được phân tích và thiết kế hoàn toàn từ hiện trạng live của product TF3.

Các ý có ích từ đề tham khảo chỉ được dùng để tăng chất lượng solution Mandate 12:

- audit cả AWS cloud và Kubernetes/EKS;
- dựng timeline ai-làm-gì-khi-nào và nội dung thay đổi;
- mọi hành động quy về danh tính cá nhân/session, không dùng chung account.

Mọi CloudTrail, Object Lock, KMS hoặc audit resource đều phải được tạo mới hoặc xác minh trực tiếp từ AWS live; không có giả định “đã có từ Mandate 4”.

## 4. Phạm vi phân tích repository

- Repository: `Phase3-TF3-Infra-Sentinel`.
- Đã loại trừ `docs/docx_cdo02`.
- Phần phân tích repository ở mục này chỉ đọc tĩnh; không chạy Terraform, Kubernetes, test, build hoặc deploy.
- Evidence AWS CLI chỉ đọc được ghi riêng tại mục 7 và revalidation mục 11; không suy diễn trạng thái live từ repository.
- Không suy diễn trạng thái live từ tài liệu thiết kế.

### Quy ước

| Trạng thái | Ý nghĩa |
|---|---|
| `CONFIRMED-REPO` | Có cấu hình hoặc ownership được codify trong repository |
| `VERIFY-LIVE` | Repository không đủ chứng minh, cần truy vấn live chỉ đọc |
| `TARGET` | Control được đề xuất cho Mandate 12, chưa triển khai |

## 5. Hiện trạng dự án liên quan

| Thành phần | Trạng thái | Nhận xét |
|---|---|---|
| AWS account `197826770971`, region chính `ap-southeast-1` | `CONFIRMED-REPO` | Phải đối chiếu caller live trước triển khai |
| Terraform root `infra/live/production` | `CONFIRMED-REPO` | Quản lý network, EKS, access và edge; không nên gộp audit state vào đây |
| EKS API private-only | `CONFIRMED-REPO` | Truy cập qua SSM/Cloudflare; Mandate 12 không thay đổi đường này |
| CloudFront/private origin | `CONFIRMED-REPO` | Storefront/edge nằm ngoài thay đổi audit |
| EKS KMS encryption | `CONFIRMED-REPO` | Không đồng nghĩa CloudTrail archive đã được bảo vệ |
| External Secrets và `techx-tf3/flagd-sync-token` | `CONFIRMED-REPO` | Là resource cần coverage `GetSecretValue`; không dùng secret thật để demo |
| Terraform apply role có `AdministratorAccess` | `CONFIRMED-REPO` | Rủi ro lớn: có thể sửa account-local audit/IAM controls |
| CloudTrail trail đang chạy | `CONFIRMED-LIVE: absent` | `describe-trails --include-shadow-trails` trả danh sách rỗng; chỉ có Event History 90 ngày |
| S3 data-event selectors | `CONFIRMED-LIVE: absent` | Không có trail để chứa selector |
| Log file integrity validation | `CONFIRMED-LIVE: absent` | Không có trail/digest chain |
| S3 Object Lock hiện có | `CONFIRMED-LIVE: absent` | Kiểm tra 7 bucket trong account: không bucket nào có Object Lock configuration |
| EKS control-plane audit logging | `CONFIRMED-LIVE: enabled` | `api`, `audit`, `authenticator` bật; `controllerManager`, `scheduler` tắt |
| EKS audit retention | `CONFIRMED-LIVE` | Log group `/aws/eks/techx-corp-tf3/cluster`, retention 90 ngày, ~1.47 GB; không gắn CMK riêng |
| AWS Organizations/member account | `OUT OF SCOPE` | Account Free Tier đơn lẻ; không dùng Organization/SCP/cross-account archive |
| Datastore/secret Mandate 8 | `CONFIRMED-LIVE: partial` | Có `sosflow/db-password`; chỉ đưa resource khác vào coverage khi tồn tại live |

## 6. Gap analysis

| Mandate control | Gap hiện tại | Mức |
|---|---|---|
| Trail liên tục | Live xác nhận không có trail; chỉ có Event History | Critical |
| Chống operator tắt trail | IAM user thuộc group `AIO2-Admin` có `AdministratorAccess`; cần access migration/boundary | Critical |
| Cảnh báo anti-audit | Chưa thấy EventBridge/SNS controls được codify hoặc xác minh | High |
| S3 object reads | Không có trail/data events | Critical |
| Secret reads | Có 2 secret live nhưng không có durable trail thu `GetSecretValue` | Critical |
| Config changes | Không có durable CloudTrail coverage cho IAM/KMS/S3/EKS/CloudTrail | Critical |
| Integrity digest | Không có trail nên không có validation/digest | Critical |
| WORM retention | Không bucket nào có Object Lock | Critical |
| EKS forensic | EKS `api`/`audit`/`authenticator` đang bật nhưng chỉ lưu CloudWatch 90 ngày; không thay CloudTrail archive | High |
| Identity attribution | Có assume-role patterns nhưng còn admin identity; cần kiểm tra shared credential/session | High |

## 7. Live discovery bắt buộc trước phê duyệt triển khai

Chỉ đọc, không mutation:

1. Caller/account/region thực tế.
2. `describe-trails`, `get-trail-status`, event selectors và validation.
3. Bucket/KMS/Object Lock/lifecycle hiện có trong account.
4. EKS control-plane log types, CloudWatch log group và retention.
5. IAM users/roles có `AdministratorAccess`, cách CI assume apply role và break-glass path.
6. Danh sách bucket/prefix nhạy cảm hiện có.
7. Danh sách secret hiện có; không đọc secret value.
8. Event volume/cost baseline.

### Kết quả discovery live ngày 17/07/2026

Discovery chỉ đọc được chạy bằng IAM identity `arn:aws:iam::197826770971:user/cdo-2-admin-team` tại `ap-southeast-1`; không đọc `SecretString` và không gọi API mutation.

| Kiểm tra | Kết quả |
|---|---|
| CloudTrail | Không có trail (`trailList: []`) |
| CloudTrail Event History | Có management events 90 ngày, nhưng không thay thế trail/S3 archive/digest |
| EKS logs | `api`, `audit`, `authenticator` enabled; log group 90 ngày |
| Secrets metadata | `sosflow/db-password`, `techx-corp-tf3/flagd-sync-token` |
| IAM identity | User thuộc group `AIO2-Admin`; group gắn `AdministratorAccess` và `AWSBillingReadOnlyAccess` |
| S3 | Có 7 bucket; không bucket nào có Object Lock configuration; chỉ `techx-products-catalog-2026` và `techx-tf3-197826770971-tfstate` trả Versioning `Enabled` |

Kết luận discovery: Mandate 12 không thể tái sử dụng audit trail/Object Lock có sẵn vì hiện không có. EKS audit log là asset duy nhất đã vận hành có thể giữ lại và nối vào forensic timeline. Audit foundation phải tạo mới, còn IAM hardening là change riêng bắt buộc trước mentor deny test.

## 8. Ràng buộc

- Không thay đổi application source, workload, datastore, network, edge hoặc flagd.
- Giữ storefront public và ops private.
- Không vượt khoảng `$300/tuần/TF`.
- Không dùng root user hoặc shared credential cho vận hành thường ngày.
- Không coi Terraform plan hay tài liệu là bằng chứng `VERIFIED`.

## 9. Kết luận

Repository có nền IaC, private access, KMS và identity flows tốt để triển khai audit độc lập. Discovery live ngày 17/07/2026 đã hoàn tất và xác nhận các gap: chưa có CloudTrail, Object Lock hay S3 data-event coverage; current admin vẫn có `AdministratorAccess`. Vì vậy Mandate 12 là **NOT READY FOR DEPLOY/VERIFY**, không còn ở trạng thái “chưa kiểm tra live”. Solution gồm audit foundation và IAM hardening là hai change riêng.

**Giải thích mục 9:**  
**1.**Nên chia làm 2 giai đoạn sau:    
Audit foundation: tạo CloudTrail, audit S3 bucket có Object Lock 365 ngày, log integrity validation, alert. Mục tiêu: bắt đầu có log đầy đủ và không dễ bị xóa.  
**2.**IAM hardening: giảm/tách quyền của user/role vận hành để họ không thể tắt CloudTrail, xóa log hoặc tắt alert. Mục tiêu: chống “người có quyền admin” làm mù audit. 

## 10. Kết luận static readiness

**Đủ để lập bốn tài liệu và bắt đầu chuẩn bị deployment; chưa đủ để apply.** Static review xác nhận đúng account/region mục tiêu (`ap-southeast-1`), Terraform root production (`infra/live/production`), backend S3 và các workload nhạy cảm cần coverage (EKS, Secrets Manager, Terraform state).

| Static evidence | Ý nghĩa với Mandate 12 |
|---|---|
| `infra/live/production` có provider AWS, backend S3 và tag chuẩn TF3 | Có convention rõ để chuẩn bị một Terraform root audit tách biệt, tránh sửa workload root hiện hữu |
| `infra/bootstrap/backend` đã có S3 state versioning, encryption và public-access block | Có mẫu hạ tầng state; không đồng nghĩa bucket audit có Object Lock |
| Không tìm thấy `aws_cloudtrail` trong `infra/` | Audit foundation chưa được quản lý bằng IaC; deployment phải bổ sung resource mới |
| `external-secrets.tf` dùng `secretsmanager:GetSecretValue` | Secrets Manager là coverage bắt buộc, không chỉ management events |
| GitHub Terraform apply role gắn `AdministratorAccess` | Chưa có operator boundary đủ mạnh; IAM hardening phải là change riêng có migration/test |

Các thông tin còn thiếu bắt buộc phải lấy bằng approval hoặc revalidation chỉ đọc trước apply: bucket/prefix S3 cần data events, tên audit bucket, SNS owner, permission thực tế của CI và ảnh hưởng plan. Không suy diễn các giá trị này từ repository.

## 11. Revalidation AWS CLI ngày 17/07/2026

Discovery chỉ đọc được chạy lại bằng `arn:aws:iam::197826770971:user/cdo-2-admin-team` tại `ap-southeast-1`. Không có API mutation, không đọc `SecretString` hay object S3.

| Hạng mục | Kết quả xác nhận |
|---|---|
| CloudTrail | `describe-trails --include-shadow-trails` trả `trailList: []` |
| EKS | `api`, `audit`, `authenticator` bật; log group retention 90 ngày, không có CMK riêng |
| IAM | User hiện tại thuộc `AIO2-Admin`; group gắn `AdministratorAccess` và `AWSBillingReadOnlyAccess` |
| Secrets | Có metadata của `sosflow/db-password` và `techx-corp-tf3/flagd-sync-token`; không đọc giá trị |
| S3 | 7 bucket; chỉ product catalog và TF3 state có Versioning `Enabled`; không bucket nào có Object Lock |

Kết quả giữ nguyên quyết định: tạo audit foundation mới, chỉ deploy khi S3 data-event scope và alert owner đã được phê duyệt; tách IAM hardening khỏi change foundation. Bảng này là tóm tắt revalidation của evidence table ở mục 7, không thay thế evidence gốc.

### Mô hình account đã xác nhận

- TF3 vận hành trong **một AWS account Free Tier**: `197826770971`.
- “Sub account” của team là IAM user hoặc IAM role trong chính account này; không phải AWS member account.
- AWS Organizations, management account, cross-account archive và SCP **không thuộc scope** của Mandate 12 hiện tại.
- Control được triển khai bằng CloudTrail account-level, audit S3 bucket, IAM role/policy/boundary và EventBridge/SNS trong cùng account.

---

**Phiên bản:** v1.4  
**Cập nhật:** 18/07/2026  
**Trạng thái:** READY FOR REVIEW — deployment blocked pending gates
