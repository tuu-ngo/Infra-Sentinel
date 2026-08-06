# Mandate 20 - Production baseline and gap analysis

Tài liệu này nối giữa:

- directive gốc `MANDATE-20-dr-backup-restore.md`
- ADR [docs/adr/0016-mandate-20-backup-restore-drill-cdo02.md](../../adr/0016-mandate-20-backup-restore-drill-cdo02.md)
- runbook [docs/runbooks/mandate-20-rds-pitr-drill.md](../../runbooks/mandate-20-rds-pitr-drill.md)

Mục tiêu là trả lời 3 câu hỏi trước khi claim pass Mandate 20:

1. ADR/runbook hiện đã cover được bao nhiêu phần của directive.
2. Production thật còn thiếu evidence nào.
3. CDO02 còn phải làm gì tiếp, phần nào cần Security/delete-authority verdict hoặc accepted risk.

## 1. Tóm tắt trạng thái hiện tại

Hiện tại CDO02 đã có:

- ADR chốt hướng `RDS PITR restore drill` làm proof chính.
- Runbook restore drill an toàn, restore ra DB tách biệt.
- Evidence index cho Mandate 20.
- Production baseline cho từng tầng dữ liệu/state.
- RDS PITR drill record thật nằm trong file tổng hợp: [docs/evidence/mandate-20/mandate-20-final-evidence-20260731.md](mandate-20-final-evidence-20260731.md).
- File trạng thái chính sau feedback mentor: [mandate-20-final-evidence-20260731.md](mandate-20-final-evidence-20260731.md).

Hiện tại CDO02 vẫn còn cần chốt:

- MSK replay proof đang bị chặn bởi Kyverno exact-digest governance, cần approved Kafka client qua GitOps/CI.
- Valkey restore target đã tạo được nhưng canary key không restore về drill, nên chưa pass canary proof.
- Backup delete-protection mới ở mức partial/remediation in progress: IAM explicit deny chặn direct delete API, nhưng guard tự gỡ được; Terraform đã bổ sung RDS AWS Backup Compliance Vault Lock, vẫn cần CI apply, recovery point evidence và hết 3 ngày cooling-off để claim immutability.

Kết luận ngắn: RDS drill đã pass; Mandate 20 overall **chưa pass** cho tới khi non-RDS proof và hard backup delete-protection được làm xong hoặc mentor/PM chấp nhận limitation rõ ràng.

## 2. Đối chiếu directive với artifact đã merge

| Yêu cầu directive | Artifact hiện có | Trạng thái |
|---|---|---|
| 1. Không sót store nào trên luồng ra tiền | ADR đã có data-tier commitments; rescue status đã ghi rõ gap Valkey/MSK/delete-protection | `Partial / not yet pass` |
| 2. RPO/RTO rõ ràng, cadence tương xứng | RDS có target và measured result; Valkey/MSK chưa có proof hoàn chỉnh | `RDS passed / Non-RDS not yet` |
| 3. Point-in-time restore chứng minh được | RDS PITR drill đã restore về `T_restore` và trả marker GOOD | `Passed for RDS` |
| 4. Tested restore drill | Evidence record [mandate-20-final-evidence-20260731.md](mandate-20-final-evidence-20260731.md), RTO 23.83 phút | `Passed for RDS` |
| 5. Backup an toàn, tách quyền xóa | Evidence đã ghi pre-check allowed, IAM explicit deny remediation, post-check explicitDeny cho direct delete API; Terraform remediation thêm RDS AWS Backup Compliance Vault Lock, nhưng chưa đủ evidence đến khi apply/cooling-off xong | `Partial / remediation in progress` |

## 3. Data-tier baseline cần có trước buổi drill

Mandate 20 không cho phép chỉ nhìn mỗi RDS. Trước buổi drill, cần có một baseline record cho từng tầng dưới đây.

