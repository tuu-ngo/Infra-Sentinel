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
- RDS PITR drill record thật: [docs/evidence/mandate-20/mandate-20-final-rds-pitr-evidence-20260729.md](mandate-20-final-rds-pitr-evidence-20260729.md).

Hiện tại CDO02 vẫn còn cần chốt:

- Security/delete-authority verdict về quyền xóa backup/snapshot, hoặc accepted-risk note nếu account còn admin-wide.
- Coverage/accepted limitation cuối cùng cho các state ngoài RDS.

Kết luận ngắn: RDS drill đã pass; Mandate 20 overall còn phụ thuộc mentor/PM chấp nhận scope/limitation cho non-RDS stores và delete-authority posture.

## 2. Đối chiếu directive với artifact đã merge

| Yêu cầu directive | Artifact hiện có | Trạng thái |
|---|---|---|
| 1. Không sót store nào trên luồng ra tiền | ADR đã có data-tier commitments và coverage matrix | `Partial` |
| 2. RPO/RTO rõ ràng, cadence tương xứng | RDS có target và measured result; store khác ghi limitation/strategy | `RDS passed / Non-RDS partial` |
| 3. Point-in-time restore chứng minh được | RDS PITR drill đã restore về `T_restore` và trả marker GOOD | `Passed for RDS` |
| 4. Tested restore drill | Evidence record [mandate-20-final-rds-pitr-evidence-20260729.md](mandate-20-final-rds-pitr-evidence-20260729.md): restore correctness passed; infrastructure available elapsed 23.83 phút; end-to-end RTO timestamp pending | `Correctness passed / RTO addendum pending` |
| 5. Backup an toàn, tách quyền xóa | ADR đã nêu delete-authority matrix | `Needs enforcement evidence or accepted risk` |

## 3. Data-tier baseline cần có trước buổi drill

Mandate 20 không cho phép chỉ nhìn mỗi RDS. Trước buổi drill, cần có một baseline record cho từng tầng dưới đây.

| Tầng dữ liệu / state | CDO02 hiện claim gì | Baseline production cần lưu | Trạng thái |
|---|---|---|---|
| RDS PostgreSQL `techx-tf3-postgres` | PITR proof chính | backup retention, latest restorable time, deletion protection, encryption, Multi-AZ, restore target window | Captured + drill passed |
| ElastiCache Valkey `techx-tf3-valkey` | Coverage phụ, không phải proof chính | snapshot cadence/retention, encryption, recovery stance cho cart-state | Captured as limitation/coverage |
| MSK Kafka `techx-tf3-kafka` | Replay/reconciliation, không gọi PITR | retention window, encryption, replay/reconciliation path, destructive-control note | Captured as limitation/coverage |
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

Phần còn thiếu không phải inventory nền nữa, mà là chốt acceptance:

- tầng nào `covered`
- tầng nào `excluded`
- tầng nào `accepted limitation`
- mentor/PM có chấp nhận RDS là proof chính và non-RDS là coverage/limitation hay không

### Requirement 2 - RPO/RTO và cadence

RDS đã có target cụ thể trong ADR và có measured result:

```text
RDS RPO target: <= 5 phút
RDS RPO evidence: T_restore cách GOOD 41.248131 giây, restored marker GOOD, 0 row data loss
RDS RTO target: <= 45 phút
RDS infrastructure available elapsed: 23.83 phút
RDS end-to-end RTO: pending successful-query timestamp addendum
```

Phần còn thiếu cho non-RDS stores:

- điền cadence/retention production thật của Valkey, MSK, state backend
- chỉ ra vì sao cadence đó đủ hoặc chưa đủ so với target
- nếu chưa đủ, phải ghi accepted limitation hoặc dependency rõ ràng

### Requirement 3 - PITR restore

RDS đã đáp ứng bằng evidence thật.

Evidence đã có:

- `T_good_commit_utc`: 2026-07-29T12:02:18.751869Z
- `T_restore`: 2026-07-29T12:03:00Z
- `T_corrupt_commit_utc`: 2026-07-29T12:15:18.439171Z
- RPO evidence: `T_restore` cách GOOD 41.248131 giây, restored marker GOOD, 0 row data loss
- Infrastructure available elapsed: 23.83 phút; end-to-end RTO pending successful-query timestamp
- Restored DB GOOD query: captured in video/evidence record

### Requirement 4 - Tested restore drill

RDS tested restore drill đã chạy thật.

Evidence:

- [docs/evidence/mandate-20/mandate-20-final-rds-pitr-evidence-20260729.md](mandate-20-final-rds-pitr-evidence-20260729.md)
- 4 video đã quay, Drive links đã ghi trong final evidence
- Infrastructure available elapsed `23.83 phút`; chưa dùng làm final RTO vì successful query không có timestamp UTC
- Production marker vẫn `CORRUPTED_AFTER_GOOD_TIME`
- Restored drill DB marker trả `GOOD_BEFORE_CORRUPTION`

### Requirement 5 - Backup an toàn

ADR đã đúng khi không overclaim phần Security.

Phần còn thiếu:

- ai được phép xóa backup/snapshot
- ai không được phép xóa
- accepted risk nếu account còn admin rộng
- encryption / delete-permission verdict hoặc accepted-risk note

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

1. Cleanup DB drill tạm sau khi team/mentor xác nhận đã lưu đủ evidence.
2. Chốt accepted limitation hoặc security verdict cho quyền xóa backup/snapshot.
3. Chốt wording với mentor/PM: RDS drill passed; non-RDS stores là coverage/limitation, không claim PITR như RDS.

## 7. Việc cần Security/delete-authority chốt

- bảng quyền xóa backup/snapshot
- verdict cho DynamoDB PITR / exclusion
- verdict cho state backend protection nếu team claim
- accepted risk nếu còn admin-wide principal

## 8. Kết luận

ADR 0016, runbook, baseline và drill evidence đã đưa Mandate 20 từ mức "có hướng chạy thật" sang "RDS restore drill đã pass".

CDO02 hiện có:

1. **production baseline cho mọi tầng dữ liệu/state**
2. **restore drill thật với RPO/RTO measured**

Cho đến khi có security/delete-authority verdict tương ứng và mentor/PM chấp nhận scope non-RDS, Mandate 20 nên được xem là:

```text
RDS restore drill passed
Overall Done pending accepted scope/limitations for non-RDS stores and delete-authority posture
```
