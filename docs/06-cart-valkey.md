# Evidence: Cart & Valkey Operation

## 1. Mục tiêu
Hiểu cart state và rủi ro vận hành của Valkey trong hệ thống.

## 2. Câu trả lời
- **Valkey đang lưu gì?**
  Valkey lưu trữ trạng thái giỏ hàng của người dùng (user cart), cụ thể là ánh xạ giữa `userId` với danh sách các sản phẩm (`productId`) và số lượng (`quantity`) tương ứng. (Theo log `AddItemAsync`, `GetCartAsync` từ `ValkeyCartStore`).

- **Cart state có còn sau khi refresh không?**
  Có, trong điều kiện hoạt động bình thường, state lưu trên Valkey sẽ được truy xuất lại qua `GetCartAsync` khi người dùng refresh ứng dụng. Tuy nhiên, nếu pod Valkey restart thì toàn bộ dữ liệu sẽ bị mất do không được thiết lập persistence.

- **Sau checkout cart xử lý thế nào?**
  Sau khi người dùng thanh toán/checkout thành công, giỏ hàng sẽ bị xóa. Log của cart service ghi nhận phương thức `EmptyCartAsync called with userId=...` được thực thi để dọn dẹp giỏ hàng.

- **valkey-cart có phải single instance không?**
  Đúng, `valkey-cart` đang chạy với mô hình single instance. Deployment spec hiển thị `Replicas: 1 desired | 1 updated | 1 total`.

- **Memory limit là bao nhiêu?**
  Memory limit của container `valkey-cart` được thiết lập rất thấp, chỉ ở mức `20Mi`.

- **Baseline có persistence/replication không?**
  Không. Deployment không mount bất kỳ Volume nào (trạng thái `Volumes: <none>`), đồng thời cũng không có cơ chế replication vì chỉ cấu hình duy nhất 1 replica.

## 3. Evidence
### Kết quả test cart
Log từ `deploy/cart` xác nhận các thao tác thêm, đọc, và dọn dẹp giỏ hàng tương tác trực tiếp tới `ValkeyCartStore`:
```text
info: cart.cartstore.ValkeyCartStore[0]
      AddItemAsync called with userId=9b425a40-7dbc-11f1-841d-fa1592bd2e96, productId=66VCHSJNUP, quantity=10
info: cart.cartstore.ValkeyCartStore[0]
      GetCartAsync called with userId=9b425a40-7dbc-11f1-841d-fa1592bd2e96
info: cart.cartstore.ValkeyCartStore[0]
      EmptyCartAsync called with userId=9b425a40-7dbc-11f1-841d-fa1592bd2e96
```

### Evidence deployment/resource của Valkey
Trích xuất từ lệnh `kubectl describe deploy valkey-cart`:
```text
Name:                   valkey-cart
Replicas:               1 desired | 1 updated | 1 total | 1 available | 0 unavailable
Containers:
 valkey-cart:
  Image:      valkey/valkey:9.0.1-alpine3.23
  Limits:
    memory:      20Mi
Mounts:        <none>
Volumes:       <none>
```

## 4. Risk Statement
- **Mất cart state:** Do không cấu hình Persistent Volumes (`Volumes: <none>`), mọi dữ liệu giỏ hàng tồn tại hoàn toàn trong memory của container. Nếu pod `valkey-cart` bị restart (do lỗi, update, hoặc evict), toàn bộ giỏ hàng của người dùng chưa checkout sẽ bị xóa sạch, bắt buộc khách hàng phải tìm và thêm lại từ đầu, gây ra trải nghiệm rất tồi tệ.
- **OOM (Out of Memory):** Memory limit quá thấp (`20Mi`). Với số lượng người dùng đồng thời lớn lên hoặc một giỏ hàng có nhiều sản phẩm, Valkey sẽ nhanh chóng chạm trần bộ nhớ, dẫn đến việc container bị hệ điều hành (OOMKiller) tắt đi và khởi động lại liên tục.
- **Single point of failure (SPOF) & Timeout:** Hệ thống chỉ có 1 replica duy nhất. Nếu node chứa pod này gặp sự cố hoặc pod crash, toàn bộ dịch vụ phụ thuộc vào Valkey (như `cart`) sẽ bị treo hoặc timeout (init container của `cart` có thiết lập timeout 30s), làm gián đoạn hoàn toàn luồng mua sắm (checkout flow) của cả hệ thống do không có instance dự phòng để phục vụ lưu lượng.
