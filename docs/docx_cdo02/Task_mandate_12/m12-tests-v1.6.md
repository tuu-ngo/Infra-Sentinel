# Mandate 12 — Kịch bản tấn công và bằng chứng

> **Trạng thái:** READY FOR REVIEW · thiết kế cho single-account hardened audit; chưa chạy test.

## 1. Quy tắc an toàn

- Chỉ test sau approval, trong UTC window và có observer.
- Dùng canary object/secret, không dùng dữ liệu production.
- Không thử sửa/xóa object Compliance thật.
- Không chạy `StopLogging` nếu operator chưa được xác nhận bounded; dùng IAM simulation trước.
- Nếu lệnh tắt trail thành công ngoài dự kiến: dừng toàn bộ test và mở Critical incident.
- Không bật CLI debug hoặc lưu `SecretString`.
- Tester, operator và audit-admin là IAM identities trong cùng account Free Tier; không kiểm thử Organizations/SCP/cross-account.
- Mọi mutation API test phải được policy simulation trước, chạy bởi dedicated bounded test identity và có audit-admin/break-glass owner trực. Nếu một request thành công, dừng test và xử lý incident; không thử “sửa lại” bằng operator.
- Mỗi EventBridge rule đã deploy phải có một denied API call thật tương ứng, capture event source/name/region, target invocation và SNS receipt. Pattern Terraform không phải PASS.

## 2. Trạng thái

| Trạng thái | Ý nghĩa |
|---|---|
| `DESIGNED` | Test được thiết kế |
| `DEPLOYED` | Control đã apply nhưng chưa mentor test |
| `VERIFIED` | Test pass và có evidence |
| `FAILED` | Control/evidence không đạt |
| `BLOCKED` | Thiếu prerequisite, không được coi là pass |

## 3. Ma trận test tối thiểu

| ID | Đòn thử | Kỳ vọng |
|---|---|---|
| M12-T01 | Operator gọi `StopLogging` | Bị deny; attempt có event + alert; trail vẫn ghi |
| M12-T02 | Operator gọi `DeleteTrail`/đổi selector | Bị deny; config không đổi; có event + alert |
| M12-T03 | Đọc S3 canary object | Có `GetObject` data event |
| M12-T04 | Đọc canary secret | Có `GetSecretValue`; evidence không chứa secret value |
| M12-T05 | Xác minh integrity | `validate-logs` không missing/`INVALID` |
| M12-T06 | Thử xóa/ghi đè log | Production dùng deny evidence; không tamper object thật |
| M12-T07 | Forensic identity chain | Dựng actor/session/action/change trong timebox |
| M12-T08 | Tamper alert plane | Bounded operator không thể disable/delete EventBridge rule/target hoặc SNS topic/subscription; rule match và SNS receipt có evidence |
| M12-T09 | Tamper IAM protection | Bounded operator không thể detach/change boundary, policy attachment/version hoặc trust/assume-role path |
| M12-T10 | Regional IAM alert | Denied IAM event được tìm trong region thực tế; route/alert được chứng minh hoặc verdict giữ `VERIFY-LIVE` |
| M12-T11 | Evidence parse và canary cleanup | Log `.json.gz` được download/read-only, decompress/parse; fixtures được cleanup an toàn sau evidence |

## 4. M12-T01 — StopLogging

### Tiền điều kiện

- Trail `IsLogging=true`.
- Operator role đã gắn và kiểm tra permissions boundary.
- EventBridge/SNS alert healthy.
- Audit-admin và observer sẵn sàng.

### Kỳ vọng

- `AccessDenied`.
- CloudTrail/EventBridge có `StopLogging` attempt, actor, time và error.
- Security owner nhận alert.
- Trail vẫn `IsLogging=true`, không có delivery gap.

### Fail

- Lệnh thành công.
- Không có alert/event.
- Trail ngừng ghi hoặc digest chain có gap.

## 5. M12-T02 — Xóa trail hoặc đổi coverage

Kiểm tra `DeleteTrail`, `UpdateTrail`, `PutEventSelectors` bằng bounded operator. Với mutation có thể thành công, dùng policy simulation thay vì gửi request production.

**PASS:** deny, attempt event/alert và cấu hình sau test không đổi.

## 6. M12-T03 — Đọc S3 object

### Fixture

- Object canary không nhạy cảm.
- Nằm đúng bucket/prefix trong advanced selector.

### Evidence

- `eventSource=s3.amazonaws.com`.
- `eventName=GetObject`.
- Đúng principal/session, bucket/key, UTC time và request ID.

**FAIL:** chỉ thấy bucket management event hoặc không có object data event.

## 7. M12-T04 — Đọc secret

