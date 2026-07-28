# Mandate 11 - Thiết kế Lambda retry và xử lý sự kiện lỗi

**Người phụ trách tài liệu:** Phạm Tùng Dương

**Ngày:** 20/07/2026

**Trạng thái:** `DESIGN ONLY - IMPLEMENTATION DEFERRED UNTIL INFRASTRUCTURE IS READY`

## 1. Mục tiêu

Luồng cảnh báo audit không được mất event âm thầm khi EventBridge không gọi được Lambda hoặc khi Lambda đã nhận event nhưng xử lý thất bại. Thiết kế này bổ sung retry, dead-letter queue, giám sát và quy trình replay mà không thay đổi phạm vi storefront, cổng vận hành hay flagd.

Luồng mục tiêu:

```text
CloudTrail
  -> EventBridge rule
     -> EventBridge target retry
        -> Lambda asynchronous queue
           -> Lambda retry
              -> SNS alert

EventBridge delivery exhausted -> EventBridge delivery DLQ
Lambda processing exhausted    -> Lambda on-failure SQS destination
```

## 2. Hai lớp lỗi phải phân biệt

### 2.1. EventBridge chưa giao được event cho Lambda

Ví dụ: Lambda permission sai, target không tồn tại, throttling hoặc lỗi dịch vụ. Đây là lỗi **delivery**. EventBridge retry việc gọi target; nếu hết retry thì gửi event sang EventBridge DLQ.

Mặc định AWS retry tối đa 24 giờ và 185 lần với exponential backoff và jitter. Với Mandate 11, phải cấu hình rõ trong Terraform để reviewer nhìn được chính sách thay vì phụ thuộc default.

### 2.2. Lambda đã nhận event nhưng handler thất bại

Ví dụ: Python exception, timeout, `SNS.publish` lỗi hoặc `cloudwatch:PutMetricData` lỗi. Đây là lỗi **processing**. Với asynchronous invocation, Lambda mặc định retry thêm hai lần cho function error; throttling và system error có thể được retry lâu hơn theo event age.

Sau khi hết retry hoặc event quá tuổi, Lambda phải gửi invocation record sang SQS on-failure destination. Không được chỉ ghi log rồi bỏ event.

## 3. Trạng thái hiện tại của PR #219

Code hiện có:

- một SQS queue tên `${name_prefix}-lambda-dlq`;
- `dead_letter_config` trên `aws_lambda_function`;
- queue policy cho service principal `lambda.amazonaws.com`;
- chưa có `aws_lambda_function_event_invoke_config`;
- chưa có `retry_policy` hoặc `dead_letter_config` trên EventBridge target;
- Lambda execution role chưa có `sqs:SendMessage` tới failure queue;
- chưa có alarm cho retry, Lambda error hoặc DLQ;
- handler chưa deduplicate event và có thể gửi email/metric trùng khi retry.

Vì vậy, cấu hình hiện tại chưa đủ để xác nhận retry path hoạt động đầu-cuối.

## 4. Cấu hình đề xuất

### 4.1. EventBridge target retry

Đặt cấu hình trực tiếp trên `aws_cloudwatch_event_target.audit_alert_router`:

```hcl
retry_policy {
  maximum_event_age_in_seconds = 300
  maximum_retry_attempts       = 10
}

dead_letter_config {
  arn = aws_sqs_queue.eventbridge_delivery_dlq.arn
}
```

Lý do chọn:

- `300` giây bám ngưỡng cảnh báo công khai `<= 5 phút`;
- nhiều lần retry ngắn giúp vượt lỗi delivery tạm thời;
- nếu không thể giao trong ngưỡng, event được giữ ở DLQ và alarm phải kêu thay vì tiếp tục im lặng.

EventBridge DLQ phải là standard SQS queue cùng region. Queue policy phải cấp `sqs:SendMessage` cho `events.amazonaws.com`, giới hạn bằng `aws:SourceArn` của rule và `aws:SourceAccount`.

### 4.2. Lambda asynchronous retry

Thay cấu hình DLQ legacy bằng on-failure destination có invocation context đầy đủ:

```hcl
resource "aws_lambda_function_event_invoke_config" "audit_alert_router" {
  function_name                = aws_lambda_function.audit_alert_router.function_name
  maximum_event_age_in_seconds = 300
  maximum_retry_attempts       = 2

  destination_config {
    on_failure {
      destination = aws_sqs_queue.lambda_failure_dlq.arn
    }
  }
}
```

Không duy trì đồng thời hai cơ chế failure destination nếu không có lý do và ownership rõ ràng. On-failure destination được ưu tiên vì giữ thêm thông tin về request và response, thuận tiện điều tra/replay.

Lambda execution role phải có:

```hcl
statement {
  sid       = "SendFailedAuditEventsToSqs"
  effect    = "Allow"
  actions   = ["sqs:SendMessage"]
  resources = [aws_sqs_queue.lambda_failure_dlq.arn]
}
```

### 4.3. Sửa handler trước khi bật retry

Retry sẽ khuếch đại lỗi cố định nếu handler chưa được sửa. Phải đóng tối thiểu các mục sau:

1. xử lý an toàn khi EventBridge gửi `resources: []`;
2. thêm `event_id = detail.eventID` hoặc fallback top-level `id` vào log, alert và DLQ context;
3. không blanket-allowlist Group 1/2;
4. giữ nguyên exception khi SNS publish thất bại để Lambda retry;
5. không để lỗi publish custom metric chặn cảnh báo chính; gửi SNS trước hoặc bắt riêng lỗi metric;
6. log attempt, AWS request ID và failure stage nhưng không log secret value.

