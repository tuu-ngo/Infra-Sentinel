# T2 - Giảm Service Surface Nội Bộ (Network Policy)

## 1. Đã làm những gì?
- Tạo 4 file `NetworkPolicy` nằm trong `gitops/infrastructure/`:
  - `network-policy-jaeger.yaml`
  - `network-policy-opensearch.yaml`
  - `network-policy-prometheus.yaml`
  - `network-policy-loadgen.yaml`
- **Cơ chế hoạt động:** 
  - Khóa (Deny) mặc định các truy cập không mong muốn vào hệ thống giám sát (Observability).
  - Chỉ tạo danh sách cho phép (Allowlist) cho các pod thực sự cần thiết (ví dụ: Grafana lấy dữ liệu từ Prometheus, Fluent-bit đẩy log vào OpenSearch).
  - Khóa hoàn toàn chiều Ingress đối với công cụ tạo tải `load-generator`.

## 2. Vì sao lại làm như vậy?
- **Ngăn chặn di chuyển ngang (Lateral Movement):** Trong Kubernetes, mặc định mọi pod đều có thể "nói chuyện" với nhau. Nếu 1 pod vòng ngoài (như Frontend) bị hacker chiếm quyền, họ có thể dễ dàng chui sâu vào đọc cắp hoặc phá hoại cơ sở dữ liệu và hệ thống giám sát nội bộ.
- **Tuân thủ Least Privilege:** Bằng cách áp dụng NetworkPolicy, chúng ta thu hẹp "bề mặt tấn công", đảm bảo chỉ những thành phần hợp lệ mới có quyền giao tiếp với các port nội bộ nhạy cảm. Điều này làm tăng độ bảo mật và giảm thiểu rủi ro (Blast Radius) cho hệ thống nếu có sự cố xảy ra.
