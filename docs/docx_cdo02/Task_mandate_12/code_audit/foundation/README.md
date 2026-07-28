# Mandate 12 — Audit foundation

Thư mục này là Terraform staging cho audit foundation của TF3. Nó chưa được áp dụng vào AWS và không thay đổi repo product.

## Topology khi apply

| Thành phần | Region | Mục đích |
|---|---|---|
| CloudTrail multi-region, audit S3 Object Lock, EventBridge/SNS chính | `ap-southeast-1` | Ghi management events toàn account, S3 data events đã được owner duyệt, và báo động thay đổi control của audit foundation. |
| EventBridge/SNS global | `us-east-1` | Bắt thay đổi IAM làm yếu permissions boundary/policy và bảo vệ chính global alert controls. |

`global_event_region` cố định là `us-east-1`: CloudTrail ghi IAM/STS/CloudFront global-service events tại Region này. Đây là alert bổ sung, không biến EventBridge rule thành rule ở mọi AWS Region.

## Bảo vệ có chủ đích

- CloudTrail chỉ được tạo sau Object Lock COMPLIANCE, versioning, SSE-S3, public-access block và bucket policy.
- Bucket policy chỉ cho CloudTrail của đúng trail ARN ghi log; mọi principal không phải `cloudtrail.amazonaws.com` bị `Deny` các object mutation của archive.
- Trail được tag `Project=TF3`, `Mandate=12`, `Protected=true`; Terraform từ chối plan nếu `s3_data_event_arns` vô tình chứa audit archive (tránh recursive logging).
- Rule dùng đúng EventBridge `source` của từng service: `aws.cloudtrail`, `aws.s3`, `aws.events`, `aws.sns`, `aws.iam`.
- Cả hai SNS email subscription có `prevent_destroy`; sau apply phải xác nhận cả hai email.

## Giới hạn có chủ đích

Audit bucket **không** được đưa vào `s3_data_event_arns`. AWS khuyến cáo không log S3 data events của chính destination bucket vì CloudTrail delivery tạo thêm `PutObject` data event lặp lại và tăng chi phí. Vì vậy:

- policy bucket chặn object overwrite/delete trực tiếp;
- rule S3 object-tamper được chuẩn bị để khớp nếu một nguồn data-event độc lập được phê duyệt;
- test bắt buộc cho "no blind window" của foundation là `StopLogging`, đổi selector, đổi bucket policy, đổi EventBridge/SNS control bị chặn hoặc tạo alert, cộng với CloudTrail log-file validation;
- nếu mentor yêu cầu alert thời gian thực cho **AccessDenied object operation trên audit bucket**, phải thiết kế một monitor trail có destination Object-Lock **khác** trước khi bật selector đó. Không được tự thêm audit archive vào selector hiện tại.

## Inputs và outputs cần dùng sau apply

`terraform.tfvars.example` cần bucket mới, prefix S3 nhạy cảm đã được duyệt và security-owner email. Outputs `trail_arn`, hai topic ARN, hai subscription ARN (chỉ dùng sau khi `Confirmed` và refresh state), `anti_audit_rule_arns`, `global_anti_audit_rule_arns` là dữ liệu đầu vào để chốt IAM hardening riêng.

## Kiểm tra staging

```powershell
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```

Không chạy `plan`/`apply` từ thư mục staging này cho đến khi backend, scope S3, email owner, cost approval và IAM change riêng đã được phê duyệt.

---
Version: 1.1 | 2026-07-18
