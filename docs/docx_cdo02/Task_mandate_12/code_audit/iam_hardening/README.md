# IAM hardening — Mandate 12

Đây là **change IAM độc lập**, thực hiện sau khi audit foundation đã chạy và đã có bằng chứng CloudTrail ghi log. Không gộp vào PR foundation, không attach trực tiếp vào root, audit-admin hoặc break-glass.

## Artifact

| File/thư mục | Tác dụng |
|---|---|
| `operator-boundary-policy.template.json` | Boundary mặc định an toàn: chặn toàn bộ assume-role của operator cho tới khi hoàn thành inventory. |
| `operator-boundary-policy.allowlisted-assume-role.template.json` | Chỉ dùng khi workflow bắt buộc role chaining; cho phép đúng ARN role đã duyệt và vẫn chặn audit-admin/break-glass. |
| `audit_access/` | Terraform root độc lập tạo hai role tối thiểu, tái lập được: `audit-admin` chỉ đọc bằng chứng và `break-glass` chỉ khôi phục `StartLogging`/`EnableRule`. |
| `iam_change/` | Terraform root độc lập tạo executor MFA để version một boundary đã review và attach đúng boundary đó vào target đã inventory; không phải daily admin. |

## Boundary bảo vệ gì

`DenyAnyAccessToAuditArchive` dùng `s3:*` **chỉ trên audit bucket và object của nó**. Vì vậy operator bị chặn cả xóa, ghi đè, thay retention/Object Lock, lifecycle, encryption, policy, public-access block và đọc archive. Đây cũng loại bỏ các tên action S3 cũ không hợp lệ; CloudTrail service principal và audit role riêng không mang boundary này nên vẫn ghi/đọc theo bucket policy và role policy.

`DenyIamPrivilegeAndCredentialMutation` chặn các nhóm action IAM làm tăng hoặc chuyển quyền: tạo/sửa/xóa user, role, group, policy, trust policy (`iam:UpdateAssumeRolePolicy`), permissions boundary, access key, login profile, service credential, MFA device, federation provider, instance profile và `iam:PassRole`. Hai action EC2 gắn/thay instance profile cũng bị chặn riêng. Quyền IAM chỉ đọc vẫn còn để discovery.

## Chọn template assume-role

1. Mặc định dùng `operator-boundary-policy.template.json`. Nó chặn `sts:AssumeRole`, `AssumeRoleWithSAML` và `AssumeRoleWithWebIdentity`; đây là lựa chọn đúng nếu operator không có workflow role chaining.
2. Nếu simulation chứng minh workflow cần role chaining, **không xóa deny để cho phép rộng**. Dùng bản `allowlisted`, thay `<approved-non-audit-role-arn-1>` bằng từng target role đã inventory và được security owner duyệt.
3. Mỗi target role được allowlist phải có policy tối thiểu và boundary bảo vệ audit tương đương hoặc mạnh hơn. Không được allowlist role `AdministratorAccess` không boundary, audit-admin hay break-glass; bản template đã explicit-deny hai role audit để tránh sai sót.
4. Đổi mọi placeholder thành ARN thật trước khi tạo managed policy. Placeholder còn sót phải làm validation/PR thất bại, không được thay bằng `*`.

Lý do: boundary chỉ giới hạn principal đang mang nó. Nếu principal assume được một role không bị giới hạn, session của role đó có thể đi vòng boundary. Vì thế assume-role cần inventory/allowlist, không xử lý bằng blanket allow cũng không giả định AWS Organizations/SCP.

## Thứ tự triển khai an toàn

1. Deploy foundation; lưu output trail ARN, audit bucket ARN, hai SNS topic ARN (`alert_topic_arn`, `global_alert_topic_arn`) và đủ 12 EventBridge rule ARN từ hai output map (primary: 7, global: 5).
2. Deploy Terraform root `audit_access/` trong PR/terraform state riêng; lưu output audit-admin, break-glass và `security_owner_assume_audit_policy_arn`. Xác nhận trust chỉ gồm security owner đã MFA, không có root; attach policy assume này thủ công vào đúng security owner trong IAM review riêng.
3. Lấy cả `alert_subscription_arn` và `global_alert_subscription_arn` sau khi recipient xác nhận subscription. Nếu một subscription đang `PendingConfirmation`, dừng tại đây.
4. Tạo managed policy từ **một** template đã điền đủ ARN; chạy parse JSON và IAM policy simulation cho từng identity trước khi attach.
5. Deploy Terraform root `iam_change/` sau khi managed boundary policy đã tồn tại; dùng output `security_owner_assume_iam_change_policy_arn` để cấp quyền assume thủ công cho đúng security owner. Security owner MFA dùng executor này để attach boundary từng user/role operator, smoke-test workload, rồi mới mở rộng. Nếu một workflow cần IAM mutation hoặc assume-role, tạo change/role tối thiểu riêng và review lại — không nới boundary hàng loạt.
6. Chạy attack tests: operator thử `StopLogging`, sửa/xóa archive, tắt rule/SNS, `UpdateAssumeRolePolicy`, tạo access key, gắn instance profile và assume unapproved role. Tất cả phải `AccessDenied`; audit-admin vẫn đọc được evidence; break-glass chỉ khôi phục được logging/rule.

## Giới hạn cần chấp nhận

- Root và bất kỳ admin identity **chưa mang boundary** vẫn là residual risk trong single AWS account; không được tuyên bố "không ai" bị chặn trước khi inventory/attach hoàn tất.
- `AllowBaselineWithinBoundary` có `Action: "*"` vì permissions boundary cần Allow ceiling. Nó không tự cấp quyền; explicit Deny ở dưới luôn ưu tiên. IAM Access Analyzer có thể cảnh báo về baseline này; đó không phải allow mới, nhưng simulation theo từng operator là bắt buộc. Ngoài role assumption, boundary cũng chặn `sts:GetFederationToken` để không tạo session federated đi vòng inventory; `GetSessionToken` không tăng quyền nên không bị chặn.
- Audit roles không sửa/xóa trail, bucket, rule hoặc topic. Khi foundation bị xóa bởi root/break-glass, khôi phục phải qua IaC change được phê duyệt và có evidence, không trao quyền phá hủy cho break-glass.

---

**Phiên bản:** v1.2  
**Cập nhật:** 18/07/2026  
**Trạng thái:** STAGING — chờ foundation output, audit-access roles, subscription confirmation, IAM inventory và approval
