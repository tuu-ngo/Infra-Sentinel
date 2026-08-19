# Báo Cáo Nộp Bài: AI Mandate #7b - Chạy Thật + Đo Đạc Minh Bạch (Proactive ML Detection & RCA)

- **Trạng thái**: Sẵn sàng đánh giá (Ready for Evaluation)
- **Đội ngũ thực hiện**: Task Force 3 (Team AIO02)
- **Hạn nộp**: Thứ Bảy 25/07/2026

---

## 🎫 1. Thông Tin Ticket Jira

* **Summary:** `AI MANDATE #7b`
* **Labels:** `ai-mandate`, `m7`
* **Priority:** `High`

---

## 💬 2. Nội Dung Comment Bằng Chứng (Evidence Comment)

*(Copy toàn bộ phần bên dưới để paste vào comment của Jira Ticket)*

---

### 🔗 1. Link PR / Commit (Code & Config)

* **Repository:** `https://github.com/Baronger23/Capstone03`
* **Proactive ML Loop + Slack Approval endpoint:** [main.py](https://github.com/Baronger23/Capstone03/blob/main/aiops-engine/main.py)
* **Thuật toán Isolation Forest + SLO Burn Rate:** [anomaly_detector.py](https://github.com/Baronger23/Capstone03/blob/main/aiops-engine/anomaly_detector.py)
* **LLM Chẩn đoán nguyên nhân gốc (RAG Playbooks):** [llm_diagnostician.py](https://github.com/Baronger23/Capstone03/blob/main/aiops-engine/llm_diagnostician.py)
* **Script đo đạc đa dịch vụ minh bạch (No Warmup Trim):** [evaluate_mandate_7b_15.py](https://github.com/Baronger23/Capstone03/blob/main/aiops-engine/evaluate_mandate_7b_15.py)
* **Kết quả Benchmark đa dịch vụ JSON:** [multiservice_benchmark_results.json](https://github.com/Baronger23/Capstone03/blob/main/aiops-engine/datametric/multiservice_benchmark_results.json)

---

### 🚀 2. Hướng Dẫn Chạy Lại Đánh Giá (Repro Steps)

Mentor có thể kiểm thử toàn bộ luồng đo đạc minh bạch trên **7 microservices** (không cắt warmup, có nhiễu tải cao thực tế):

```bash
kubectl --server=https://localhost:8443 --insecure-skip-tls-verify=true \
  exec deployment/aiops-engine -n techx-tf3 -- \
  python evaluate_mandate_7b_15.py
```

---

### 📊 3. Bối Cảnh Đo Đạc Minh Bạch (Evaluation Context & Disclosures)

- **Số lượng dịch vụ đo đạc**: **7 microservices** (`frontend`, `checkout`, `payment`, `product-catalog`, `product-reviews`, `shipping`, `recommendation`).
- **Tổng số chu kỳ Telemetry**: **420 chu kỳ** (30 phút liên tục).
- **Độ nhiễu tải cao thực tế (High Noise)**: RPS trung bình 80 req/s, Latency nền 45ms, CPU 35% (Không dùng dữ liệu latency/error = 0 ảo).
- **Cửa sổ Warmup-trim**: **BỎ HOÀN TOÀN** (Đo đạc 100% dòng dữ liệu không cắt tỉa).

---

### 📐 4. Kết Quả Số Liệu Thực Tế & Vai Trò Hai Lớp (Multi-Layer Architecture)

#### 🅰️ Bảng So Sánh Chỉ Số Đơn Lớp ML vs Hệ Thống 2 Lớp (Combined):

| Chỉ số Metric | Isolation Forest Standalone (Thuần ML) | Combined 2-Layer System (ML + SLO Gate) | Ghi chú & Vai trò Kiến trúc |
|:---|:---:|:---:|:---|
| **Precision** | **7.12%** | **100.0%** | ML phát hiện nhạy; Cổng SLO lọc sạch báo động giả |
| **Recall** | **90.0%** | **90.0%** | Bắt trọn 9/10 giai đoạn sự cố thực tế |
| **False Positive Rate (FPR)** | **90.26%** | **0.00%** | Cổng SLO triệu tiêu toàn bộ 352 nhiễu giả |
| **Confusion Matrix (TP / FP / FN / TN)** | `27 / 352 / 3 / 38` | `27 / 0 / 3 / 390` | Động lực kết hợp 2 lớp hoàn hảo |

#### 🅱️ Phân Định Vai Trò Kiến Trúc Hai Lớp (Layer Value Proposition):

1. **Lớp 1 - ML Isolation Forest (Chủ động/Proactive)**:
   - Đóng vai trò bộ lọc độ nhạy cao (**High Sensitivity / High Recall = 90%**), quét đa chiều (CPU, Memory, Latency deviation, RPS delta) để phát hiện sự cố rò rỉ sớm trước khi chạm ngưỡng thảm họa.
2. **Lớp 2 - SLO Burn Rate & Health Gate (Chính xác/High Precision)**:
   - Đóng vai trò bộ lọc chính xác cao (**High Precision = 100%**), dùng công thức Burn Rate $K=14.4$ trên Span Metrics để triệt tiêu 352 cảnh báo nhiễu ngắn hạn, đưa tỷ lệ báo giả về **0.0%**.

---

### 📝 5. Thiết Kế & Đánh Đổi (ADR Signed)

Chi tiết thiết kế kiến trúc hai lớp phát hiện, RCA qua Jaeger Trace, và Human-in-the-Loop Slack Card được lưu tại:

* **Consolidated ADR:** [CONSOLIDATED_ADR.md](https://github.com/Baronger23/Capstone03/blob/main/docs/adr/CONSOLIDATED_ADR.md)
