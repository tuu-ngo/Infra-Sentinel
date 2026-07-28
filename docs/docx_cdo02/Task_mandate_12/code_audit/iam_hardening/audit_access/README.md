# Audit-admin và break-glass (staging)

Terraform root độc lập này tạo hai role **không phải admin** trong cùng AWS account:

- `tf3-m12-audit-admin`: chỉ đọc CloudTrail/archive/rule/topic để điều tra và xác minh integrity.
- `tf3-m12-audit-breakglass`: chỉ `cloudtrail:StartLogging`, `events:EnableRule`, đọc trạng thái và gửi test SNS. Role này không có quyền Stop/Delete/Update trail, sửa bucket, sửa target rule hay sửa topic.

## Dependency và vị trí triển khai

Deploy sau foundation, trong Terraform state/PR IAM riêng. Khi được duyệt, copy **toàn bộ** thư mục này vào `Phase3-TF3-Infra-Sentinel/infra/live/iam/mandate-12/audit_access/`. Đây là Terraform root hoàn chỉnh, không cần wrapper module hay provider từ stack khác.

1. Copy `backend.hcl.example` thành `backend.hcl` trong workspace deploy và điền **state bucket/DynamoDB lock table đã tồn tại, được phê duyệt**. Dùng key riêng `mandate-12/audit_access/terraform.tfstate`; không chia sẻ key/state với foundation.
2. Copy `terraform.tfvars.example` thành `terraform.tfvars`, thay toàn bộ placeholder bằng output foundation thật. Hai file local này bị `.gitignore`; không commit credentials, backend hay định danh security owner không cần công khai.

Input bắt buộc lấy từ output foundation thật:

1. `audit_bucket_arn`, `audit_trail_arn`, cả hai `alert_topic_arns` (`alert_topic_arn` ở `ap-southeast-1`, `global_alert_topic_arn` ở `us-east-1`) và **toàn bộ 12** `audit_rule_arns` từ hai output map foundation. Validation từ chối mọi input không đúng chính xác 2 topic và 12 rule; không tự chọn subset. Map primary có `trail`, `trail_selectors`, `bucket`, `event_rule`, `event_target`, `sns_topic`, `sns_subscription`; map global có `iam`, `event_rule`, `event_target`, `sns_topic`, `sns_subscription`.
2. `trusted_principal_arns`: chỉ user/role security owner định danh được, MFA-capable; tuyệt đối không dùng account root hoặc wildcard account principal.
3. `require_mfa = true` cho người vận hành. Nếu role CI không có MFA, không thêm nó vào trust này; tạo role CI tối thiểu riêng và đưa qua review.

Trust policy không tự cấp quyền gọi `sts:AssumeRole`. Module tạo output `security_owner_assume_audit_policy_arn`: attach policy tối thiểu này, trong IAM change được review riêng, vào **đúng từng** principal trong `trusted_principal_arns`. Không attach qua group rộng, không attach vào operator thường, không dùng wildcard. Lưu mapping `principal ARN -> policy ARN -> audit role ARN` vào evidence; sau đó simulation phải cho phép security owner assume hai audit role và từ chối các principal khác.

Ví dụ kiểm tra trước apply trong workspace được phê duyệt:

```powershell
terraform fmt -check -recursive
terraform init -backend-config=backend.hcl
terraform validate
terraform plan -var-file=terraform.tfvars
```

Sau apply, lưu hai output role ARN. Trong **bản boundary allowlisted** (không phải bản strict mặc định), điền hai ARN này vào `DenyAssumeProtectedAuditRoles`, **không** đưa chúng vào allowlist. Test trust bằng security owner có MFA và kiểm tra operator thường nhận `AccessDenied`.

## Giới hạn thiết kế

- Đây không thể chống account root hay một principal `AdministratorAccess` chưa bị boundary; single account không có SCP/organization isolation.
- Break-glass chỉ phục hồi logging/rule bị disable. Nếu root xóa foundation, khôi phục qua Terraform change được phê duyệt, không cấp Delete/Update cho break-glass.
- `prevent_destroy` là guardrail Terraform, không thay thế IAM explicit deny hay Object Lock.

---

**Phiên bản:** v1.1  
**Cập nhật:** 18/07/2026  
**Trạng thái:** STAGING — không deploy trước foundation, trust-owner review và change approval
