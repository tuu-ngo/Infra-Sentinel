# Mandate 12 — Kế hoạch và runbook triển khai

> **Trạng thái:** READY FOR REVIEW · chỉ thực hiện sau khi solution và gate được phê duyệt.

## 1. Nguyên tắc

- Không sửa repository production trong giai đoạn discovery.
- Không dùng root user để deploy.
- Mọi plan/apply qua identity cá nhân assume-role và saved plan.
- Chỉ dùng IAM user/role trong account Free Tier `197826770971`; không có bước Organizations, SCP hoặc cross-account.
- Audit foundation và IAM hardening là hai change riêng.
- Không dùng secret thật hoặc object thật cho mentor demo.
- Không đánh dấu `VERIFIED` chỉ vì apply thành công.
- [m12-coverage-v1.0.md](m12-coverage-v1.0.md) và [m12-iam-scope-v1.0.md](m12-iam-scope-v1.0.md) là artifact bắt buộc, không phải tài liệu tham khảo tùy chọn.

## 2. Phase 0 — Discovery chỉ đọc

Thu evidence:

1. Caller/account/region.
2. Trail hiện có, status, selectors, validation và destination.
3. Bucket/Object Lock/KMS/lifecycle hiện có trong account.
4. EKS control-plane logs và retention.
5. IAM admin users/roles, CI apply role, assume-role path và root hygiene.
6. Sensitive S3 bucket/prefix.
7. Secret inventory metadata; không đọc secret value.
8. Event volume và cost baseline.
9. Coverage matrix: classification/owner/exact scope cho toàn bộ data asset nhạy cảm.
10. Daily-admin/CI inventory, trust/assume-role path, exception và root residual-risk acceptance.

### Kết quả đã xác nhận

- Không có CloudTrail trail hoặc Object Lock bucket để tái sử dụng.
- EKS `api`/`audit`/`authenticator` logging đang bật, retention 90 ngày.
- IAM user vận hành hiện tại có `AdministratorAccess` qua group.
- Có hai secret live: `sosflow/db-password` và `techx-corp-tf3/flagd-sync-token`.
- Có 7 S3 bucket; chưa bucket nào có Object Lock. Chỉ `techx-products-catalog-2026` và `techx-tf3-197826770971-tfstate` có Versioning `Enabled`.

Do đó Phase 1 phải tạo audit foundation mới; Phase 3 IAM hardening là điều kiện trước khi chạy deny test trên operator role.

### Go/No-Go

**GO** khi owner, scope, retention, alert recipient, backend/state và rollback path rõ ràng.

**NO-GO** khi:

- không biết trail/bucket hiện có thuộc ai;
- có nguy cơ tạo duplicate trail/bucket không cần thiết;
- chưa biết workflow nào phụ thuộc `AdministratorAccess`;
- còn S3 bucket/prefix, secret hoặc daily-admin identity `Unknown`/chưa có owner;
- plan có change/delete production resource;
- không có người giữ break-glass hoặc security alert.

## 3. Phase 1 — Audit foundation

### Dự kiến tạo/cập nhật

- Account CloudTrail multi-region.
- Management read/write events.
- S3 data selector được duyệt.
- S3 audit archive Versioning + Object Lock Compliance 365 ngày.
- Log file integrity validation.
- Primary (`ap-southeast-1`) và global (`us-east-1`) EventBridge/SNS anti-audit alert planes.

### Không thay đổi

- EKS workload, network, edge, datastore, flagd và application.

### Gate plan

- Chỉ add/update audit resources.
- Không destroy.
- Không mở public access.
- Không ghi secret vào state/config.
- Không bật S3 data events ngoài scope.
- `s3_data_event_arns` khớp từng giá trị với hàng `APPROVED` trong coverage matrix.
- Forecast cost trong ngân sách.

### Gate sau apply

- `IsLogging=true`.
- Multi-region/global events đúng.
- Event selectors đúng management/data coverage.
- Log và digest được delivery.
- Object Lock/retention đúng.
- Cả hai alert subscription healthy/`Confirmed`.
- Tất cả anti-audit rule có mapping test runtime theo service-specific event source; chưa có claim regional IAM alert khi chưa test.

