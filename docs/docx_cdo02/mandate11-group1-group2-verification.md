# Mandate 11 - Xác minh Group 1 và Group 2

**Người phụ trách:** Phạm Tùng Dương

**Ngày rà soát tĩnh:** 20/07/2026

**PR nguồn:** [#219 - Mandate 11 audit detection](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/219)

**Trạng thái:** `STATIC REVIEW COMPLETE` / `RUNTIME VERIFICATION PENDING`

## 1. Phạm vi và giới hạn của lần xác minh này

Tài liệu này xác minh bằng code hai nhóm sự kiện được giao:

- **Group 1:** hành động làm mù hoặc làm yếu audit/log;
- **Group 2:** hành động tạo credential hoặc principal mới, mở thêm đường truy cập.

Luồng được đối chiếu trực tiếp là:

`CloudTrail -> EventBridge default bus -> Lambda audit-alert-router -> SNS email -> người vận hành`

Các file nguồn:

- [cấu hình rule production](../../infra/live/production/audit-detection.tf);
- [module EventBridge, Lambda, SNS và DLQ](../../infra/modules/audit-detection/main.tf);
- [Lambda phân loại và dựng payload cảnh báo](../../infra/modules/audit-detection/lambda/index.py).

Đây chưa phải bằng chứng chạy thật. PR #219 đã được merge rồi bị revert bởi PR #274, nên code trên source branch không đồng nghĩa với hạ tầng đang hoạt động trong production. Không dùng tài liệu này để kết luận Mandate 11 đã runtime pass.

## 2. Kết quả xác minh Group 1

### 2.1. Mục tiêu

Group 1 phát hiện nỗ lực làm mất khả năng quan sát trước khi thực hiện hành động khác. Các sự kiện này phải là `critical` đối với cả con người và automation. Một thay đổi bảo trì hợp lệ chỉ được giảm nhiễu bằng suppression có actor, resource, thời gian bắt đầu, thời gian kết thúc và lý do rõ ràng.

### 2.2. Event được khai báo

| Event source | Event name | Ý nghĩa rủi ro | Region/rule | Lambda group |
|---|---|---|---|---:|
| `cloudtrail.amazonaws.com` | `StopLogging` | Dừng ghi audit trail | `ap-southeast-1` / `g1-audit` | 1 |
| `cloudtrail.amazonaws.com` | `DeleteTrail` | Xóa đường ghi audit | `ap-southeast-1` / `g1-audit` | 1 |
| `cloudtrail.amazonaws.com` | `UpdateTrail` | Thay đổi đích hoặc phạm vi ghi log | `ap-southeast-1` / `g1-audit` | 1 |
| `cloudtrail.amazonaws.com` | `PutEventSelectors` | Thu hẹp loại event được lưu | `ap-southeast-1` / `g1-audit` | 1 |
| `cloudtrail.amazonaws.com` | `StartLogging` | Tín hiệu cần đối chiếu sau một lần dừng bất thường | `ap-southeast-1` / `g1-audit` | 1 |
| `logs.amazonaws.com` | `DeleteLogGroup` | Xóa nơi lưu log | `ap-southeast-1` / `g1-audit` | 1 |
| `logs.amazonaws.com` | `PutRetentionPolicy` | Có thể giảm thời gian lưu bằng chứng | `ap-southeast-1` / `g1-audit` | 1 |

### 2.3. Kết quả code review

- Rule `g1-audit` match đúng `source`, `detail.eventSource` và `detail.eventName`.
- `GROUP_MAP` ánh xạ đủ bảy event về Group 1.
- `critical_group_numbers = [1, 2, 4]`, vì vậy Group 1 được gán severity `critical`.
- Payload đã khai báo event name, actor, event time, detected time, TTD, source IP, region, user agent, target và request summary.

Kết quả: **đạt ở mức khai báo tĩnh**, chưa đạt runtime acceptance do các blocker tại mục 5.

## 3. Kết quả xác minh Group 2

### 3.1. Mục tiêu

Group 2 phát hiện việc tạo thêm credential hoặc principal có thể dùng để duy trì quyền truy cập sau khi một tài khoản quản trị bị lạm dụng. Các event này phải là `critical`. Hoạt động CI/CD hợp lệ không nên dùng allowlist vĩnh viễn; nếu cần giảm nhiễu thì dùng suppression hẹp và tự hết hạn.

### 3.2. Event được khai báo

| Event source | Event name | Ý nghĩa rủi ro | Region/rule | Lambda group |
|---|---|---|---|---:|
| `iam.amazonaws.com` | `CreateAccessKey` | Tạo credential dài hạn mới | `us-east-1` / `g2-new-access` | 2 |
| `iam.amazonaws.com` | `CreateUser` | Tạo principal IAM mới | `us-east-1` / `g2-new-access` | 2 |
| `iam.amazonaws.com` | `CreateRole` | Tạo đường assume role mới | `us-east-1` / `g2-new-access` | 2 |
| `iam.amazonaws.com` | `CreateLoginProfile` | Bật đăng nhập console cho IAM user | `us-east-1` / `g2-new-access` | 2 |

IAM là global service; rule được đặt tại `us-east-1`, còn trail multi-region được tạo ở module `ap-southeast-1` với global service events bật.

### 3.3. Kết quả code review

- Rule `g2-new-access` match đúng `aws.iam`, `iam.amazonaws.com` và bốn event tạo access path.
- `GROUP_MAP` ánh xạ đủ bốn event về Group 2.
- Group 2 được gán severity `critical`.
- `extract_target()` lấy được `userName` hoặc `roleName` cho bốn trường hợp này.

Kết quả: **đạt ở mức khai báo tĩnh**, chưa đạt runtime acceptance do các blocker tại mục 5.

## 4. Ma trận đối chiếu với Mandate 11

| Yêu cầu | Bằng chứng trong code | Trạng thái |
|---|---|---|
| Danh mục hành động nguy hiểm | Event catalog Group 1/2 và giải thích rủi ro ở mục 2-3 | Static pass |
| Rule bắt đúng event | `g1-audit`, `g2-new-access` và `GROUP_MAP` | Static pass |
| Mức độ cảnh báo | Group 1/2 nằm trong `critical_group_numbers` | Static pass |
| Định tuyến tới người | Lambda publish tới SNS email subscription | Provisioned in code; delivery pending |
| Ngữ cảnh ai/gì/khi/đâu | Payload có actor, event, timestamp, IP, region, user agent và target | Partial; xem blocker B-01/B-03 |
| Time-to-detect | Lambda tính `detectedAt - detail.eventTime` và publish metric | Detector latency only; runtime pending |
| Giảm nhiễu đáng tin | Có allowlist và time-bounded suppression | Fails acceptance until B-02 is fixed |
| Mentor tự bấm kiểm | Quy trình ở mục 6 | Not run |

## 5. Blocker phải đóng trước khi ghi runtime pass

### B-01 - EventBridge `resources: []` có thể làm Lambda lỗi

Lambda đang lấy `event.get("resources", [fallback])[0]`. Khi key `resources` tồn tại nhưng là mảng rỗng, code phát sinh `IndexError` trước khi ghi metric và gửi SNS. Cần lấy rule name theo cách an toàn hoặc dùng một giá trị fallback khi danh sách rỗng.

### B-02 - Allowlist automation đang áp dụng quá rộng

`is_allowed_automation(actor)` được kiểm tra trước logic theo group, nên principal được allowlist có thể làm `StopLogging` hoặc `CreateAccessKey` mà không phát cảnh báo. Group 1 phải luôn alert; Group 2 chỉ được suppress bằng rule hẹp, có resource và thời gian hết hạn.

### B-03 - Trường `actor` chưa đủ chi tiết cho assumed role

`extract_actor()` ưu tiên ARN của `sessionIssuer`, làm mất role-session name hoặc source identity. Với shared role, cảnh báo chỉ cho biết role chung chứ chưa chắc chỉ ra người thật thực hiện hành động.

### B-04 - Chưa có bằng chứng cảnh báo tới tay người

Cần xác nhận SNS email subscription đã active và chụp email thực nhận. TTD hiện được lấy trước khi `SNS.publish`, nên chỉ chứng minh thời gian tới Lambda, chưa chứng minh thời gian tới mailbox/on-call.

### B-05 - Branch chưa phải trạng thái deploy

Code PR #219 không còn trong `main` sau PR #274. Phải có một thay đổi integration được phê duyệt và Terraform apply thành công trước khi chạy mentor verification.

## 6. Quy trình runtime verification sau khi hạ tầng sẵn sàng

### 6.1. Điều kiện trước khi test

- B-01 và B-02 đã được sửa và review;
- Terraform plan/apply thành công ở đúng account/region;
- EventBridge rules đang `ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS`;
- Lambda không có error/throttle đang mở;
- ít nhất một SNS email subscription ở mỗi topic đã được xác nhận;
- đồng hồ máy test dùng UTC hoặc đã ghi rõ timezone.

### 6.2. Hành động test khuyến nghị

Dùng `CreateUser` thay vì `CreateAccessKey` để không tạo secret credential cần che khỏi ảnh/Jira:

```powershell
$VerifyUser = "mandate11-verify-$(Get-Date -Format 'yyyyMMddHHmmss')"
aws iam create-user --user-name $VerifyUser
```

Sau khi đã thu bằng chứng cảnh báo:

```powershell
aws iam delete-user --user-name $VerifyUser
```

Không chạy `StopLogging` trên trail production để demo. Chỉ dùng Group 1 nếu team đã tạo trail test riêng và có kế hoạch bật lại được phê duyệt.

### 6.3. Tiêu chí pass

- email/on-call nhận cảnh báo trong `<= 5 phút` kể từ `detail.eventTime`;
- payload/email có đủ actor, event name, event time, source IP/region/user agent và target;
- CloudWatch log có cùng event và `time_to_detect_seconds`;
- custom metric `AuditDetectionLatencySeconds` xuất hiện;
- không có Lambda error, failed invocation hoặc DLQ message cho test thành công;
- tài nguyên test được dọn sau khi thu bằng chứng.

### 6.4. Bảng điền kết quả

| Test ID | Event | CloudTrail event time (UTC) | Lambda detectedAt (UTC) | Email receivedAt (UTC) | Detector TTD | End-to-end TTD | Pass/Fail | Evidence link |
|---|---|---|---|---|---:|---:|---|---|
| G2-01 | `CreateUser` | Pending | Pending | Pending | Pending | Pending | Not run | Pending |
| G1-01 | Event trên trail test | Pending | Pending | Pending | Pending | Pending | Not run | Pending |

## 7. Bằng chứng Jira

Có thể nộp ngay cho phần static review:

1. link commit chứa comment Group 1/2 và hai tài liệu Mandate 11;
2. ảnh diff `GROUP_MAP` cho Group 1/2;
3. ảnh bảng event và ma trận đối chiếu trong tài liệu này;
4. link PR #219 để truy vết nguồn thiết kế.

Chỉ nộp sau khi hạ tầng chạy cho phần runtime:

1. CloudTrail event detail của test;
2. CloudWatch Lambda log chứa payload và detector TTD;
3. email SNS thực nhận, có timestamp;
4. CloudWatch metric hoặc dashboard TTD;
5. trạng thái EventBridge rule, Lambda và DLQ;
6. bằng chứng xóa IAM user/trail test sau demo.

Không đưa access key, secret value, token, password hoặc nội dung nhạy cảm vào ảnh/Jira. Che account ID và email cá nhân nếu Jira có người ngoài team.
