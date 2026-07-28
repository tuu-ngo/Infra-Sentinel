# Mandate 12 — IAM scope và residual-risk acceptance

> **Trạng thái:** DRAFT / `NO-GO` cho kết luận Mandate 12 `VERIFIED` cho đến khi inventory, migration và acceptance này hoàn tất.

## 1. Phạm vi bắt buộc

“Daily admin” là mọi human, CI/CD, service role hoặc assume-role path có thể trực tiếp hoặc gián tiếp thay đổi audit controls, hay tự nâng quyền để làm điều đó. Inventory phải bao gồm user, group, role, inline/managed policy, permissions boundary, trust policy, OIDC/CI path và quyền `iam:*`/`sts:AssumeRole` liên quan.

Không được kết luận “operator bị chặn” khi còn một daily-admin identity chưa được phân loại. Root, audit-admin và break-glass là ngoại lệ phải được ghi rõ, không được biến thành lỗ hổng không owner.

## 2. Cách lập inventory chỉ đọc

Chạy trong account `197826770971`, lưu output redacted vào IAM PR/change record. Các lệnh này chỉ đọc metadata, không thay đổi production.

```powershell
aws iam get-account-authorization-details `
  --filter User Role Group LocalManagedPolicy AWSManagedPolicy `
  --output json > iam-authorization-details.json

aws iam generate-credential-report
aws iam get-credential-report --output text > iam-credential-report.csv

aws iam list-open-id-connect-providers --output json > iam-oidc-providers.json
aws iam list-saml-providers --output json > iam-saml-providers.json

# Với từng identity có quyền hiệu lực cao, lấy thêm path và trust policy.
aws iam list-groups-for-user --user-name <user>
aws iam list-user-policies --user-name <user>
aws iam list-attached-user-policies --user-name <user>
aws iam list-role-policies --role-name <role>
aws iam list-attached-role-policies --role-name <role>
aws iam get-role --role-name <role>
```

Security/IAM owner phải review policy documents và assume-role chain; danh sách tên policy gắn trực tiếp không đủ để chứng minh effective permission. Không ghi access key, secret, session token hoặc output nhạy cảm vào tài liệu/PR.

## 3. Inventory và trạng thái migration

Mỗi principal effective-admin phải có một hàng riêng. Các hàng `TBD` dưới đây là discovery item, không phải exception được chấp nhận.

| ID | Principal / type | Nguồn quyền hiện tại | Workflow/owner | Target Mandate 12 | Test + rollback | Trạng thái |
|---|---|---|---|---|---|---|
| IAM-01 | `arn:aws:iam::197826770971:user/cdo-2-admin-team` / human user | Live discovery: group `AIO2-Admin` gắn `AdministratorAccess` | Owner `TBD`; daily ops | Migrate khỏi admin trực tiếp; attach boundary sau baseline review hoặc thay bằng bounded role | Policy simulation, approved workflow test, detach/revert theo IAM PR | `PENDING OWNER` |
| IAM-02 | Terraform/GitHub apply role / CI | Static repo xác nhận có `AdministratorAccess`; exact ARN/trust path `TBD` | IaC/CI owner | Bounded CI role; audit root deploy identity tách khỏi production workflow | OIDC/trust review, plan/apply baseline, one-at-a-time rollback | `PENDING INVENTORY` |
| IAM-03 | `arn:aws:iam::197826770971:root` / account root | Trust anchor cuối cùng của single account | Account security owner | Không dùng vận hành; MFA, không access key, break-glass only; **không thể gắn permissions boundary** | Tabletop break-glass, credential report, incident procedure | `PENDING ACCEPTANCE` |
| IAM-04 | Audit-admin read-only role + break-glass recovery role / human-assumed roles | Chưa tạo/chưa chỉ định exact ARN | Security/IaC owner | Audit-admin chỉ đọc evidence; break-glass chỉ `StartLogging`/`EnableRule`, không phải daily admin | Assume-role attribution, MFA, change approval; delete/recreate control dùng root-custodian/Terraform recovery riêng | `PENDING DESIGN` |
| IAM-05+ | Mọi user/role/group/OIDC/service role còn lại có effective admin hoặc escalation path | Điền từ inventory ở mục 2 | Từng owner | `BOUND`, `RETIRED`, hoặc documented exception | Simulation + baseline + rollback per identity | `PENDING INVENTORY` |

### Điều kiện complete inventory

