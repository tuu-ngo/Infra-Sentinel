# Báo cáo Audit: Luồng Browse & Giỏ hàng (Đối chiếu SLO)

## 1. Mục tiêu Audit
Thực hiện một luồng giao dịch E2E giả lập (Duyệt sản phẩm -> Thêm vào giỏ hàng) nhằm đối chiếu tỷ lệ thành công với cam kết trong `SLO.md`. Đồng thời sử dụng dữ liệu từ Jaeger và Dashboard Grafana PM-75 để phân tích độ trễ và dò tìm các rủi ro ngầm.

## 2. Kết quả đối chiếu SLO



Dựa vào dữ liệu thu thập được từ Grafana (thời gian rolling 24h):
- **Luồng Browse (Xem sản phẩm):** Success Rate đạt **99.5012%** (vừa đủ đạt chuẩn SLO $\ge$ 99.5%). Mặc dù đạt chuẩn nhưng con số này đang nằm sát mép ranh giới vi phạm, cần chú ý theo dõi thêm. Về tốc độ, p95 Latency là **53ms** (Rất tốt, vượt xa chuẩn $< 1000ms$).
- **Luồng Cart (Giỏ hàng):** Success Rate đạt **100.00%** (Vượt chuẩn SLO $\ge$ 99.5%). 

**👉 Kết luận trạng thái 2 luồng:** Đang duy trì trạng thái **KHỎE** (Đạt SLO).

## 3. Phân tích Trace & Phát hiện Rủi ro ngầm (Jaeger)



Phân tích một luồng Trace `user_add_to_cart` (thời gian chạy ~24.38ms):
- **Đường đi (Topology):** `load-generator` $\rightarrow$ `frontend-proxy` $\rightarrow$ `frontend` $\rightarrow$ `product-catalog` $\rightarrow$ `postgresql`.
- **Độ trễ (Latency):** Các service trong chuỗi đều phản hồi cực kỳ nhanh. Đáng chú ý là bản thân service `product-catalog` xử lý chỉ mất khoảng **2.05ms**, trong đó câu lệnh query xuống `postgresql` chiếm **1.84ms**.

**🚨 Cảnh báo Rủi ro ngầm (Hidden Risk):**
Qua biểu đồ Trace, chúng ta thấy rõ luồng Browse/Cart phụ thuộc trực tiếp vào cơ sở dữ liệu `postgresql` thông qua service `product-catalog`. 
Mặc dù hiện tại tốc độ đang rất khoẻ, nhưng vì nó có chung **root cause** với sự cố sập hệ thống INC-1/2/3 đợt trước (sử dụng Postgres nhưng không giới hạn Connection Pool), nên nếu lượng truy cập tăng vọt (Spike Traffic), kết nối từ `product-catalog` xuống DB sẽ bị quá tải và gây sập dây chuyền toàn bộ luồng Browse.

**👉 Đề xuất hành động (Tạo Backlog mới):**
- **Tạo 1 task mới:** Cấu hình giới hạn Connection Pool (vd: triển khai PgBouncer hoặc giới hạn max_connections ở mức code) cho service `product-catalog` để phòng ngừa rủi ro (Task này là 1 dòng backlog mới hoàn toàn, tách biệt với các task P2 hiện tại).