| Tầng dữ liệu / state | CDO02 hiện claim gì | Baseline production cần lưu | Trạng thái |
|---|---|---|---|
| RDS PostgreSQL `techx-tf3-postgres` | PITR proof chính | backup retention, latest restorable time, deletion protection, encryption, Multi-AZ, restore target window | Captured + drill passed |
| ElastiCache Valkey `techx-tf3-valkey` | Managed snapshot/restore path, không gọi PITR | snapshot cadence/retention, encryption, restore/canary result | Restore target available nhưng canary chưa proven |
| MSK Kafka `techx-tf3-kafka` | Replay/reconciliation, không gọi PITR | retention window, encryption, replay/reconciliation path, destructive-control note | Baseline captured; replay blocked by Kyverno governance |
| DynamoDB lock table | Exclude nếu chỉ là Terraform lock | tên bảng, chức năng thực tế, PITR có bật hay exclude có lý do | Excluded from business-data restore under current evidence |
| EBS / volume legacy | Không dùng làm proof chính | volume/snapshot ownership hoặc accepted limitation | Accepted limitation / avoid M8-M18 conflict |
| GitOps / IaC state | Covered bằng source-of-truth process nếu team claim | Git baseline, state backend/versioning/Object Lock nếu có, secret reference path | Captured as source-of-truth/state-backend limitation |

## 4. Gap còn thiếu để pass theo từng yêu cầu

### Requirement 1 - Không sót store nào trên luồng ra tiền

ADR và production baseline đã ghi đủ các store/state cần nói tới:

- RDS
- Valkey
- MSK
- DynamoDB lock
- legacy volume/EBS
- GitOps/IaC state

Phần còn thiếu không phải inventory nền nữa, mà là proof/acceptance:

- tầng nào `covered`
- tầng nào `excluded`
- tầng nào `accepted limitation`
- MSK replay có được chạy bằng approved client hay không
- Valkey canary restore có được rerun trong SLO-green window hay mentor chấp nhận limitation hay không
- backup delete-protection chưa đủ hard guard: IAM deny hiện tại tự gỡ được; RDS Vault Lock đang được thêm bằng Terraform nhưng cần apply/cooling-off; các đường `ModifyDBInstance`, `DeleteDBInstance`, `DeleteReplicationGroup`, `ScheduleKeyDeletion` vẫn cần chốt bằng guardrail khác hoặc accepted risk

### Requirement 2 - RPO/RTO và cadence

RDS đã có target cụ thể trong ADR và có measured result:

```text
RDS RPO target: <= 5 phút
RDS RPO evidence: T_restore cách GOOD 41.248131 giây, restored marker GOOD, 0 row data loss
RDS RTO target: <= 45 phút
RDS RTO measured: 23.83 phút
```

Phần còn thiếu cho non-RDS stores:

- MSK cần replay proof hoặc accepted limitation.
- Valkey cần canary restore proof hoặc accepted limitation.
- State backend/delete-protection đã có IAM explicit deny cho normal operator/CI apply path, nhưng state bucket chưa có Object Lock và IAM guard còn self-removable.
- RDS backup delete-protection đang có hướng hard guard bằng AWS Backup Compliance Vault Lock trong Terraform; cần capture LockDate và recovery point sau CI apply.

### Requirement 3 - PITR restore

RDS đã đáp ứng bằng evidence thật.

Evidence đã có:

- `T_good_commit_utc`: 2026-07-29T12:02:18.751869Z
- `T_restore`: 2026-07-29T12:03:00Z
- `T_corrupt_commit_utc`: 2026-07-29T12:15:18.439171Z
- RPO evidence: `T_restore` cách GOOD 41.248131 giây, restored marker GOOD, 0 row data loss
- RTO measured: 23.83 phút
- Restored DB GOOD query: captured in video/evidence record

### Requirement 4 - Tested restore drill

RDS tested restore drill đã chạy thật.

Evidence:

- [docs/evidence/mandate-20/mandate-20-final-evidence-20260731.md](mandate-20-final-evidence-20260731.md)
- 4 video đã quay, Drive links đã ghi trong final evidence
- RTO `23.83 phút`, trong target `<= 45 phút`
- Production marker vẫn `CORRUPTED_AFTER_GOOD_TIME`
- Restored drill DB marker trả `GOOD_BEFORE_CORRUPTION`

