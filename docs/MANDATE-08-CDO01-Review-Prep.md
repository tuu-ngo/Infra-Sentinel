# Báo cáo Chuẩn bị Đánh giá: Mandate #8 (Managed Migration)
**Người thực hiện:** CDO01 (Security & Architecture Focus)
**Mục tiêu:** Nắm bắt kỹ thuật di trú, chuẩn bị checklist bảo mật và câu hỏi phản biện cho phương án thực thi của CDO02 đối với Mandate #8 (Migration Postgres, Valkey, Kafka lên Managed Services).

---

## 1. Phân tích Các Phương án Di trú (Migration Options)

Để có thể review và góp ý hiệu quả, dưới đây là phân tích về các phương pháp di trú cho từng loại data store, ưu/nhược điểm và lý do vì sao một công cụ được (hoặc không được) lựa chọn:

### A. Postgres → Amazon RDS
*   **Tùy chọn 1: `pg_dump` / `pg_restore` (Logical Backup)**
    *   **Cơ chế:** Xuất toàn bộ dữ liệu ra file backup và phục hồi lại trên RDS.
    *   **Ưu điểm:** Đơn giản, sử dụng công cụ native, dễ hiểu, phù hợp với lượng dữ liệu nhỏ.
    *   **Nhược điểm:** Downtime lớn (phải chặn write ở source, chờ dump và restore xong mới trỏ app sang RDS). Không phù hợp cho yêu cầu SLO ≥99% nếu dữ liệu lớn.
*   **Tùy chọn 2: AWS DMS (Database Migration Service) kết hợp CDC**
    *   **Cơ chế:** Copy dữ liệu ban đầu (Full Load) sau đó liên tục bắt các thay đổi (Change Data Capture - CDC) từ source sang RDS cho đến khi 2 bên đồng bộ hoàn toàn.
    *   **Ưu điểm:** Cho phép **Near-zero downtime**. Quá trình cutover chỉ mất vài giây/phút để đổi chuỗi kết nối của app.
    *   **Nhược điểm:** Setup phức tạp hơn, tốn chi phí chạy instance DMS, yêu cầu cấu hình WAL (Write-Ahead Logging) ở mức `logical` trên source Postgres.
*   **Tùy chọn 3: Native Logical Replication**
    *   **Cơ chế:** Dùng tính năng native của Postgres (Publication/Subscription) để stream dữ liệu sang RDS.
    *   **Ưu điểm:** Near-zero downtime, không tốn thêm tool trung gian như DMS.
    *   **Nhược điểm:** Cấu hình thủ công phức tạp, có thể gặp rủi ro nếu phiên bản Postgres giữa source và target lệch nhau nhiều.
*   **Nhận định cho CDO02:** Để đảm bảo SLO checkout ≥99%, AWS DMS hoặc Logical Replication là bắt buộc. `pg_dump` chỉ nên dùng nếu lượng data cực kỳ nhỏ và có thể chịu downtime trong maintenance window ban đêm.

### B. Valkey/Redis → Amazon ElastiCache
*   **Tùy chọn 1: Cold Start (Bỏ dữ liệu cũ, bắt đầu từ Cache rỗng)**
    *   **Cơ chế:** Đổi endpoint thẳng sang ElastiCache, app sẽ tự query database và fill lại cache từ đầu (cache miss).
    *   **Ưu điểm:** Cực kỳ đơn giản, không tốn effort migrate.
    *   **Nhược điểm:** Rủi ro "Cache Stampede" - khi vừa cutover, hàng loạt request ập vào DB do cache rỗng, có thể làm sập DB.
*   **Tùy chọn 2: Online Migration / Warm-up (Dùng RIOT hoặc tính năng migrate của AWS)**
    *   **Cơ chế:** ElastiCache có hỗ trợ sync data từ external Redis/Valkey trước khi promote thành primary.
    *   **Ưu điểm:** Giữ nguyên hiệu năng, không bị giật lag (latency spike) lúc cutover.
    *   **Nhược điểm:** Phải mở kết nối mạng giữa cụm cũ và ElastiCache, thao tác phức tạp hơn mức cần thiết.
*   **Nhận định cho CDO02:** Vì đây chỉ là Cache (không phải Single Source of Truth), việc mất data là chấp nhận được. Tuy nhiên, để tránh làm quá tải DB lúc cutover, cần hỏi CDO02 xem họ có chiến lược "warm-up" cache hay giới hạn rate limit trong vài phút đầu sau khi cutover không.

### C. Kafka → Amazon MSK (Managed Streaming for Apache Kafka)
*   **Tùy chọn 1: MirrorMaker 2 / Kafka Connect**
    *   **Cơ chế:** Chạy cụm MirrorMaker để replicate topic, partition, và offset từ Kafka cũ sang MSK liên tục.
    *   **Ưu điểm:** Không mất message, hỗ trợ quá trình chuyển đổi mượt mà (có thể cho producer viết vào MSK, consumer đọc nốt ở cụm cũ rồi chuyển sang MSK).
    *   **Nhược điểm:** Setup MirrorMaker rất phức tạp, tốn kém tài nguyên compute.
*   **Tùy chọn 2: Cold Cutover (Chuyển đổi ngắt quãng)**
    *   **Cơ chế:** Dừng toàn bộ Producer, chờ Consumer xử lý hết message tồn đọng ở cụm cũ, trỏ cả hai sang MSK, rồi bật lại.
    *   **Ưu điểm:** Đơn giản, kiến trúc gọn gàng.
    *   **Nhược điểm:** Có downtime cho luồng xử lý bất đồng bộ.
