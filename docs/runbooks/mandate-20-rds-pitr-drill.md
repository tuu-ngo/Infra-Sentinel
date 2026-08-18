# Mandate 20 runbook - RDS PITR restore drill

Runbook này dùng để chạy restore drill RDS cho Mandate #20 trước mentor/PM hoặc quay video evidence đầy đủ.

**Scope:** CDO02 Reliability/Operations  
**Source DB:** `techx-tf3-postgres`  
**Region:** `ap-southeast-1`  
**Account:** `197826770971`  
**ADR:** [docs/adr/0016-mandate-20-backup-restore-drill-cdo02.md](../adr/0016-mandate-20-backup-restore-drill-cdo02.md)
**Solution:** [docs/docx_cdo02/mandate-20-rds-pitr-restore-solution.md](../docx_cdo02/mandate-20-rds-pitr-restore-solution.md)

Không chạy runbook này nếu chưa có cửa sổ drill được PM/mentor đồng ý.

## 1. Target

```text
RDS RPO target: <= 5 phút
RDS RTO target: <= 45 phút
Expected data loss in probe: 0 row
```

## 2. Safety rules

- Không restore đè production.
- Không đổi `DB_CONNECTION_STRING`.
- Không đổi ExternalSecret/Secret production.
- Không repoint app sang DB drill.
- Không thao tác bảng khách hàng.
- Chỉ tạo/corrupt marker trong schema `dr_drill`.
- Không cleanup DB drill trước khi mentor/PM xác nhận evidence đủ hoặc video/raw output đã capture đủ.

## 2.1. SQL client path for current drill

RDS là private. Đường thao tác SQL hiện dùng trong video script:

```text
Docker postgres:17 psql -> host.docker.internal:15432
localhost:15432 -> SSM bastion -> RDS/private endpoint:5432
```

Không yêu cầu cài `psql` local; dùng Docker image `postgres:17` làm `psql` client mặc định.

## 3. Preflight read-only

```powershell
$Region = "ap-southeast-1"
$SourceDb = "techx-tf3-postgres"
$DbSubnetGroup = "techx-tf3-postgres"
$VpcSecurityGroupId = "sg-025478cd9d0ae1f52"
$DbParameterGroupName = "techx-tf3-postgres17"
$DrillSuffix = Get-Date -Format 'yyyyMMdd-HHmmss'
$DrillId = "techx-tf3-postgres-drill-$DrillSuffix"
$DrillMarkerId = "m20-rds-pitr-$DrillSuffix"

git rev-parse --short origin/main
aws sts get-caller-identity

aws rds describe-db-instances `
  --region $Region `
  --db-instance-identifier $SourceDb `
  --query "DBInstances[0].{Id:DBInstanceIdentifier,Status:DBInstanceStatus,Encrypted:StorageEncrypted,Kms:KmsKeyId,BackupRetention:BackupRetentionPeriod,LatestRestorable:LatestRestorableTime,DeletionProtection:DeletionProtection,MultiAZ:MultiAZ,AZ:AvailabilityZone,Public:PubliclyAccessible,SubnetGroup:DBSubnetGroup.DBSubnetGroupName,VpcSGs:VpcSecurityGroups[].VpcSecurityGroupId}" `
  --output json

aws rds describe-db-instances `
  --region $Region `
  --query "DBInstances[?contains(DBInstanceIdentifier,'drill') || contains(DBInstanceIdentifier,'restore') || contains(DBInstanceIdentifier,'m20')].{Id:DBInstanceIdentifier,Status:DBInstanceStatus,Created:InstanceCreateTime}" `
  --output table
```

Stop nếu:

- Sai account/region.
- Source DB không `available`.
- `BackupRetentionPeriod = 0`.
- `LatestRestorableTime` không cập nhật.
- Có incident/benchmark khác gây nhiễu mà mentor không yêu cầu.

## 4. Create GOOD marker

Kết nối production RDS bằng đường vận hành hiện có, chỉ tạo schema probe:

```sql
-- Replace <DRILL_MARKER_ID> with the PowerShell $DrillMarkerId for this drill.
CREATE SCHEMA IF NOT EXISTS dr_drill;