### Requirement 5 - Backup an toàn

ADR đã đúng khi không overclaim phần Security.

Phần còn thiếu:

- ai được phép xóa backup/snapshot
- ai không được phép xóa
- hard guard nào đang chặn normal operator/CI
- negative test/audit evidence
- accepted risk nếu account còn admin rộng và chưa kịp tách quyền

## 5. Checklist production baseline cần chụp trước khi drill

Lưu thành raw evidence trong thư mục [docs/evidence/mandate-20/](.).

### 5.1. RDS

Phải có:

- `DBInstanceIdentifier`
- `BackupRetentionPeriod`
- `LatestRestorableTime`
- `StorageEncrypted`
- `DeletionProtection`
- `MultiAZ`
- `PubliclyAccessible = false`

### 5.2. DynamoDB

Phải có:

- danh sách bảng liên quan
- nếu chỉ có Terraform lock thì ghi rõ `exclude with reason`
- nếu claim backup thì phải có trạng thái PITR

### 5.3. Valkey

Phải có:

- snapshot cadence / retention
- encryption posture
- accepted recovery stance cho cart-state

### 5.4. MSK

Phải có:

- cluster status
- retention / replay stance
- encryption posture
- giải thích vì sao đây không phải PITR nhưng vẫn có recovery path

### 5.5. GitOps / IaC state

Phải có:

- Git baseline commit
- manifest source of truth
- state backend / versioning / Object Lock nếu team claim
- đường tham chiếu secret/config để dựng lại

## 6. Việc CDO02 nên làm tiếp ngay

1. Dùng [mandate-20-final-evidence-20260731.md](mandate-20-final-evidence-20260731.md) làm file chính để mentor đọc trạng thái sau feedback.
2. MSK: chuẩn bị approved Kafka client qua GitOps/CI rồi chạy canary replay, hoặc xin mentor accept blocker governance.
3. Valkey: chỉ rerun canary restore khi SLO-green và không có failover/snapshot noise, hoặc xin mentor accept limitation.
4. Backup delete-protection: giữ verdict partial/remediation in progress; merge/apply RDS AWS Backup Compliance Vault Lock, capture LockDate/recovery point, và chỉ claim immutability sau 3 ngày cooling-off.
5. Cleanup tài nguyên drill tạm sau khi đã lưu đủ evidence và được PM/mentor xác nhận.

## 7. Việc cần Security/delete-authority chốt

- bảng quyền xóa backup/snapshot theo từng resource và principal
- IAM explicit deny đã được chọn cho normal operator/CI apply path nhưng chưa đủ vì self-removable; SCP không khả dụng, RDS Vault Lock đang được thêm bằng Terraform, state bucket Object Lock chưa bật
- negative test bằng IAM simulation đã chứng minh normal operator/CI apply không xóa được backup protected
- verdict cho DynamoDB PITR / exclusion
- verdict cho state backend protection nếu team claim
- accepted risk nếu còn admin-wide principal

## 8. Kết luận

ADR 0016, runbook, baseline và drill evidence đã đưa Mandate 20 từ mức "có hướng chạy thật" sang "RDS restore drill đã pass". Sau feedback mentor, trạng thái chính được cập nhật trong [mandate-20-final-evidence-20260731.md](mandate-20-final-evidence-20260731.md).

CDO02 hiện có:

1. **production baseline cho mọi tầng dữ liệu/state**
2. **restore drill thật với RPO/RTO measured cho RDS**
3. **rescue status rõ ràng cho MSK/Valkey và delete-protection remediation in progress**

Cho đến khi có non-RDS proof hoặc accepted limitation, Mandate 20 nên được xem là:

```text
RDS restore drill passed
Overall Mandate 20: NOT YET PASS
Open: MSK replay, Valkey canary restore, applied/cooling-off-complete backup delete-protection
```
