# Mandate 12 — Audit không thể bị đánh bại

Thư mục chỉ chứa tài liệu chuẩn bị cho Mandate 12 của TF3. Dự án dùng một AWS account Free Tier; “sub account” là IAM user/role trong cùng account, không phải AWS Organizations. Repository production chỉ được đọc; chưa có thay đổi hay triển khai nào vào production.

## Bộ tài liệu hiện hành

1. [m12-gap-v1.4.md](m12-gap-v1.4.md) — yêu cầu, hiện trạng và gap.
2. [m12-coverage-v1.0.md](m12-coverage-v1.0.md) — matrix bắt buộc cho toàn bộ dữ liệu nhạy cảm và config control.
3. [m12-iam-scope-v1.0.md](m12-iam-scope-v1.0.md) — inventory daily-admin/CI, migration và residual-risk acceptance.
4. [m12-solution-v1.7.md](m12-solution-v1.7.md) — solution, thiết kế và giới hạn claim single-account.
5. [m12-runbook-v1.5.md](m12-runbook-v1.5.md) — kế hoạch, gate và runbook.
6. [m12-tests-v1.6.md](m12-tests-v1.6.md) — kịch bản kiểm thử và evidence.

## Tài liệu nguồn

- [MANDATE-12-audit-anti-defeat-_BTC.md](MANDATE-12-audit-anti-defeat-_BTC.md) — đề chính thức; giữ nguyên nội dung.
- [MANDATE-4_BTC.md](MANDATE-4_BTC.md) — chỉ tham khảo, không phải hạng mục đã triển khai.

`code_audit/` có staging foundation, audit-access, controlled IAM executor (`iam_change`), local evidence extractor và hướng dẫn deploy. Deployment vẫn bị block cho đến khi coverage matrix, cả hai SNS recipient, backend, change window, IAM attachment mapping và root residual-risk acceptance được phê duyệt.

## Quy tắc version

- Minor (`v1.1` → `v1.2`): đổi tên file hiện hành và cập nhật nội dung; không giữ bản minor cũ.
- Major (`v1.x` → `v2.0`): tạo bộ file mới, giữ bộ major cũ để đối chiếu.
- Chỉ sửa bản mới nhất. Phiên bản và trạng thái luôn ghi ở cuối mỗi tài liệu làm việc.

---

**Phiên bản:** v1.7  
**Cập nhật:** 18/07/2026  
**Trạng thái:** READY FOR REVIEW — deployment blocked pending gates