### 4.4. Idempotency và chống cảnh báo trùng

Lambda async có cơ chế at-least-once, vì vậy cùng một CloudTrail event có thể được xử lý nhiều lần. Giải pháp đề xuất:

- khóa dedup bằng CloudTrail `detail.eventID`; fallback top-level EventBridge `id`;
- dùng DynamoDB on-demand table nhỏ với conditional write và TTL 24 giờ;
- nếu conditional write báo key đã tồn tại, log `duplicate_event` và không gửi lại SNS;
- chỉ ghi trạng thái dedup hoàn tất sau khi SNS publish thành công, hoặc dùng state `processing/sent` có timeout để tránh mất alert khi Lambda chết giữa chừng.

Nếu chưa triển khai DynamoDB, payload và subject ít nhất phải có event ID để on-call nhận biết duplicate. Không được tuyên bố đã kiểm soát nhiễu hoàn toàn nếu chưa có dedup state.

## 5. Monitoring và alarm bắt buộc

| Layer | Metric | Ngưỡng gợi ý | Ý nghĩa |
|---|---|---:|---|
| EventBridge | `RetryInvocationAttempts` | `>= 1` trong 5 phút | Target bắt đầu cần retry |
| EventBridge | `FailedInvocations` | `>= 1` | Giao target thất bại vĩnh viễn |
| EventBridge | `InvocationsSentToDlq` | `>= 1` | Event đã vào delivery DLQ |
| EventBridge | `InvocationsFailedToBeSentToDlq` | `>= 1` | DLQ hoặc permission lỗi |
| Lambda | `Errors` | `>= 1` | Handler/runtime lỗi |
| Lambda | `Throttles` | `>= 1` | Thiếu concurrency |
| Lambda | `AsyncEventAge` | `>= 180000 ms` | Gần chạm mục tiêu TTD nội bộ |
| Lambda | `AsyncEventsDropped` | `>= 1` | Event bị bỏ sau retry/expiry |
| Lambda | `DeadLetterErrors` | `>= 1` | Cấu hình DLQ legacy không nhận được event |
| Lambda | `DestinationDeliveryFailures` | `>= 1` | Lambda không gửi được failure record |
| SQS | `ApproximateNumberOfMessagesVisible` | `>= 1` | Có event cần điều tra/replay |

Alarm failure path phải đi tới một topic/on-call độc lập với Lambda audit router. Nếu alarm dùng cùng Lambda/SNS path đang lỗi, hệ thống sẽ tự làm mù cảnh báo lỗi của chính nó.

## 6. Replay an toàn

1. On-call lấy message từ DLQ bằng quyền read-only phù hợp.
2. Đối chiếu `eventID`, event time, actor, target và failure stage với CloudTrail/Lambda logs.
3. Xác nhận lỗi đã được sửa hoặc dependency đã phục hồi.
4. Replay từng message, không bulk replay khi chưa biết nguyên nhân.
5. Giữ nguyên event ID để dedup hoạt động.
6. Xóa message khỏi DLQ chỉ sau khi Lambda xử lý thành công và alert đã tới người nhận.
7. Ghi incident/change reference cho mọi replay production.

Không chỉnh timestamp gốc của CloudTrail. TTD sau replay phải tách thành:

- `original_detection_latency`: từ event time đến lần xử lý đầu;
- `recovery_latency`: từ failure đầu đến replay thành công;
- `end_to_end_alert_latency`: từ event time đến lúc người nhận thấy alert.

## 7. Kế hoạch kiểm thử sau khi hạ tầng sẵn sàng

| Test | Cách tạo lỗi | Kỳ vọng | Bằng chứng |
|---|---|---|---|
| R1 - EventBridge delivery | Dùng test rule/target Lambda canary không cho invoke | Có retry, rồi message vào EventBridge DLQ | `RetryInvocationAttempts`, DLQ message |
| R2 - Lambda processing | Test alias/canary chủ động raise exception | Tổng cộng một lần chạy đầu và tối đa hai retry, sau đó on-failure destination nhận record | Lambda logs theo request ID, SQS message |
| R3 - DLQ permission | Kiểm tra policy bằng IAM simulation và một failure canary | Không có `DestinationDeliveryFailures`/`InvocationsFailedToBeSentToDlq` | IAM result, metrics |
| R4 - Duplicate | Gửi lại cùng event ID hai lần | Chỉ một SNS alert, lần sau log `duplicate_event` | Lambda logs và một email |
| R5 - Recovery | Sửa lỗi rồi replay một message | Alert tới người, DLQ giảm về 0 | replay log, email, SQS metric |

Không tạo failure trực tiếp trên Lambda production nếu chưa có change window. Dùng test alias hoặc canary có cùng cấu hình retry/DLQ.

## 8. Điều kiện hoàn tất

Chỉ chuyển tài liệu từ `DESIGN ONLY` sang `VERIFIED` khi có đủ:

- Terraform plan/apply của retry policy, two-layer DLQ, IAM permission và alarms;
- test R1-R5 pass;
- ảnh CloudWatch metrics và DLQ;
- ít nhất một replay thành công;
- một alert Group 1/2 thành công trong ngưỡng `<= 5 phút`;
- runbook/on-call owner nhận và xác nhận quy trình.

## 9. Tài liệu tham chiếu

- [AWS EventBridge retry policy](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-rule-retry-policy.html)
- [AWS Lambda asynchronous error handling](https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-error-handling.html)
- [AWS Lambda asynchronous invocation configuration](https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-configuring.html)
- [AWS Lambda failure destinations and DLQ](https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-retain-records.html)
- [AWS EventBridge delivery metrics](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-monitoring-events-best-practices.html)
