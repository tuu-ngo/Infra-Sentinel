# ADR 0014 — PM-176: derived OpenSearch plugin trust model

**Ngày:** 27/07/2026

**Người quyết định (ký):** VietSory — PM-176 implementation owner
**Trạng thái:** ✅ Chấp nhận và đã triển khai production qua PR #476/#478

## Bối cảnh

PM-176 yêu cầu Grafana có OpenSearch datasource plugin trong image immutable,
không tải plugin khi Pod khởi động. PR #475 đã giữ archive chính thức nhưng
Trivy chặn trước khi push: bốn HIGH có bản fixed version đều nằm trong backend
plugin (`grpc v1.79.3` và Go stdlib `1.26.3`). Tại thời điểm quyết định,
archive chính thức mới nhất là `2.34.0`; các bản cũ hơn có nhiều finding hơn.

Không được làm xanh pipeline bằng cách ignore CVE. Đồng thời không được sửa
binary mà vẫn giữ `MANIFEST.txt`, vì Grafana sẽ phát hiện signature bị thay đổi.

## Quyết định

Xây một artifact **TF3-derived** có phạm vi hẹp:

1. Checkout đúng upstream plugin commit
   `188f6f20d488f771808eff476e8647dccb901dad`.
2. Áp dụng patch `go.mod`/`go.sum` đã review, có SHA-256 cố định, nâng
   `google.golang.org/grpc` lên `v1.82.1`; build bằng Go `1.26.5` pinned digest,
   `CGO_ENABLED=0`, và target architecture tường minh.
3. Lấy frontend/metadata từ archive Grafana Catalog `2.34.0` với checksum riêng
   cho `linux/amd64` và `linux/arm64`; kiểm tra plugin ID, version, compatibility,
   manifest và executable trước khi dùng.
4. Cài archive qua Grafana CLI trong build để giữ contract của PM-176, đối chiếu
   toàn bộ tree bằng `diff -qr`, rồi overlay backend đã rebuild.
5. Xóa `MANIFEST.txt` sau overlay (không để signature cũ gây hiểu nhầm), ghi
   `TF3-PROVENANCE`, allowlist duy nhất `grafana-opensearch-datasource`, và đặt
   plugin directory root-owned/read-only.
6. Grafana chart phải đặt `preinstall_disabled=true`,
   `preinstall_auto_update=false`, `plugin_admin_enabled=false` và
   `plugin_admin_external_manage_enabled=false`. Đây là điều bắt buộc: biến
   `GF_PLUGINS_PREINSTALL` rỗng **không** vô hiệu catalog mặc định của Grafana 13.
7. PR gate build và scan độc lập cả `linux/amd64` lẫn `linux/arm64`, chạy
   Trivy blocking với `HIGH,CRITICAL`, và smoke runtime trên amd64. Gate không
   có AWS credentials, ECR push, hay quyền ghi repository.

`TF3-derived-unsigned` là trust model trung thực: artifact không còn được
Grafana publisher signature bảo vệ sau khi backend thay đổi. Integrity được
bù bằng source/dependency/archive checksums, read-only filesystem, immutable
image digest, SBOM/Cosign và gate Trivy. Đây không phải là tắt signature
verification toàn cục.

## Các phương án bị loại

- **Chờ upstream release sạch:** an toàn hơn nhưng không đáp ứng PM-176 trong
  thời hạn hiện tại; phải chuyển lại khi upstream có bản signed không còn finding.
- **Hạ version plugin:** các archive đã kiểm tra có nhiều HIGH/CRITICAL hơn.
- **Trivy ignore:** che giấu code dễ bị khai thác và vi phạm PM-101.
- **Tự ký lại bằng khóa khác:** Grafana không coi đó là chữ ký publisher; không
  tạo thêm giá trị so với trust model derived đã công bố.

## Rollback và điều kiện xem lại

Trước khi merge, không có image tag/digest production nào thay đổi. Nếu gate
hoặc runtime thất bại, dừng rollout và tạo revert PR cho commit PM-176; ArgoCD
trên `main` sẽ tự đồng bộ về image trước đó. Không mở public egress để chữa
cháy. Revisit quyết định khi upstream có signed release sạch, hoặc khi Grafana
thay đổi cơ chế preinstall/signature.

## Kết quả triển khai

Image derived đã được build/push qua workflow `30240572310`, pin vào
production bằng PR #478 và xác minh runtime ngày 27/07/2026:

- ArgoCD `techx-corp` `Synced/Healthy`;
- Pod Grafana 4/4 Ready, zero restart;
- startup log đăng ký `grafana-opensearch-datasource`;
- không có runtime install/download hoặc modified-signature failure;
- datasource `webstore-logs` trả `HTTP 200`, `Index OK. Time field name OK.`;
- image production:
  `b44ca10-30240572310-grafana@sha256:198bff3b9b5f15962cf0942f38a0a90226f60277e7ef5212294987d160f55958`.

Full PR #426 egress/destructive recreation gate vẫn là follow-up bắt buộc và
không được suy diễn từ kết quả core rollout này.

*Signed: VietSory, PM-176 implementation owner, 2026-07-27.*