Nếu chưa có digest, trạng thái là `DEPLOYED`, chưa `VERIFIED`.

## 4. Phase 2 — Coverage tests

Chuẩn bị:

- canary S3 object không nhạy cảm trong prefix được log;
- canary secret vô giá trị, không app nào sử dụng;
- mentor/tester role có đúng quyền tối thiểu.

Kiểm tra:

1. `GetObject` tạo S3 data event.
2. `GetSecretValue` tạo management read event.
3. Config change canary tạo management write event.
4. Event có actor, session, time, resource, outcome và request ID.
5. Download log `.json.gz` theo exact key, decompress/parse record và redaction evidence; không chỉ dựa vào `aws s3 ls`.
6. Cleanup canary object/secret theo procedure sau khi evidence đã hash và review.

## 5. Phase 3 — IAM hardening riêng

### Thiết kế access migration

1. Hoàn tất [m12-iam-scope-v1.0.md](m12-iam-scope-v1.0.md): inventory toàn bộ use case, policy, group, trust/OIDC và escalation path của apply/admin role hiện tại.
2. Deploy standalone `audit_access` root sau foundation: audit-admin chỉ đọc evidence, break-glass chỉ `StartLogging`/`EnableRule`; root là exception có acceptance, không đưa root vào boundary.
3. Render/create boundary và attachment mapping trong PR IAM tái lập được; strict template là `NO-GO` nếu CI cần `sts:AssumeRole`, allowlist variant phải review exact non-audit roles/trust/OIDC trước.
4. Deploy standalone `iam_change` executor root với explicit target set, MFA security owner và removal flag `false`; security owner assume executor bằng short-lived session.
5. Test CI plan, EKS operations, incident response và rollback bằng role mới.
6. Chuyển từng workflow/user một, lưu baseline verdict và rollback path.
7. Chỉ loại quyền admin trực tiếp khi mọi test pass; bất kỳ identity `Unknown` nào là `NO-GO`.

Boundary phải loại quyền:

- mutate CloudTrail;
- sửa/xóa audit bucket/Object Lock;
- tắt EventBridge/SNS alert;
- sửa/gỡ chính boundary và audit protection policy.
- sửa trust policy hoặc tạo assume-role path để né boundary.

Không chuyển IAM hàng loạt trong cùng change với trail/bucket.

## 6. Phase 4 — Mentor verification

Tối thiểu:

- thử `StopLogging`/`DeleteTrail` bằng bounded operator;
- thử mutation audit S3, EventBridge rule/target, SNS và IAM boundary/trust policy bằng dedicated bounded test identity;
- đọc canary object;
- đọc canary secret;
- chạy `validate-logs`;
- chứng minh từng rule match API call bị deny thật, có EventBridge invocation/SNS receipt và `awsRegion`;
- với IAM/global-service event, kiểm tra evidence ở `ap-southeast-1` và `us-east-1`, hoặc giữ IAM alert ở trạng thái `VERIFY-LIVE`;
- dựng một forensic timeline cloud/Kubernetes/Git nếu action liên quan EKS.

Chi tiết nằm trong file [m12-tests-v1.6.md](m12-tests-v1.6.md).

## 7. Vận hành sau triển khai

### Hằng ngày

- trail logging/delivery health;
- anti-audit alarms;
- delivery/digest errors.

### Hằng tuần

- integrity validation theo time window;
- coverage reconciliation với bucket/secret mới;
- re-review identity inventory, trust policy và exception/root acceptance;
- cost thực tế so với forecast;
- review IAM/boundary drift;
- EKS audit retention và forensic query readiness.

### Khi mandate khác tạo resource

```text
Resource mới
→ phân loại dữ liệu
→ thêm coverage selector nếu cần
→ plan/review
→ canary verification
→ cập nhật coverage matrix
```

## 8. Failure handling