*   **Nhận định cho CDO02:** Dịch vụ Checkout hiện tại có cơ chế `WaitForAll` khi tương tác Kafka. Nếu dùng Cold Cutover, cần đảm bảo timeout của `WaitForAll` đủ dài hoặc app có cơ chế retry tốt để không rớt đơn hàng của user trong cửa sổ cutover.

---

## 2. Checklist Bảo Mật Dành Cho CDO01 (Khi Review Phương Án)

Để đảm bảo kiến trúc mới tuân thủ nghiêm ngặt các tiêu chuẩn bảo mật (Security Pillar), CDO01 sẽ rà soát các hạng mục sau dựa trên phương án của CDO02:

> [!IMPORTANT]
> **Quy tắc cốt lõi:** Chuyển sang Managed Services không đồng nghĩa với việc AWS tự động cấu hình bảo mật ở mức cao nhất. Chúng ta phải chủ động thiết lập.

- [ ] **1. Encryption in Transit (TLS Bắt buộc):**
  - **RDS:** Bắt buộc thiết lập `rds.force_ssl=1`. Application (Checkout, v.v.) phải cập nhật chuỗi kết nối thêm `sslmode=require` và được cung cấp AWS RDS CA Bundle.
  - **ElastiCache:** Bật tính năng `In-Transit Encryption`. Đảm bảo Helm charts của các app dùng Redis/Valkey có cấu hình cờ TLS (`rediss://` thay vì `redis://`).
  - **MSK:** Cấu hình MSK cluster chỉ chấp nhận kết nối `TLS`. Tắt giao thức PLAINTEXT.
- [ ] **2. Encryption at Rest (KMS):**
  - Đảm bảo RDS Storage, ElastiCache nodes, và MSK EBS Volumes đều được bật Encryption at rest.
  - Kiểm tra xem CDO02 dùng *AWS Managed Key* hay *Customer Managed Key (CMK)*. Khuyến nghị dùng CMK để có quyền tự rotate key.
- [ ] **3. Secrets Management (Không Hardcode):**
  - **Tuyệt đối không** lưu RDS Password, Redis Auth Token, hay Kafka SASL Credentials dưới dạng plaintext trong `values-prod.yaml`, GitHub repo, hay biến môi trường (Environment Variables) trực tiếp.
  - Các thông tin này phải được tạo tự động/lưu trữ trong **AWS Secrets Manager**. Ứng dụng/EKS phải dùng External Secrets Operator hoặc CSI Secret Store để mount secret vào pod.
- [ ] **4. Network Exposure (Private Endpoints):**
  - **Subnet:** RDS, ElastiCache, MSK phải nằm hoàn toàn ở **Private Subnets** (không có Internet Gateway).
  - **Security Groups (SG):** SG của các dịch vụ này chỉ được phép mở cổng (5432, 6379, 9094/9096) từ nguồn (Source) là SG của EKS Worker Nodes (tức là chỉ App mới gọi được DB), áp dụng nguyên tắc Least Privilege.
  - Không được thiết lập `Publicly Accessible = true` trong bất kỳ tình huống nào.

---

## 3. Danh Sách Câu Hỏi Chuẩn Bị (Q&A cho CDO02)

Dưới đây là 5 câu hỏi có cơ sở kỹ thuật để chất vấn/góp ý khi CDO02 trình bày phương án, nhằm đảm bảo cả hai trụ Reliability và Security:

1. **Về Downtime & SLO:** *"Thời gian downtime thực tế dự kiến cho đợt cutover (đặc biệt là Postgres) là bao lâu? Team định dùng metrics hay công cụ gì để đo lường và xác nhận việc cutover thành công mà không vi phạm cam kết SLO ≥99% của dịch vụ Checkout?"*
2. **Về Data Integrity:** *"Đối với dữ liệu tài chính/đơn hàng trong Postgres, phương pháp xác minh tính toàn vẹn (Data Parity) sau khi migrate là gì? Chạy checksum, đếm row count trước-sau, hay có script so sánh mẫu để đảm bảo không sai lệch dòng data nào?"*
3. **Về Resilience vs Cost:** *"Với cấu hình Multi-AZ cho RDS và MSK, chi phí ước tính tăng lên bao nhiêu so với Single-AZ, có nằm trong ngân sách cho phép không? Và team đã đánh giá độ trễ (latency) khi sync data qua lại giữa các AZ có ảnh hưởng tới P99 latency của Checkout chưa?"*
4. **Về Cơ chế Rollback:** *"Nếu quá trình cutover gặp sự cố bất ngờ giữa chừng (ví dụ: app không tương thích với version Postgres mới trên RDS, hoặc MSK cấu hình sai TLS khiến producer không push được message), kế hoạch Rollback chi tiết là gì? Mất bao lâu để khôi phục về hệ thống cũ trên K8s?"*
5. **Về Hệ quả cho Kafka Clients:** *"Dịch vụ Checkout hiện tại có cơ chế `Kafka WaitForAll`. Trong quá trình chuyển đổi Kafka sang MSK (dù dùng MirrorMaker hay Cold Cutover), app Checkout sẽ phản ứng thế nào nếu có gián đoạn mạng hoặc rớt kết nối ngắn? Đã có cơ chế retry đủ tốt để tránh việc user bị trừ tiền nhưng đơn không đẩy được vào queue chưa?"*
