# Tổng Hợp Nghiên Cứu - Mandate 09 (Managed Zero-Downtime Ops)

*Báo cáo nghiên cứu cho các yêu cầu chuyển đổi hệ thống không gây gián đoạn (zero-downtime) trên hạ tầng AWS Managed Services, được ánh xạ trực tiếp với kiến trúc hiện hành của TechX Corp.*

---

## PHẦN 1: TỔNG HỢP NGHIÊN CỨU 5 YÊU CẦU

### 1. Online Schema Migration dưới tải
*   **Giải pháp/Công cụ:** Pattern **Expand-Contract** (Thực hiện thủ công qua Flyway/Liquibase) hoặc dùng công cụ **pg-osc** (PostgreSQL Online Schema Change - hoạt động dựa trên Logical Replication).
*   **Cách hoạt động & Áp dụng cho từng loại thay đổi cụ thể:**
    *   **Thêm cột `NOT NULL`:** Không thể chạy thẳng lệnh `ADD COLUMN...NOT NULL` vì Postgres sẽ khóa (lock) toàn bảng để quét dữ liệu. 
        *   *Cách xử lý (Expand-Contract):* 1. Thêm cột mới nhưng cho phép `NULL`. 2. Sửa App (Go/Python/.NET) ghi default value vào cột mới (Dual-write). 3. Backfill dữ liệu cũ dưới nền. 4. Chạy `ALTER TABLE...ADD CONSTRAINT NOT NULL NOT VALID`. 5. Chạy lệnh `VALIDATE CONSTRAINT` (không khóa bảng).
    *   **Đổi kiểu dữ liệu (Change Type):** Không thể `ALTER TYPE` trực tiếp vì khóa toàn bảng. 
        *   *Cách xử lý:* Tạo cột `_v2` với kiểu dữ liệu mới. App thực hiện Dual-write. Chạy job Backfill data. Cuối cùng App chuyển sang chỉ đọc/ghi cột mới và drop cột cũ.
    *   **Thêm Index:** Lệnh `CREATE INDEX` chuẩn sẽ khóa ghi (Write lock). 
        *   *Cách xử lý:* Bắt buộc dùng cú pháp `CREATE INDEX CONCURRENTLY` của Postgres. Nó không khóa Write, chỉ tốn tài nguyên và thời gian lâu hơn một chút.
*   **Vì sao phù hợp:** Chia nhỏ Exclusive Lock của Postgres thành các tác vụ siêu ngắn, giữ cho kết nối từ `product-catalog` hay `accounting` không bị time-out khi hệ thống đang chịu tải nặng.
*   **Ưu/Nhược điểm:**
    *   *Ưu:* An toàn tuyệt đối, zero-downtime, dễ rollback từng bước.
    *   *Nhược:* Mất nhiều công sức phối hợp đồng bộ giữa Code App và script DB.
