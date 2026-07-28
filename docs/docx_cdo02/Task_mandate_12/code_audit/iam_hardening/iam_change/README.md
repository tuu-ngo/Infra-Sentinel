# IAM change executor (staging)

Đây là Terraform root độc lập cho role `tf3-m12-iam-change`. Role này thay cho việc dùng daily admin không boundary để attach/cập nhật operator boundary sau khi Mandate 12 đi vào vận hành.

## Quyền chính xác

- Được version một **managed policy boundary ARN duy nhất** đã render/review (`CreatePolicyVersion`, `SetDefaultPolicyVersion`, `DeletePolicyVersion`). Không được tạo hoặc xóa policy.
- Được attach **đúng boundary đó** vào user/role được liệt kê rõ trong `target_user_arns`/`target_role_arns`.
- Không có quyền CloudTrail, S3, EventBridge, SNS, `iam:PassRole`, role trust, access key, group, policy attachment hoặc tạo/xóa IAM principal.
- Xóa boundary bị tắt mặc định. Muốn rollback phải PR/approval riêng, đặt `allow_boundary_removal = true`, apply, lưu evidence, rồi trả về `false`.

## Vị trí và thứ tự deploy

Khi được duyệt, copy toàn bộ thư mục này vào `Phase3-TF3-Infra-Sentinel/infra/live/iam/mandate-12/iam_change/`. Đây là root độc lập với state key `mandate-12/iam-change/terraform.tfstate`.

1. Deploy foundation, rồi `audit_access/`.
2. Render template boundary với output foundation/subscription ARN, review và tạo managed policy ban đầu bằng bootstrap change được phê duyệt. Lưu ARN của policy đó.
3. Điền `terraform.tfvars` từ file mẫu: policy ARN, target operator chính xác và security owner MFA. Không thêm audit-admin, break-glass, IAM change role, root hay wildcard vào target/trust.
4. `terraform fmt -check -recursive`; `terraform init -backend-config=backend.hcl`; `terraform validate`; `terraform plan -var-file=terraform.tfvars`; peer review; apply trong change window.
5. Module xuất `security_owner_assume_iam_change_policy_arn`. Attach policy tối thiểu này **thủ công trong IAM change review riêng** vào đúng `trusted_change_owner_arns`; trust policy một mình không cho phép assume role.
6. Security owner MFA assume role, chạy `iam:SimulatePrincipalPolicy`, attach boundary từng target, smoke-test workload và lưu CloudTrail/global-IAM-alert evidence.

## Guardrail và residual risk

Role executor vẫn là privileged change path, nhưng mọi IAM thao tác của nó phải vào global IAM alert. Single-account root và admin không boundary còn lại là residual risk cho đến khi inventory/boundary migration hoàn tất; không gọi đó là "không có cửa sổ mù" trước thời điểm đó.

---

**Phiên bản:** v1.0  
**Cập nhật:** 18/07/2026  
**Trạng thái:** STAGING — chỉ deploy sau foundation, audit-access và rendered boundary policy được phê duyệt