CREATE TABLE IF NOT EXISTS dr_drill.restore_probe (
  id text PRIMARY KEY,
  expected_payload text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

INSERT INTO dr_drill.restore_probe(id, expected_payload)
VALUES ('<DRILL_MARKER_ID>', 'GOOD_BEFORE_CORRUPTION')
ON CONFLICT (id) DO UPDATE
SET expected_payload = EXCLUDED.expected_payload,
    updated_at = clock_timestamp();

SELECT id, expected_payload, clock_timestamp() AT TIME ZONE 'UTC' AS t_good_commit_utc
FROM dr_drill.restore_probe
WHERE id = '<DRILL_MARKER_ID>';
```

Ghi lại `T_good_commit_utc` và marker id của lần drill. Không dùng lại marker id cũ nếu chạy nhiều lần.

## 5. Corrupt marker in controlled scope

Đợi 60-120 giây rồi chạy:

```sql
-- Replace <DRILL_MARKER_ID> with the marker id used in step 4.
UPDATE dr_drill.restore_probe
SET expected_payload = 'CORRUPTED_AFTER_GOOD_TIME',
    updated_at = clock_timestamp()
WHERE id = '<DRILL_MARKER_ID>';

SELECT id, expected_payload, clock_timestamp() AT TIME ZONE 'UTC' AS t_corrupt_commit_utc
FROM dr_drill.restore_probe
WHERE id = '<DRILL_MARKER_ID>';
```

Chọn `T_restore` nằm sau `T_good_commit_utc` và trước `T_corrupt_commit_utc`.

## 6. Wait until PITR can restore chosen time

```powershell
aws rds describe-db-instances `
  --region $Region `
  --db-instance-identifier $SourceDb `
  --query "DBInstances[0].LatestRestorableTime" `
  --output text
```

Chỉ chạy restore khi `LatestRestorableTime >= T_restore`.

## 7. Restore to isolated drill DB

Production VPC không có default subnet. Vì vậy lệnh restore phải chỉ rõ DB subnet group, security group và DB parameter group của production RDS. Nếu bỏ các tham số này, restore có thể fail với lỗi `InvalidSubnet`.

```powershell
$RestoreTime = "2026-07-28Txx:xx:xxZ"
$Start = Get-Date

aws rds restore-db-instance-to-point-in-time `
  --region $Region `
  --source-db-instance-identifier $SourceDb `
  --target-db-instance-identifier $DrillId `
  --restore-time $RestoreTime `
  --db-instance-class db.t4g.micro `
  --db-subnet-group-name $DbSubnetGroup `
  --vpc-security-group-ids $VpcSecurityGroupId `
  --db-parameter-group-name $DbParameterGroupName `
  --no-publicly-accessible

aws rds wait db-instance-available `
  --region $Region `
  --db-instance-identifier $DrillId

$InfrastructureAvailableAt = Get-Date
$InfrastructureElapsed = $InfrastructureAvailableAt - $Start
"Infrastructure available elapsed: $($InfrastructureElapsed.TotalMinutes) minutes"
```

Inventory DB drill:

```powershell
aws rds describe-db-instances `
  --region $Region `
  --db-instance-identifier $DrillId `
  --query "DBInstances[0].{Id:DBInstanceIdentifier,Status:DBInstanceStatus,Endpoint:Endpoint.Address,AZ:AvailabilityZone,Public:PubliclyAccessible,Created:InstanceCreateTime}" `
  --output json
```

## 8. Verify restored data

Kết nối DB drill, chạy:

```sql
-- Run this on the restored drill DB, not production.
SELECT id, expected_payload, created_at, updated_at, clock_timestamp() AT TIME ZONE 'UTC' AS verify_time_utc
FROM dr_drill.restore_probe
WHERE id = '<DRILL_MARKER_ID>';
```

Pass nếu:

```text
expected_payload = GOOD_BEFORE_CORRUPTION
```

Fail nếu:

```text
expected_payload = CORRUPTED_AFTER_GOOD_TIME
```

Trong trường hợp fail, không claim pass. Dừng lại, lưu lỗi, không patch production để "cứu" drill.

Ngay sau khi query trên **drill endpoint** trả `GOOD_BEFORE_CORRUPTION`, khóa timestamp end-to-end:

```powershell
$VerifiedAt = Get-Date
$Rto = $VerifiedAt - $Start
"Successful restored-data query at: $($VerifiedAt.ToUniversalTime().ToString('o'))"
"End-to-end RTO measured: $($Rto.TotalMinutes) minutes"
```

Không dùng `$InfrastructureAvailableAt` làm RTO end. Contract yêu cầu timer kết thúc sau successful restored-data query.

## 9. Cleanup

Chỉ cleanup sau khi mentor/PM xác nhận evidence đủ hoặc video/raw output đã capture đủ:

```powershell
aws rds delete-db-instance `
  --region $Region `
  --db-instance-identifier $DrillId `
  --skip-final-snapshot

aws rds wait db-instance-deleted `
  --region $Region `
  --db-instance-identifier $DrillId
```

Production marker cleanup phải có phạm vi hẹp. **Không dùng** `DROP SCHEMA dr_drill CASCADE` trên production vì lệnh đó xóa toàn bộ schema, có thể làm mất marker/history của các lần drill khác.

Khuyến nghị mặc định: giữ lại row marker trong production để làm audit trail. Nếu PM/mentor yêu cầu cleanup dữ liệu probe, chỉ xóa đúng marker id của lần drill:

```sql
-- Run on production RDS only if marker cleanup is explicitly approved.
-- Replace <DRILL_MARKER_ID> with the marker id used in this drill.
DELETE FROM dr_drill.restore_probe
WHERE id = '<DRILL_MARKER_ID>';
```

Không drop schema/table trừ khi có change request riêng và đã xác nhận không còn marker/history cần giữ.

## 10. Evidence record checklist

Lưu evidence vào [docs/evidence/mandate-20/](../evidence/mandate-20/):

```text
Git baseline:
AWS caller/account/region:
RDS source inventory:
T_good_commit:
T_restore:
T_corrupt_commit:
DB drill identifier:
Drill marker id:
Restore start:
Infrastructure available at / elapsed:
Successful restored-data query at:
End-to-end RTO measured:
Production corrupt query:
Restored DB GOOD query:
Cleanup result:
Witness mode: mentor/PM live hoặc recorded video
```
