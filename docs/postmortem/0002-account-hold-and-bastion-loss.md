# Postmortem 0002 — AWS account bị hold + mất bastion (mất đường vào cluster, storefront down)

**Ngày:** 12/07/2026
**Người ghi nhận & xử lý:** CDO02
**Mức độ ảnh hưởng:** Cao — storefront offline với khách (CloudFront bị gỡ khỏi edge), team mất
hoàn toàn quyền quản lý cluster (bastion bị hủy). Cluster + node vẫn chạy nội bộ.
**Trạng thái:** 🔴 Đang mở — chờ AWS mở khóa account; đã chuẩn bị sẵn các bước khôi phục.

---

## Tóm tắt

AWS đặt account vào trạng thái **hold pending verification** (lý do payment/account-verification,
phía AWS). Trong lúc đó, việc merge PR #40 (adopt addon) kích hoạt `terraform apply`, và apply
này **thực thi một lệnh replace bastion tiềm ẩn** (do AMI drift) — hủy bastion thành công nhưng
không tạo lại được vì account đang bị chặn `RunInstances`. Kết quả: mất bastion (đường vào cluster
duy nhất), và AWS song song gỡ CloudFront khỏi edge → storefront offline với khách.

**Quan trọng:** đây là **2 sự cố độc lập cộng dồn**, không phải do nội dung PR #40 (addon adopt
đã thành công — 3 addon ACTIVE).

## Dòng thời gian (ICT)

- **~14:27** — Merge PR #39 (REL-01 replicas + PDB), verify live OK (10 service 2/2, 10 PDB, ArgoCD Healthy).
- **~14:32** — Merge PR #40 (adopt coredns/kube-proxy/vpc-cni) → `terraform-apply` chạy.
- Trong apply: 3 addon `Creation complete`; **`aws_instance.bastion: Destruction complete` → `Creating...` → Error `RunInstances Blocked: account currently blocked`.**
- CloudFront update trong cùng apply → `AccessDenied`. Apply exit 1 (failed).
- Sau đó: `kubectl` fail (TLS handshake timeout — bastion đã mất). `aws eks describe-cluster` = ACTIVE, node = running. CloudFront domain **không resolve ra IP** trên cả 8.8.8.8/1.1.1.1 → storefront down toàn cầu.
- Nhận email AWS yêu cầu xác minh payment/ID (deadline 15/07). Account holder xác nhận account hold là thật, đã tạo case support chính thức qua Console.

## Nguyên nhân gốc

**Sự cố 1 — Account hold (phía AWS):** AWS không xác thực được thông tin payment của account →
đặt hold → chặn tạo tài nguyên mới (`RunInstances` Blocked, CloudFront update AccessDenied) và
gỡ dịch vụ public khỏi edge. Ngoài tầm kiểm soát của code hạ tầng.

**Sự cố 2 — Bastion tự replace do AMI drift:** `infra/bastion.tf` dùng
`data "aws_ami" "al2023" { most_recent = true }` và gán `ami = data.aws_ami.al2023.id`. Khi AWS
phát hành AL2023 AMI mới (giữa 08/07 tạo bastion và 12/07), data source trỏ sang AMI id mới →
đổi `ami` **buộc replace instance**. Lệnh replace này nằm sẵn trong **mọi** plan sau đó, không
liên quan gì tới PR #40 — PR #40 chỉ tình cờ là apply kích hoạt nó.

**Cộng dồn:** replace bastion (hủy trước, tạo sau) + account block (không tạo được) = **bastion
mất hẳn, apply fail giữa chừng.**

## Vì sao ảnh hưởng nặng

- Bastion là **đường vào duy nhất** tới EKS API (private-only từ 09/07). Mất bastion = mất
  `kubectl`/`helm` → không quản lý được cluster, kể cả để xử lý sự cố khác.
- Datastore in-cluster **0 PVC (REL-10 chưa vá)** → nếu AWS terminate node, dữ liệu
  Postgres/Kafka/Valkey mất vĩnh viễn, và **hiện không backup được** vì không có đường vào.

## Đã / đang xử lý

- Xác minh cluster + node vẫn ACTIVE/running qua AWS API (không cần bastion).
- Tạo **case support AWS chính thức** (qua Console, không qua link email) để mở khóa account.
- Chuẩn bị **PR #41** vá footgun AMI (`lifecycle { ignore_changes = [ami] }`) — sẵn sàng apply khi account mở.
- Soạn recovery runbook (`docs/runbooks/eks-recovery-after-account-unblock.md`).

## Bài học (action items)

1. **Đọc kỹ `terraform plan` trước khi approve production apply.** Plan đã hiện
   `aws_instance.bastion must be replaced` — nếu để ý sẽ dừng lại. → Thêm vào quy trình:
   reviewer phải xác nhận không có resource nhạy cảm (bastion/datastore) bị replace/destroy.
2. **Tránh `most_recent = true` cho tài nguyên stateful/hạ tầng quan trọng** — footgun replace
   âm thầm. Đã vá bastion (PR #41); rà các data source `most_recent` khác.
3. **Bastion là SPOF cho quản trị** — cân nhắc phương án vào cluster dự phòng (VD tạm bật public
   endpoint có allowlist khi khẩn cấp) để không "mất chìa khóa" khi bastion chết.
4. **REL-10 (datastore không PVC) giờ là rủi ro sống** — sự cố này cho thấy nếu node bị terminate,
   dữ liệu mất và không cứu được. Nâng ưu tiên PVC/backup Postgres + migrate managed (ADR 0002).
5. **Cost/billing monitoring** — account hold vì payment; dựng AWS Budget/billing alert (đã nợ từ
   BUDGET.md) để không bị bất ngờ về trạng thái billing.

---
*Cập nhật trạng thái khi account được mở khóa và bastion/cluster khôi phục.*
