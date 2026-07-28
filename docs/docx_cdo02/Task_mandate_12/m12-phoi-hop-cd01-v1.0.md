# Mandate 12 — Phối hợp CD01

## 1. Mục tiêu

Audit foundation được triển khai độc lập, không sửa EKS, Kyverno, ArgoCD hoặc workload Mandate 5. CD01 chỉ cần phối hợp trước giai đoạn IAM hardening để permissions boundary không làm hỏng pipeline hiện tại.

## 2. Input CD01 cần cung cấp

| Input | Nội dung |
|---|---|
| Identity | Exact ARN của GitHub OIDC, CI/CD, ArgoCD, Terraform và daily-operator role/user |
| Trust path | Trust policy, OIDC provider và các role workflow cần `sts:AssumeRole*` |
| Quyền cần giữ | ECR push/sign, EKS access, Cosign và `iam:PassRole` nếu thực sự dùng |
| Baseline | Quy trình test: build → Trivy → ECR → Cosign → PR digest → ArgoCD/EKS |
| Quản trị change | Owner, change window, thứ tự role và rollback cho từng identity |

CD01 không bàn giao access key, secret hoặc session credential.

## 3. Output Mandate 12 bàn giao

- ARN của CloudTrail, audit bucket, hai SNS topics/subscriptions và 12 EventBridge rules.
- Boundary strict hoặc allowlisted đã được review.
- Exact allowlist non-audit roles, không dùng wildcard.
- Mapping `identity → boundary → owner → rollback`.
- Kết quả policy simulation và baseline sau mỗi attachment.

## 4. Trình tự phối hợp

1. TF3 deploy và verify audit foundation bằng change/state riêng.
2. CD01 bàn giao đầy đủ input ở mục 2.
3. Hai bên chọn strict boundary hoặc allowlisted boundary.
4. Không attach boundary khi Mandate 5 đang cutover/demo hoặc pipeline chưa ổn định.
5. Attach từng identity một, chạy lại toàn bộ baseline rồi mới sang identity tiếp theo.
6. Nếu baseline fail: dừng batch và rollback đúng identity; không tắt audit foundation.
7. Chỉ sign-off IAM hardening khi không còn daily-admin/CI path chưa phân loại.

## 5. Điều kiện NO-GO

- ARN/trust/owner còn `TBD` hoặc `Unknown`.
- CI cần assume role nhưng strict boundary chưa có allowlist được duyệt.
- Chưa có baseline, rollback hoặc người CD01 phối hợp kiểm thử.
- Security owner/audit roles bị đưa nhầm vào operator-boundary targets.
- IAM hardening trùng change window với thay đổi Kyverno/EKS production.

---

**Phiên bản:** v1.0
**Cập nhật:** 18/07/2026
**Trạng thái:** READY FOR HANDOFF — audit foundation độc lập; IAM hardening chờ input CD01