### Fixture

- Canary secret vô giá trị, không được application sử dụng.
- Tester chỉ được đọc canary secret.

### Evidence

- `eventSource=secretsmanager.amazonaws.com`.
- `eventName=GetSecretValue`.
- Đúng principal/session, secret identifier, time và outcome.
- Không có `SecretString`/`SecretBinary` trong evidence.

## 8. M12-T05 — Integrity validation

Chờ digest bao phủ test window, sau đó chạy `validate-logs` theo trail ARN, region và UTC range.

**PASS:** không có missing digest/log hoặc `INVALID`.

**FAIL:** validation gap, signature/hash failure hoặc team chỉ chứng minh file tồn tại.

## 9. M12-T06 — WORM protection

- Không tamper log thật.
- Dùng authorization/deny evidence để chứng minh operator không thể delete/overwrite.
- Hiển thị Object Lock `COMPLIANCE`, retain-until và versioning.
- Nếu cần minh họa tamper detection, dùng fixture sandbox riêng.

## 10. M12-T07 — Forensic identity chain

Mentor thực hiện một action canary qua assumed role hoặc EKS. Team phải dựng:

```text
IAM identity
→ STS assumed-role session
→ AWS/EKS username
→ action/verb/resource
→ Git/Argo CD change nếu liên quan
→ UTC timeline
```

**FAIL:** chỉ biết role dùng chung, không truy về người/session hoặc không xác định được nội dung thay đổi.

## 11. M12-T08 — Tamper alert plane

Trước test, lấy **cả** `terraform output -json anti_audit_rule_arns` và `terraform output -json global_anti_audit_rule_arns`, rồi lập map: **mỗi primary/global rule output → API deny có service-specific event source → target SNS expected**. Foundation hiện tại có đúng 12 rule (7 primary + 5 global) và audit-access bắt buộc nhận đủ 12 ARN. Nếu bổ sung rule, phải cập nhật foundation, validation audit-access và test map trong cùng một change được duyệt; không tự bỏ qua rule mới.

Ví dụ nhóm action cần có trong map: `events:DisableRule`/remove target cho EventBridge, và mutation SNS topic/subscription cho SNS. Tất cả phải nhắm vào control audit thật nhưng được thực hiện từ bounded test identity sau simulation; nếu request không bị deny là Critical incident.

**PASS:** từng rule có API request bị deny, CloudTrail event đúng `eventSource`/`eventName`/`awsRegion`, EventBridge `Invocations`/`FailedInvocations` evidence, target invocation và security owner nhận SNS đúng SLA. Cả primary/global subscription phải `Confirmed`; `PendingConfirmation`, chỉ thấy CloudTrail hoặc chỉ thấy policy simulation đều là **FAIL**.

## 12. M12-T09 — Tamper IAM protection

Dùng dedicated bounded user/role đã có trong [m12-iam-scope-v1.0.md](m12-iam-scope-v1.0.md); không test trên root, audit-admin hoặc workload production. Test tối thiểu một action gỡ/sửa boundary/policy attachment và một action đổi trust/assume-role path sau policy simulation. Với `UpdateAssumeRolePolicy`, request input phải là bản trust policy **hiện tại** của dedicated test role (không tạo broad trust doc); nếu unexpectedly allowed thì request semantic-idempotent nhưng vẫn là Critical incident.

**PASS:** mọi action bị `AccessDenied`; CloudTrail cho biết principal/session/error; IAM tamper rule và SNS có evidence. Nếu CI cần `sts:AssumeRole`, boundary strict mặc định không được attach: chỉ dùng allowlisted variant sau khi exact non-audit roles, trust policy và baseline CI được review/pass.

## 13. M12-T10 — Regional IAM alert

EventBridge matching là regional. Với denied IAM/global-service action, truy evidence CloudTrail ở `ap-southeast-1` và `us-east-1`, ghi `awsRegion` trong event, region của EventBridge rule/target và timestamp SNS receipt.

**PASS:** event và alert route được chứng minh ở region thực tế. Nếu event chỉ xuất hiện ở `us-east-1` nhưng foundation không có route đã test ở đó, không được gọi IAM alert pass; mở change regional riêng hoặc giữ verdict `VERIFY-LIVE`.

## 14. M12-T11 — Evidence parse và canary cleanup

Sau T03/T04, tải **bản sao local** của exact CloudTrail log object `.json.gz`, decompress, parse records và chỉ redaction fields cần cho actor/session/time/resource/request ID. Evidence phải có hash sau redaction và output `validate-logs`; `aws s3 ls` hay filename không chứng minh event.