*   **Nguồn tham khảo:** [Prisma - Expand and Contract Pattern](https://www.prisma.io/dataguide/types/relational/expand-and-contract-pattern).
*   **Hướng triển khai tổng quát:** Sử dụng Flyway để tạo kịch bản migration. Mã nguồn App phải được cập nhật và deploy ở giữa các phase (sau Expand, trước Contract).

### 2. Nâng Major Version Zero-Downtime
*   **Giải pháp/Công cụ:** **AWS RDS Blue/Green Deployments**.
*   **Cách hoạt động:** AWS tạo tự động bản clone "Green" từ "Blue". Hệ thống nâng cấp Green lên version mới (ví dụ PostgreSQL 16). AWS tự động bật Logical Replication đồng bộ từ Blue sang Green. Khi Switchover, AWS ngắt kết nối phía Blue, đợi Green đồng bộ nốt dữ liệu còn thiếu, rồi trỏ DNS về phía Green.
*   **Vì sao phù hợp:** Rút ngắn thời gian downtime khi nâng cấp PostgreSQL/Valkey từ mức 15-30 phút (cách nâng cấp In-place thông thường) xuống chỉ còn chớp mắt (dưới 1 phút - thời gian trễ do đổi DNS).
*   **Giới hạn của giải pháp (Limitations):**
    *   Không hỗ trợ hạ cấp (Downgrade) nếu xảy ra lỗi sau khi đã switch.
    *   Trong quá trình đồng bộ (chạy song song), tuyệt đối không được thực hiện thay đổi schema (DDL) trên môi trường Blue.
    *   Nếu Replication Lag (độ trễ đồng bộ) quá cao do tải ghi (Write load) đang lớn, quá trình switchover có thể bị timeout và báo lỗi.
*   **Ưu/Nhược điểm:**
    *   *Ưu:* Hoàn toàn tự động, rủi ro thấp vì môi trường cũ (Blue) vẫn còn nguyên si sau khi switch.
    *   *Nhược:* Tốn x2 chi phí DB trong thời gian bật Blue/Green.
*   **Nguồn tham khảo:** [AWS Docs - RDS Blue/Green Deployments](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/blue-green-deployments.html).
*   **Hướng triển khai tổng quát:** Bật tính năng Blue/Green trong Terraform (`aws_db_instance`). Dùng RDS Proxy để giữ (hold) connection trong ~1 phút switchover để App không ném lỗi.

### 3. Đổi tham số cần reboot
*   **Giải pháp/Công cụ:** Cải thiện qua cơ chế **Multi-AZ Failover** hoặc dùng **Blue/Green Deployments**.
*   **Cách hoạt động:** Apply tham số `pending-reboot` (ví dụ `shared_buffers`) vào Standby Instance. Sau đó gọi API `Reboot with Failover`. AWS sẽ tự động promote Standby lên làm Primary (với tham số mới đã được apply thành công).
*   **Vì sao phù hợp:** Rút ngắn thời gian gián đoạn từ việc reboot Primary (thường tốn vài phút) xuống chỉ còn thời gian Failover (~60s).
*   **Ưu/Nhược điểm:**
    *   *Ưu:* Nhanh gọn, tận dụng sẵn hạ tầng High Availability (HA) Multi-AZ của Mandate 8.
    *   *Nhược:* Có thể gây hiện tượng "Cold Cache" (Cache Lạnh) ở node mới lên, làm query chậm trong vài phút đầu tiên. Có thể dùng extension `pg_prewarm` để nạp dữ liệu vào RAM trước khi failover để khắc phục điểm yếu này.
*   **Nguồn tham khảo:** [AWS Docs - Modifying DB parameter groups](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_WorkingWithParamGroups.html).
*   **Hướng triển khai tổng quát:** Chỉnh sửa tham số tĩnh qua Terraform, apply thành công. Chủ động trigger failover trong giờ có tải thấp. Bắt buộc có RDS Proxy và Retry ở tầng App để giữ connection ổn định.

### 4. Xoay credential live
*   **Giải pháp/Công cụ:** **AWS Secrets Manager Rotation (Multi-user)** kết hợp **Amazon RDS Proxy**.
*   **Cách hoạt động & Vai trò của RDS Proxy:**
    *   Secrets Manager tự động tạo mật khẩu mới (dùng tính năng Multi-user rotation để tạo một user clone).
    *   **Vai trò cốt lõi của RDS Proxy:** App hoàn toàn không nối thẳng vào DB mà nối vào Proxy bằng một Credential tĩnh (hoặc qua IAM Auth). RDS Proxy tự đọc Secret mới từ Secrets Manager và dùng mật khẩu này để thiết lập connection mới xuống DB sau màn màn.
*   **Vì sao phù hợp:** App (Go/.NET/Python) không cần restart để nhận biến môi trường (mật khẩu) mới. Zero-downtime Auth hoàn hảo.
*   **Ưu/Nhược điểm:**
    *   *Ưu:* Bảo mật tuyệt đối, tự động xoay pass (rotate) theo lịch trình, không cần sự can thiệp của con người.
    *   *Nhược:* Tốn phí duy trì RDS Proxy (dù là rất nhỏ).
*   **Nguồn tham khảo:** [AWS Docs - Rotating secrets for Amazon RDS](https://docs.aws.amazon.com/secretsmanager/latest/userguide/rotating-secrets.html).
*   **Hướng triển khai tổng quát:** Triển khai RDS Proxy thông qua Terraform. Bật Lambda Rotation cho Secret. Cập nhật file `values-prod.yaml` để App chĩa endpoint về Proxy thay vì nối thẳng xuống DB.

### 5. App chịu được Connection Blip
*   **Giải pháp/Công cụ:** **RDS Proxy** (giữ kết nối ở infra) + **Connection Pool** + **Exponential Backoff Retry with Jitter** (ở tầng App).
*   **Cách hoạt động & Tương thích ngôn ngữ của hệ thống:**
    *   Dù RDS Proxy có "giam" (hold) request, mạng của AWS đôi lúc vẫn có thể timeout, App bắt buộc phải có cơ chế tự Retry lại.
    *   **Golang (`product-catalog`, `checkout`):** Sử dụng `database/sql` có sẵn connection pool. Cần bọc các lệnh truy vấn bằng thư viện **`avast/retry-go`**.
    *   **.NET/C# (`accounting`, `cart`):** Sử dụng connection pool mặc định của **`Npgsql`** (với Postgres) và **`StackExchange.Redis`** (với Valkey). Bọc logic gọi DB bằng thư viện **`Polly`** (cụ thể là `WaitAndRetryAsync`).
    *   **Python (`product-reviews`):** Sử dụng connection pool của **`psycopg2`** / `SQLAlchemy`. Bọc logic gọi DB bằng thư viện **`tenacity`**.
    *   *Lưu ý cốt tử:* Bắt buộc dùng thuật toán **Jitter** (ngẫu nhiên hóa thời gian chờ giữa các lần retry) để tránh hàng ngàn request cùng "đấm" vào DB lúc nó vừa hồi sinh (Thundering Herd).
*   **Vì sao phù hợp:** Hạ tầng không bao giờ hoàn hảo 100%, tự phục hồi ở App layer là chốt chặn cuối cùng đảm bảo Error Count = 0 trên Grafana.
*   **Ưu/Nhược điểm:**
    *   *Ưu:* Hệ thống cực kỳ bền bỉ (resilient) trước mọi chấn động của infra.
    *   *Nhược:* Yêu cầu các luồng nhạy cảm (như thanh toán, trừ hàng) phải có tính **Idempotency** (chống trừ tiền 2 lần khi bị gọi lại).
*   **Nguồn tham khảo:** [AWS Blog - Exponential Backoff and Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/).
*   **Hướng triển khai tổng quát:** Update source code của các microservice để thêm hàm Retry. Đồng thời, nâng timeout của Envoy (`frontend-proxy`) trong `values-prod.yaml` lên > 65s để kiên nhẫn chờ RDS Proxy trả lời.

---

## PHẦN 2: ĐỐI CHIẾU SƠ BỘ NGÂN SÁCH (< $300/tuần)
*   **Blue/Green Deployments:** Chỉ chạy song song hai cụm Managed (RDS/ElastiCache) lúc nâng cấp (< 2 giờ đồng hồ). Chi phí phát sinh ước tính: **< $5**.
*   **RDS Proxy:** Mức giá khởi điểm ~$0.015/vCPU/giờ. Tương đương **~$2.5/tuần**.
*   **Secrets Manager:** Phí lưu trữ là $0.40/secret/tháng + phí API vô cùng rẻ. **Không đáng kể**.
=> **Kết luận:** Tổng chi phí kiến trúc Zero-Downtime này ước tính **dưới $10/tuần**, hoàn toàn an toàn và nằm gọn trong ngưỡng ngân sách $300/tuần của chương trình.

---

## PHẦN 3: DANH SÁCH PHỤ THUỘC VÀO MANDATE #8 (Prerequisites)
Để có "đất diễn" thực thi Mandate #9, chúng ta bắt buộc cần có các Input/Output sau từ việc hoàn thành Mandate #8:
1.  **Hạ tầng Managed đã hoạt động:** Các đoạn code Terraform khai báo RDS PostgreSQL, ElastiCache Valkey, MSK Kafka đã được apply thành công ở thư mục `infra/live/production/` và DB đang chạy trơn tru.
2.  **Cấu hình nền tảng DB:** Module Terraform của RDS phải được cấu hình sẵn `Multi-AZ` (để test failover) và `rds.logical_replication=1` (để dùng Blue/Green Deployments và công cụ schema migration pg-osc).
3.  **App đã nối sang Managed DB:** Các service cấu hình trong `values-prod.yaml` đã sửa chuỗi kết nối từ cụm DB nội bộ in-cluster sang các Managed DB.
4.  **Bảo đảm Idempotency:** Nhóm dev phải đảm bảo các route nhạy cảm (VD: đặt đơn ở `checkout`) đã được thiết kế chống ghi đúp (Idempotent API) để an toàn tuyệt đối khi Mandate 9 kích hoạt cơ chế Retry.