- Không còn `TBD`/`Unknown` đối với identity có quyền audit mutation hoặc privilege escalation.
- Mỗi exception có owner, business reason, expiry/review date, monitoring và acceptance riêng.
- Daily operator/CI target list khớp với attachment mapping trong IAM PR.
- Audit-admin/break-glass không được dùng làm workaround thường ngày; mọi session phải truy về cá nhân và change record.

## 4. PR IAM tái lập được

IAM hardening là PR/branch riêng, không gộp với foundation. Tên gợi ý:

```text
branch: chore/mandate-12-iam-boundary
product repository targets (sau IaC-owner approval):
infra/live/iam/mandate-12/
├── audit_access/                      # standalone Terraform root audit-admin/break-glass
└── iam_change/                        # standalone executor root, state key mandate-12/iam-change/terraform.tfstate
    ├── rendered boundary policy ARN   # input, không còn placeholder
    ├── explicit target user/role ARNs # input; không wildcard target
    └── MFA-trusted security owner ARNs # input cho executor
```

Source staging là `code_audit/iam_hardening/audit_access/` và `code_audit/iam_hardening/iam_change/`. Nếu repository cần wrapper/provider/backend khác cho `audit_access`, IaC owner phải ghi exact path/state key trong PR trước apply. `iam_change` là executor kiểm soát thay đổi/rollback, không phải daily-admin role. PR phải quản lý **cả** rendered policy ARN lẫn attachment mapping; không chấp nhận policy template đơn lẻ hoặc attachment thủ công không có record tái lập được.

### Gate PR IAM

1. Inventory mục 3 hoàn chỉnh và được security/IaC/CI owners ký.
2. Rendered policy thay hết placeholder, JSON validate và IAM policy validation pass; warning có acceptance rõ ràng.
3. Simulation với từng target identity: audit/alert/IAM-escalation actions là `explicitDeny`; workflow baseline được phép là `allowed`.
4. Review trust policy/OIDC/`sts:AssumeRole`, inline policy, managed policy version và quyền sửa/gỡ boundary.
5. Attach từng identity một, chạy CI/ops baseline và lưu verdict trước khi chuyển identity kế tiếp.
6. Run mandatory denied tests cho CloudTrail, audit S3, EventBridge/SNS, IAM boundary/trust policy; capture actor, region, EventBridge invocation và SNS receipt.
7. Rollback cụ thể cho từng identity có owner; rollback không được tắt trail/xóa archive.

### Chuỗi thực thi IAM

`foundation healthy → audit_access apply → cả hai SNS subscription Confirmed → render/validate/create managed boundary policy → iam_change plan/apply (removal=false) → gắn security-owner assume policy cho named MFA owner → assume executor → attach boundary theo batch → baseline/simulation → denied tests`.

Nếu CI cần `sts:AssumeRole`, strict template mặc định là `NO-GO`; chỉ dùng allowlisted template sau khi exact non-audit target roles, trust/OIDC path và baseline CI đã pass. Không attach root hoặc principal còn unbounded `AdministratorAccess` ngoài migration scope.

## 5. Root và continuity limitation

Trong một account Free Tier, root không thể bị permissions boundary hoặc account-local EventBridge/SNS giới hạn như daily operator. Vì vậy Mandate 12 chỉ có thể đưa ra claim chính xác sau:

> Với các daily operator/CI identities đã có trong inventory và đã được harden, attempt thay đổi audit controls bị deny và có evidence alert theo test window. Claim không chứng minh root, audit-admin/break-glass được loại trừ tuyệt đối và không chứng minh alert delivery liên tục nếu toàn bộ cùng-account alert plane bị root/break-glass thay đổi.

Root residual risk phải được security owner và account owner chấp nhận bằng record dưới đây trước verdict `VERIFIED`:

| Trường | Giá trị phải điền |
|---|---|
| Account / UTC date | `197826770971` / `TBD` |
| Root controls | MFA enabled, no access key, custody/contact path, credential-report evidence |
| Break-glass trigger | Critical incident/change record được phép |
| Custodian / approver | `TBD` |
| Detection / attribution | CloudTrail actor/session + evidence retention 365 ngày |
| Review expiry | `TBD` (tối đa theo policy nội bộ) |
| Residual-risk acceptance | Security owner + account owner signature/link `TBD` |

Không có record này thì trạng thái là `PARTIAL`, không phải `VERIFIED`.

---

**Phiên bản:** v1.0  
**Cập nhật:** 18/07/2026  
**Trạng thái:** DRAFT — mandatory IAM scope and acceptance artifact
