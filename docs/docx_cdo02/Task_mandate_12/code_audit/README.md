# code_audit — Mandate 12

Đây là staging để chuẩn bị Mandate 12 cho **một AWS account Free Tier TF3**. Không file nào trong thư mục này tự động tác động production.

| File/thư mục | Tác dụng |
|---|---|
| `foundation/` | Terraform root độc lập tạo CloudTrail, audit S3 WORM, data-event coverage, primary/global EventBridge và hai SNS alert planes. |
| `foundation/main.tf` | Audit controls, bucket policy giới hạn đúng trail, EventBridge/SNS và `prevent_destroy`. |
| `foundation/variables.tf` | Chặn sai region/account và bắt buộc S3 prefix + alert recipient trước deploy. |
| `foundation/terraform.tfvars.example` | Mẫu input phải được owner phê duyệt. |
| `foundation/backend.hcl.example` | State key riêng, không dùng state của production root. |
| `foundation/.gitignore` | Chặn commit backend local, tfvars, plan và cache provider. |
| `foundation/.terraform.lock.hcl` | Provider AWS `5.100.0` đã được Terraform validate; copy và commit cùng PR. |
| `iam_hardening/audit_access/` | Standalone Terraform root tạo audit-admin read-only và break-glass recovery hẹp; copy vào `infra/live/iam/mandate-12/audit_access/` sau foundation, state/PR riêng. |
| `iam_hardening/iam_change/` | Standalone controlled-executor Terraform root; copy vào `infra/live/iam/mandate-12/iam_change/`, dùng state key `mandate-12/iam-change/terraform.tfstate` để giới hạn ai được attach/rollback boundary. |
| `iam_hardening/operator-boundary-policy.template.json` | Strict boundary mặc định; deny mọi `sts:AssumeRole`, chỉ attach khi target không cần assume role. |
| `iam_hardening/operator-boundary-policy.allowlisted-assume-role.template.json` | Variant chỉ dùng khi exact non-audit assume-role targets đã được IAM/CI owner review/test. |
| `tools/Export-M12CloudTrailEvidence.ps1` | Local-only: decompress/parse một log CloudTrail `.json.gz` đã tải bằng read-only role, xuất metadata redacted. |
| [`HD_deploy-v1.8.md`](HD_deploy-v1.8.md) | Quy trình gate 0–11, cách lấy phụ thuộc, deploy ba state độc lập, verify integrity/evidence và rollback an toàn. |

Mục tiêu copy là `Phase3-TF3-Infra-Sentinel/infra/live/audit/`. Không đặt file vào `infra/live/production/` vì root đó quản lý EKS, network và edge đang chạy.

**Trạng thái:** staging đã chuẩn bị, **blocked deployment** cho đến khi coverage matrix, cả hai SNS recipient, backend, change window, IAM scope/attachment mapping và root residual-risk acceptance được phê duyệt.

**Giới hạn bắt buộc:** Foundation tạo log, retention và alert nhưng chưa làm Mandate 12 pass trước current admin/root. IAM hardening là change riêng. Audit-admin chỉ đọc evidence; break-glass chỉ recovery `StartLogging`/`EnableRule`, còn delete/recreate control phải qua incident/root-custodian và Terraform recovery change riêng. Single-account không chứng minh root hoặc toàn bộ same-account alert plane bị chặn tuyệt đối.

---

**Phiên bản:** v1.6
**Cập nhật:** 18/07/2026
**Trạng thái:** READY FOR REVIEW — chưa được phép deploy
