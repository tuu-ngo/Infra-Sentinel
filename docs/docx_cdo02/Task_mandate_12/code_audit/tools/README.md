# Công cụ evidence Mandate 12

`Export-M12CloudTrailEvidence.ps1` trích xuất metadata đã redaction từ **một** file CloudTrail `.json.gz` đã tải về máy cục bộ. Công cụ không gọi AWS, không thay đổi production và không xuất request body hoặc giá trị secret.

Luồng dùng trong mentor test:

1. Từ audit-admin read-only role, copy đúng file log CloudTrail từ audit bucket về workspace evidence cục bộ.
2. Chạy script với API cần chứng minh (`GetSecretValue`, `GetObject`, `StopLogging`, `DeleteTrail`, `DisableRule`, ...).
3. Lưu JSON output cùng với lệnh `validate-logs`, ảnh alert và UTC window. Chỉ lưu metadata được script xuất ra; không lưu secret/object content.

Ví dụ:

```powershell
.\Export-M12CloudTrailEvidence.ps1 `
  -LogFile .\CloudTrail-ap-southeast-1-20260718T1200Z.json.gz `
  -EventName GetObject `
  -ResourceContains 'approved-sensitive-bucket/approved-prefix/' `
  -OutputPath .\evidence\M12-T03-s3-getobject.json
```

Đối với secret, dùng `-EventName GetSecretValue` và `-ResourceContains <secret ARN hoặc tên>`; script chỉ xuất actor, timestamp, request ID và identifier, không xuất `SecretString`.

---

**Phiên bản:** v1.0  
**Cập nhật:** 18/07/2026  
**Trạng thái:** STAGING — chỉ chạy trên bản sao log trong evidence workspace