| Lỗi | Xử lý |
|---|---|
| Trail ngừng ghi | Critical incident; preserve actor/evidence. Break-glass chỉ được `StartLogging`/`EnableRule`; nếu trail/topic/bucket bị delete thì root custodian + Terraform recovery change riêng xử lý |
| Delivery error | Kiểm tra bucket policy/encryption; không nới public/admin rộng |
| Missing digest | Khoanh UTC window; không tuyên bố integrity pass |
| `GetObject` không có event | Sửa exact ARN selector sau cost review |
| `GetSecretValue` không có event | Kiểm tra management read coverage và region/time |
| Alert không đến | Kiểm tra rule/target/subscription; dừng mentor destructive test |
| IAM alert chỉ xuất hiện ở `us-east-1` hoặc không có regional route | Không tuyên bố IAM alert pass; mở change riêng để tạo/duyệt route đúng region rồi test lại |
| IAM boundary làm hỏng workflow | Quay lại role cũ theo approved rollback; không gỡ audit foundation |
| Cost spike | Thu hẹp noisy non-sensitive selectors; không tắt mandatory logging |

## 9. Rollback

- Không rollback bằng cách tắt audit hoặc xóa archive.
- Object Lock Compliance đã áp dụng không thể rút ngắn.
- Có thể revert selector batch gây noise, nhưng vẫn giữ sensitive coverage.
- IAM migration rollback độc lập về role cũ trong thời gian test, với approval và audit trail.
- Nếu audit bucket cấu hình sai, dừng ghi mới sau approval và chuyển destination; giữ object cũ tới hết retention.

## 10. Definition of Done

- Audit foundation `DEPLOYED` và delivery healthy.
- Operator boundary được test mà không làm hỏng CI/operations.
- Mentor tests pass.
- Coverage matrix không còn `Unknown`; selector khớp exact approved scope và inventory daily-admin hoàn chỉnh.
- Tất cả alert-plane/IAM tamper test pass, gồm regional IAM evidence hoặc approved regional route.
- Integrity validation pass.
- Retention evidence pass.
- Forensic attribution về cá nhân/session pass.
- Cost trong budget.
- Không ảnh hưởng storefront, private ops hoặc flagd.

## 11. Điều kiện bắt đầu chuẩn bị deployment

Static review đủ để bắt đầu chuẩn bị PR/code ở một audit root riêng, nhưng chưa cho phép chạy apply. Trước khi tạo PR phải chốt: tên/region audit bucket, coverage matrix đầy đủ (bao gồm classification Terraform state), alert owner/regional route, backend state key, IAM scope/attachment mapping và root residual-risk acceptance.

PR audit phải có plan riêng, không có thay đổi trong `infra/live/production`; reviewer đối chiếu plan với allowlist audit resources. Nếu plan có thay đổi EKS, network, Cloudflare, datastore, flagd hoặc resource workload khác thì dừng và tách nguyên nhân trước khi review tiếp.

Trước khi tạo PR/plan phải revalidate chỉ đọc các thông số live và quyền thực thi. Ngay trước apply, lặp lại các kiểm tra tối thiểu (caller/account, trail absence/presence, bucket name, approved selector, alert recipient) để phát hiện drift. Chỉ khi tất cả gate pass mới chuyển từ `READY FOR REVIEW` sang `APPROVED FOR APPLY`.

## 12. Input còn thiếu trước PR

AWS CLI đã đủ để loại bỏ giả định sai về trail/Object Lock, nhưng không tự quyết định scope nghiệp vụ. Owner phải phê duyệt bằng văn bản: bucket/prefix S3 cần log `GetObject`, classification Terraform state, người nhận SNS, tên audit bucket, backend state key, vai trò audit-admin và root residual risk. Không chọn `sosflow/db-password`, `flagd-sync-token`, Terraform state hay production object làm canary.

## 13. Cost gate

Trước apply, tạo forecast từ số object read/write của prefix đã duyệt và đơn giá CloudTrail Data Events/S3 storage hiện hành; lưu forecast cùng `tfplan.txt`. Đặt no-go nếu forecast hoặc mức sử dụng quan sát được khiến tổng chi phí audit có nguy cơ vượt ngân sách `$300/tuần/TF`. Không xử lý cost bằng cách tắt coverage bắt buộc; chỉ thu hẹp prefix không nhạy cảm sau approval.

---

**Phiên bản:** v1.5  
**Cập nhật:** 18/07/2026  
**Trạng thái:** READY FOR REVIEW — deployment blocked pending gates
