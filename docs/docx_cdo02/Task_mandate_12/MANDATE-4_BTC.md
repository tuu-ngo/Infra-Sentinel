# mandate 4 này sẽ không là mandate này hỗ trợ để làm mandate 12
Kiểm toán sẽ soi sâu TF3. Câu hỏi của kiểm toán không phải "hệ thống có chạy không" mà là: "chuyện gì đã xảy ra, ai làm, khi nào - và làm sao tin được bản ghi đó?". TF3 phải chứng minh mình dựng lại được sự thật từ dấu vết, và dấu vết đó không sửa được.

Yêu cầu
Có đường ghi vết đầy đủ. Bật ghi nhật ký hành động ở tầng cụm và cloud (K8s audit log + CloudTrail hoặc tương đương) + change trail cho thay đổi cấu hình / hạ tầng (ai, khi nào, nội dung).
Bài forensic (chấm tại chỗ). BTC sẽ chọn một hành động hoặc một sự cố đã diễn ra (một thay đổi config, hoặc một lần bật flag) và yêu cầu TF3 dựng lại timeline ai-làm-gì-khi-nào chỉ từ audit log / trace, trong thời gian giới hạn. Dựng không ra = chưa đạt.
Bản ghi toàn tin (tamper-evident). Chứng minh audit log không sửa / xóa được tùy tiện - quyền ghi tách khỏi người vận hành (người vận hành không tự xóa được vết của mình).
Truy về người. Mọi thay đổi lớn + hành động on-call quy được về một danh tính (không dùng chung tài khoản).
Ràng buộc
Trong ngân sách hiện tại (~$300/tuần/TF).
Storefront vẫn công khai, cổng vận hành vẫn riêng tư (Directive #1); không đụng / vô hiệu hóa flagd (Luật chơi).
Phải nộp
Cho mentor cách xem audit log (K8s / cloud) + chịu bài forensic tại chỗ: mentor tự chọn một sự kiện, TF3 truy vết ra người + thời điểm + nội dung ngay trước mặt, và cho thấy bản ghi không sửa được.
Được nhìn ở trụ nào
Chính là Auditability - truy vết forensic, log integrity, change management, quy trách nhiệm về người. Chạm thêm Security (kiểm soát quyền ghi / đọc audit) và Operational Excellence (kỷ luật thay đổi).

Directive riêng cho TF3. Điểm nằm ở chỗ: khi bị hỏi "chuyện gì đã xảy ra", TF3 dựng lại được sự thật từ dấu vết và chứng minh dấu vết đó đáng tin.