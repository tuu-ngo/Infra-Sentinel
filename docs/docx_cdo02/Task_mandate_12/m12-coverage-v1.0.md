# Mandate 12 — Coverage matrix bắt buộc

> **Trạng thái:** DRAFT / `NO-GO` cho plan hoặc apply cho đến khi tất cả hàng bắt buộc được hoàn tất và phê duyệt.

## 1. Mục đích và quy tắc

Matrix này là nguồn quyết định scope logging của Mandate 12. Nó phải được hoàn tất từ inventory live **metadata-only** trước plan; không được đọc giá trị secret hoặc tải dữ liệu production để điền matrix.

- Mỗi nơi chứa hoặc cho phép đọc dữ liệu nhạy cảm phải có một hàng riêng, owner, cách truy cập và control ghi log tương ứng.
- `Unknown`, `TBD`, bỏ trống, hoặc “không thuộc scope” không có chữ ký owner/security là `NO-GO`.
- S3 chứa dữ liệu nhạy cảm phải có exact ARN bucket/prefix trong `s3_data_event_arns`; không dùng wildcard hoặc all-S3 để thay cho quyết định scope.
- Secret trong Secrets Manager dùng CloudTrail management events read/write; CloudTrail ghi metadata/API identity, không được đưa `SecretString`/`SecretBinary` vào evidence.
- Audit archive không đưa vào selector S3 data events để tránh vòng lặp logging. Terraform state **không được tự động loại trừ**: owner phải phân loại nó; nếu state có dữ liệu nhạy cảm hoặc secret output thì phải có coverage `GetObject` hoặc một control thay thế được security owner phê duyệt bằng văn bản.
- Canary chỉ chứng minh control cho prefix/secret class; không thay thế inventory hoặc approval cho dữ liệu thật.

## 2. Gate coverage trước deployment

Chỉ chuyển sang `APPROVED FOR APPLY` khi đồng thời đạt tất cả điều kiện:

1. Inventory live trong change window đã liệt kê toàn bộ secret metadata và toàn bộ S3 bucket hiện hữu; mỗi bucket có classification bởi data owner.
2. Mọi hàng `Sensitive` hoặc `Critical` có owner, exact scope, CloudTrail coverage và test evidence được chỉ định.
3. Mảng `s3_data_event_arns` trong `terraform.tfvars` khớp **từng giá trị** với hàng S3 `APPROVED` trong matrix; không có selector thừa/chưa được duyệt.
4. Mọi S3 bucket/prefix bị loại khỏi data-event scope có lý do, compensating control (nếu có) và acceptance của security owner. Một resource nhạy cảm không có coverage không được chấp nhận là “ngoại lệ im lặng”.
5. Test canary có thể đặt trong một prefix nhạy cảm đã duyệt mà không sửa object production; secret canary là secret mới không có giá trị nghiệp vụ.

## 3. Matrix dữ liệu

Điền một hàng cho **mỗi** asset/prefix. Các hàng mẫu dưới đây không phải approval. Trước plan phải thay `TBD` bằng dữ liệu đã xác nhận hoặc thêm hàng mới.

| ID | Asset/định danh | Phân loại / owner | Đường đọc cần quan sát | Coverage bắt buộc | Scope exact / input Terraform | Kiểm thử và evidence | Quyết định |
|---|---|---|---|---|---|---|---|
| COV-01 | Secrets Manager: `sosflow/db-password` | Sensitive; owner `TBD` | `GetSecretValue`, thay đổi secret | Management events Read/Write, all regions | Không cần S3 selector | Không đọc secret thật; canary `GetSecretValue`, parsed CloudTrail event có actor/session/resource | `PENDING OWNER` |
| COV-02 | Secrets Manager: `techx-corp-tf3/flagd-sync-token` | Sensitive; owner `TBD` | `GetSecretValue`, thay đổi secret | Management events Read/Write, all regions | Không cần S3 selector | Không đọc secret thật; dùng canary mới, evidence không có secret value | `PENDING OWNER` |
| COV-03 | Mọi secret metadata còn lại phát hiện ở Phase 0 | Classify từng secret; owner từng asset | Read/write API tương ứng | Management events Read/Write | Không cần S3 selector | So sánh `list-secrets` metadata với matrix, canary theo class | `PENDING INVENTORY` |
| COV-04 | S3 `techx-products-catalog-2026` | Prefix/classification/owner `TBD` | `GetObject` nếu prefix nhạy cảm | S3 Object data events | `arn:aws:s3:::<bucket>/<approved-prefix>/` cho từng prefix Sensitive | Canary object ở prefix đã duyệt; parsed `GetObject` event | `PENDING OWNER` |
| COV-05 | S3 `techx-tf3-197826770971-tfstate` | Security/IaC owner phải xác nhận có/không sensitive output | `GetObject` state nếu classified Sensitive | S3 Object data events **nếu Sensitive**; không auto-exclude | Exact state prefix hoặc documented non-sensitive decision | Evidence classification + canary/safe read procedure đã duyệt | `PENDING CLASSIFICATION` |
| COV-06 | S3 `thermal-power-plant-frontend-197826770971` | Prefix/classification/owner `TBD` | `GetObject` nếu prefix nhạy cảm | S3 Object data events | Exact approved prefix, nếu có | Canary object + parsed event | `PENDING OWNER` |
| COV-07 | Bốn S3 bucket còn lại từ inventory live và mọi bucket/prefix mới | Tạo một hàng cho từng bucket/prefix; không gộp “other buckets” | Theo classification | S3 Object data events nếu Sensitive | Exact approved prefix | Evidence data owner + canary theo class | `PENDING INVENTORY` |
| COV-08 | Kubernetes Secret/API hoặc data path ngoài S3/Secrets Manager, nếu tồn tại live | Platform owner + security owner | API access tương ứng | Nguồn audit phù hợp (EKS audit log là supplemental, không thay CloudTrail archive) | Nêu rõ nguồn/retention hoặc explicit out-of-scope acceptance | Query/evidence riêng | `PENDING DISCOVERY` |
| COV-09 | Audit S3 archive | Security/IaC owner | Log/digest delivery | CloudTrail destination, Object Lock, integrity validation; **không** S3 data selector | Audit bucket mới | `validate-logs`, Object Lock, delivery health | `REQUIRED FOUNDATION` |

