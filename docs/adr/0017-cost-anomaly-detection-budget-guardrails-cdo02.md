# ADR 0017 — Cost guardrails: AWS Cost Anomaly Detection + Budget hard-ceiling

**Ngày:** 19/08/2026
**Người quyết định (ký):** Huu Tai Ngo — CDO02 (Reliability + Cost Optimization)
**Trụ:** Cost Optimization
**Trạng thái:** ✅ Quyết định — triển khai module `cost-guardrails` (Terraform, qua PR + CI), bật ở production

---

## Bối cảnh

Cost đang được theo dõi **100% thủ công**: chạy Cost Explorer lọc `RECORD_TYPE=Usage`, ghi tay vào `docs/cost-breakdown-*.md`. Không có cơ chế tự động cảnh báo khi chi tiêu vượt trần hoặc đột biến bất thường.

Đây là việc đã được đánh dấu **"nên làm sớm"** ở hai nơi mà chưa ai làm:

- [`phase3 - information/onboarding/BUDGET.md`](../../phase3%20-%20information/onboarding/BUDGET.md) — *"AWS Budgets + Cost Anomaly Detection … Dựng cái này sớm là một việc nên làm."*
- [`docs/backlog/week2-action-plan.md`](../backlog/week2-action-plan.md) (P1) — *"Dựng AWS Budget alert — theo dõi trần $300/tuần."*

Bối cảnh cost thật (quét 21/07, [`docs/cost-breakdown-2026-07-22.md`](../cost-breakdown-2026-07-22.md)): **$426/tuần so với trần $300/tuần/TF (142%)**. Rủi ro là các khoản mồ côi âm thầm (2 OCU OpenSearch Serverless của AIO02, VPC endpoint, stack ngoài Phase 3 ở Tokyo) — đúng loại chi tiêu mà con người bỏ sót giữa hai lần quét tay.

## Quyết định

Dựng module Terraform `infra/modules/cost-guardrails/` với **hai lớp bổ trợ**, cùng đẩy vào một SNS topic chung để tái dùng danh sách người nhận của audit alert-plane:

| Lớp | Resource | Bắt gì |
|---|---|---|
| **1. Cost Anomaly Detection** | `aws_ce_anomaly_monitor` (DIMENSIONAL/SERVICE) + `aws_ce_anomaly_subscription` (IMMEDIATE, ngưỡng $30) | Đột biến **bất thường** theo từng service — AWS tự học baseline. Bắt được đột biến giữa hai mốc tháng mà budget không thấy. |
| **2. Budgets** | `aws_budgets_budget` (COST, MONTHLY, $1300) — cảnh báo 80% ACTUAL / 100% ACTUAL / 100% FORECASTED | Trần **cứng** đã biết trước. Forecast báo *trước* khi cán trần. |

Bật bằng cờ `enable_cost_guardrails = true` trong tfvars (mặc định module `false`, giống `enable_managed_datastores`).

## Các điểm kỹ thuật quan trọng (nếu làm sai thì alert "câm" trong im lặng)

1. **Region — global service, endpoint us-east-1.** Cả Cost Anomaly Detection lẫn Budgets chỉ publish được vào **SNS topic ở us-east-1**. Module chạy dưới provider alias `aws.us_east_1` (đã có sẵn trong `providers.tf`); topic + CMK cũng nằm us-east-1.

2. **Credit che chi phí.** Account đang được credit phủ ~100% → nhìn hoá đơn ròng thấy ~$0, **không phản ánh mức tiêu thật** (memory `cost-explorer-credit-masks-spend`). Budget đặt `cost_types { include_credit = false; include_refund = false; include_tax = false }` để **khớp cách đo tay** `RECORD_TYPE=Usage`. `include_credit = false` là setting mấu chốt — thiếu nó thì budget báo theo net và vô dụng.

3. **KMS + publish cross-service.** Topic mã hoá bằng CMK, nên `budgets.amazonaws.com` và `costalerts.amazonaws.com` phải được cấp **cả** `sns:Publish` (trên topic policy) **và** `kms:GenerateDataKey*`/`kms:Decrypt` (trên key policy). Cấp mỗi `sns:Publish` sẽ trả `AuthorizationError` và alert biến mất không dấu vết — cùng lớp lỗi đã ghi ở audit-detection (PM-126). Điều kiện `aws:SourceAccount` (+ `aws:SourceArn` = budget ARN cho Budgets) chặn confused-deputy.

4. **AWS test-publish khi tạo subscription.** `aws_ce_anomaly_subscription` với subscriber SNS sẽ test publish lúc create → `depends_on` topic policy để policy có trước.

## Đánh đổi đã chấp nhận (ghi rõ để không nhầm là "đã xong tất")

- **Không có đơn vị WEEKLY trong Budgets.** Trần thật là $300/**tuần**, nhưng Budgets chỉ có DAILY/MONTHLY. Chọn MONTHLY $1300 (= 300×52/12) vì daily budget không hỗ trợ forecast và sẽ báo gần như mỗi ngày. Hệ quả: budget **làm mượt** các gai theo tuần — đó chính là lý do **cần Lớp 1** để bắt đột biến trong tháng.
- **Monitor account-wide.** DIMENSIONAL/SERVICE phủ toàn account, nên **bao gồm cả workload ngoài Phase 3 ở Tokyo** (`thermal-power-plant-*`, ~$23/tuần). Nếu thành nhiễu, chuyển sang CUSTOM monitor lọc theo cost-allocation tag `project` — nhưng tag đó phải **kích hoạt tay trong billing console** (mất ~24h) trước khi dùng được, nên chưa đưa vào lần này. `default_tags` đã gắn `project=techx-corp-phase3` sẵn sàng cho bước đó.
- **Ngưỡng $30 là điểm khởi đầu**, không phải chân lý — chờ dữ liệu thật vài tuần rồi hiệu chỉnh.

## Xác minh sau apply (chưa chạy — CI apply chưa thực hiện)

1. Mỗi người nhận có mail SNS "Subscription Confirmation" → **phải bấm confirm** thì mới nhận alert (email subscription của SNS cần double opt-in).
2. Console Billing → Cost Anomaly Detection: monitor `techx-corp-tf3-service-monitor` = Active, subscription trỏ đúng topic.
3. Console Billing → Budgets: budget `techx-corp-tf3-monthly-ceiling` hiện đúng limit $1300, 3 alert.
4. Gửi test publish vào topic (hoặc chờ anomaly thật) để xác nhận đường mail thông.

## Hệ quả

- Đóng checkbox P1 backlog + mục "nên làm sớm" của BUDGET.md.
- Cost chuyển từ giám sát thủ công sang **push alert tự động**, dùng chung inbox với audit plane.
- Không đụng Mandate #8/#13/#17 hay nodegroup — thuần observability chi phí, zero rủi ro runtime.