Sau khi evidence được hash/review, cleanup chỉ canary đã tạo: S3 object bằng delete marker/version-aware procedure và Secrets Manager secret bằng scheduled deletion tối thiểu 7 ngày. Lưu cleanup request/result trong evidence; không xóa audit archive, production object hoặc evidence gốc.

## 15. Test bổ sung sau MVP

- Burst `GetObject` có giới hạn để kiểm tra exfiltration detection.
- Low-and-slow reads để kiểm tra hunting dài ngày.
- Resource mới ngoài selector để kiểm tra coverage drift.
- Root/break-glass tabletop exercise; không dùng root để test live thông thường.

## 16. Evidence pack

```text
M12-Txx/
├── metadata.md
├── request-redacted.txt
├── result-redacted.txt
├── cloudtrail-event-redacted.json
├── cloudtrail-log-copy.json.gz
├── cloudtrail-log-parsed-redacted.json
├── alert-redacted.txt
├── eventbridge-invocation-redacted.json
├── regional-check-redacted.txt
├── trail-health.json
├── integrity-result.txt
├── fixture-cleanup-redacted.txt
└── verdict.md
```

Metadata ghi UTC window, account, region, principal/session, target resource, approver, observer và SHA-256 của evidence files sau redaction.

## 17. Verdict table

| Test | UTC window | Principal | Event found | Alert | Integrity | Verdict |
|---|---|---|---|---|---|---|
| M12-T01 | | | | | | `DESIGNED` |
| M12-T02 | | | | | | `DESIGNED` |
| M12-T03 | | | | N/A | | `DESIGNED` |
| M12-T04 | | | | theo policy | | `DESIGNED` |
| M12-T05 | | | N/A | N/A | | `DESIGNED` |
| M12-T06 | | | | | | `DESIGNED` |
| M12-T07 | | | | N/A | | `DESIGNED` |
| M12-T08 | | | | | | `DESIGNED` |
| M12-T09 | | | | | | `DESIGNED` |
| M12-T10 | | | | | | `DESIGNED` |
| M12-T11 | | | | N/A | | `DESIGNED` |

## 18. Điều kiện mentor sign-off

- Anti-audit attempt bị chặn hoặc alert đúng SLA.
- S3 object/secret reads có vết đầy đủ.
- Integrity chain pass.
- WORM retention pass.
- Identity/forensic attribution pass.
- Coverage matrix không còn resource nhạy cảm `Unknown`/unapproved selector.
- T08–T10 pass, bao gồm mỗi anti-audit rule runtime match và regional IAM alert evidence.
- Root residual-risk acceptance và IAM scope/attachment mapping đã ký.
- Không ảnh hưởng storefront, private ops hoặc flagd.

## 19. Chuẩn bị test từ static review

Static review xác định được hai fixture bắt buộc: một secret chỉ đọc qua `Secrets Manager` (không đọc giá trị secret) và object tại bucket/prefix được owner phê duyệt. Không dùng Terraform state, manifest secret, EKS workload, storefront hoặc flagd làm fixture test.

Mọi test trong tài liệu này chỉ được chạy sau khi audit foundation đã deploy và delivery healthy. Trước đó, test matrix là checklist chuẩn bị evidence; không phải bằng chứng Mandate 12 đã đạt. [m12-coverage-v1.0.md](m12-coverage-v1.0.md) quyết định fixture S3 hợp lệ; canary không tự tạo approval coverage.

## 20. Fixture sau AWS CLI discovery

Discovery xác nhận có hai secret production (`sosflow/db-password`, `techx-corp-tf3/flagd-sync-token`) và 7 S3 bucket, nhưng không xác định được fixture an toàn cho mentor test. Vì vậy Phase 1 phải tạo **canary secret mới không có giá trị nghiệp vụ** và **canary S3 object mới, không nhạy cảm** trong prefix đã được owner duyệt. Không dùng Terraform state, secret hiện hữu, object production hoặc log archive thật làm fixture.

## 21. Gate test theo hai change

- Sau foundation, chỉ chạy T03–T06 và T11 (evidence/cleanup) và ghi trạng thái `DEPLOYED/PARTIAL`; T03 chỉ chạy khi approved S3 prefix đã có trong selector.
- T01/T02/T08–T10 là `BLOCKED`, không phải pass, cho đến khi IAM PR hardening, identity inventory và alert plane regional route được kiểm thử.
- T07 dùng CloudTrail cho AWS timeline; EKS audit log 90 ngày chỉ là nguồn bổ trợ Kubernetes, không được dùng thay integrity/WORM evidence.

---

**Phiên bản:** v1.6  
**Cập nhật:** 18/07/2026  
**Trạng thái:** READY FOR REVIEW — test blocked pending foundation and IAM gates