### Quy tắc cho 7 S3 bucket đã biết

Discovery chỉ xác nhận số lượng 7 bucket và ba tên ở trên. Trước plan, data owner phải chạy inventory metadata-only gần thời điểm deploy, ghi đủ bảy tên vào matrix và phân loại từng bucket/prefix là `Sensitive`, `Not sensitive`, `System/audit`, hoặc `Unknown`.

- `Sensitive`: bắt buộc exact prefix selector + evidence test.
- `Not sensitive`: cần owner + lý do; review lại khi loại dữ liệu thay đổi.
- `System/audit`: audit archive chỉ được ghi bằng CloudTrail destination/integrity, không thêm data-event selector.
- `Unknown`: `NO-GO`.

## 4. Matrix cấu hình quan trọng

Các thay đổi control cũng phải có vết management event và route cảnh báo đã test. Không được chỉ kiểm tra pattern Terraform; phải có một API call bị deny thật cho mỗi rule đã deploy.

| ID | Control | Mutations cần phát hiện/chặn | Log + alert requirement | Test/evidence bắt buộc | Trạng thái |
|---|---|---|---|---|---|
| CFG-01 | CloudTrail trail/selectors/validation | `StopLogging`, `DeleteTrail`, `UpdateTrail`, `PutEventSelectors` | Management event + service-specific EventBridge rule + SNS | Bounded operator denied; actor/error/alert/trail health | `PENDING` |
| CFG-02 | Audit S3 bucket | Policy, versioning, Object Lock, lifecycle, encryption, public access; object delete/overwrite | **Config mutation:** management event + audit-bucket alert rule. **Archive object data operation:** bucket policy/boundary deny + Object Lock/digest, không tự claim EventBridge alert vì archive không vào S3 data selector | Denied config API + Object Lock/retention evidence; object tamper chỉ dùng authorization evidence, không tamper log thật | `PENDING` |
| CFG-03 | EventBridge rules/targets | Disable/delete rule, remove target, change event pattern | Management event + alert-plane rule | Denied call for each deployed alert-rule mapping; SNS receipt | `PENDING` |
| CFG-04 | SNS topic/subscription/policy | Delete topic, subscription/policy change | Management event + SNS alert-plane route | Denied call; capture EventBridge invocation + confirmed recipient | `PENDING` |
| CFG-05 | IAM boundary, managed policy, attachments, role trust | Detach/delete boundary, policy version/attachment, `UpdateAssumeRolePolicy` | Management event + IAM tamper route | Dedicated bounded test identity; denied call + regional verification | `PENDING` |
| CFG-06 | KMS, nếu dùng CMK | Disable/deletion/policy mutation | Management event + KMS route | Denied call/alert in approved region | `NOT APPLICABLE UNTIL CMK` |

## 5. Xác nhận và liên kết evidence

Trước apply, lưu cùng change record:

- Bản matrix đã điền, timestamp UTC, account/region, người lập và security/data/IaC owners phê duyệt.
- Danh sách exact `s3_data_event_arns` đã đối chiếu với matrix.
- Link tới [m12-iam-scope-v1.0.md](m12-iam-scope-v1.0.md), `tfplan.txt`, forecast chi phí và evidence path.

Sau mentor test, cập nhật từng hàng bằng evidence path, UTC window, request ID và verdict. Không dùng matrix để tuyên bố coverage hồi tố cho khoảng thời gian trước khi CloudTrail delivery + digest healthy.

---

**Phiên bản:** v1.0  
**Cập nhật:** 18/07/2026  
**Trạng thái:** DRAFT — mandatory approval artifact before deployment
