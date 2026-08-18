# Mandate 20 evidence - RDS PITR restore drill 2026-07-29

## Summary

RDS PITR restore drill đã được thực hiện cho production RDS `techx-tf3-postgres` bằng marker riêng trong schema `dr_drill`. Drill chứng minh restored DB có thể quay về mốc trước controlled corruption, trong khi production marker hiện tại vẫn ở trạng thái corrupted.

```text
Result: PASS for RDS PITR restore correctness
RPO target: <= 5 minutes
RPO evidence: T_restore is 41.248131 seconds after GOOD commit and restored marker was recovered
Probe data loss: 0 row
Infrastructure available elapsed: 23.83 minutes
RTO target: <= 45 minutes
End-to-end RTO verdict: pending successful-query timestamp addendum
Traffic impact: none observed / no app repoint performed
Production restore-overwrite: not performed
Drill DB: separate RDS instance, private, same DB subnet group
Video links: Drive folder and per-video links recorded in Video Evidence Index
```

Contract clarification added after evidence review:

```text
The 23.83-minute value ends when the RDS drill instance became available.
The GOOD marker was subsequently verified on the correct drill endpoint in video 4,
but that successful query does not have a recorded UTC timestamp in this evidence set.
Under contract v1, RTO ends at the successful restored-data query, so 23.83 minutes
must not be presented as the final end-to-end RTO until T_verify_good is supplied.
```

Normative measurement rules: [RPO/RTO contract and drill selection](../../docx_cdo02/mandate-20-rpo-rto-contract-and-drill-selection.md).

## Scope

This evidence covers the RDS/PostgreSQL PITR drill for Mandate 20.

It does not by itself claim full backup coverage for Valkey, MSK, DynamoDB, EBS, or IAM delete-authority separation. Those are documented separately as coverage/limitation items in:

- [docs/evidence/mandate-20/supporting-production-baseline-20260729.md](supporting-production-baseline-20260729.md)
- [docs/evidence/mandate-20/supporting-scope-gap-analysis.md](supporting-scope-gap-analysis.md)
- [docs/adr/0016-mandate-20-backup-restore-drill-cdo02.md](../../adr/0016-mandate-20-backup-restore-drill-cdo02.md)

## Actors And Environment

```text
Operator: Nguyễn Đỗ Hoàng Phúc / CDO02
AWS account: 197826770971
AWS caller: arn:aws:iam::197826770971:user/cdo-2-admin-team
Region: ap-southeast-1
Source DB: techx-tf3-postgres
Source DB name: otel
Source endpoint: techx-tf3-postgres.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com
Source DB subnet group: techx-tf3-postgres
Source security group: sg-025478cd9d0ae1f52
Restore target class: db.t4g.micro
Restore target public access: false
```

## Drill Identifiers

```text
Drill marker id: m20-rds-pitr-20260729-181943
Drill DB id: techx-tf3-postgres-drill-20260729-181943
Drill DB endpoint: techx-tf3-postgres-drill-20260729-181943.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com
Restore time: 2026-07-29T12:03:00Z
```

## Timeline

```text
T_good_commit_utc:
2026-07-29 12:02:18.751869 UTC

T_restore:
2026-07-29T12:03:00Z

T_corrupt_commit_utc:
2026-07-29 12:15:18.439171 UTC

RestoreStart:
2026-07-29T12:40:03Z

RestoreEnd:
2026-07-29T13:03:53Z

RTO measured:
23.83 minutes
```

Timeline proof:

```text
T_good_commit_utc < T_restore < T_corrupt_commit_utc
2026-07-29T12:02:18.751869Z < 2026-07-29T12:03:00Z < 2026-07-29T12:15:18.439171Z
```

RPO proof:

```text
RPO target: <= 5 minutes
GOOD commit to restore point delta: 41.248131 seconds
Restored DB returned GOOD_BEFORE_CORRUPTION for the marker
Probe data loss: 0 row
Verdict: PASS for the RDS drill scope
```

## Video Evidence Index

folder: [Drive folder](https://drive.google.com/drive/folders/1YDcvzsHzFiEpUJXlEGTD7mdm3MKT_926?usp=sharing)

| Video | Purpose | Status | Drive link |
|---|---|---|---|
| 1 | Create GOOD marker and establish pre-corruption restore point | captured | [Video 1](https://drive.google.com/file/d/1P_hZd6M3pE_DFKyKq8gbGEp_SCMs2hMH/view?usp=sharing) |
| 2 | Controlled corruption after `LatestRestorableTime >= T_restore` | captured | [Video 2](https://drive.google.com/file/d/1-QhUrofjCvp5rImVd-_TJH7Dbhkcruip/view?usp=sharing) |
| 3 | Restore request / RTO completion | captured partially; terminal context issue occurred after RTO | [Video 3](https://drive.google.com/file/d/168xyH6Z8iY6s3csFxJKhN5iQUKdAs2N0/view?usp=sharing) |
| 4 | Correct drill endpoint verification on separate port/session | captured | [Video 4](https://drive.google.com/file/d/1bU4Y8bP3ONEzHQcMQke8GYdfWVp01k7C/view?usp=sharing) |

Video 3 incident note:

```text
After RTO completed, the old local SSM session expired. A session was reopened to the production RDS endpoint on local port 15432, and a query returned CORRUPTED_AFTER_GOOD_TIME. This was expected for production and was not a restore failure.

Video 4 corrected the context by opening a separate SSM tunnel to the drill RDS endpoint on a different local port and verifying the restored data there.
```

## Production Marker After Corruption

Production query showed the marker in corrupted state:

```text
id: m20-rds-pitr-20260729-181943
expected_payload: CORRUPTED_AFTER_GOOD_TIME
created_at_utc: 2026-07-29 12:02:18.751869
updated_at_utc: 2026-07-29 12:15:18.439171
```

This is expected and useful evidence: production remained at the current corrupted marker state and was not overwritten by the restore.

## Restore Command Shape

The first restore attempt without a DB subnet group failed with `InvalidSubnet` because the VPC has no default subnet. The successful restore command used the production private DB subnet group and security group:

```powershell
aws rds restore-db-instance-to-point-in-time `
  --region ap-southeast-1 `
  --source-db-instance-identifier techx-tf3-postgres `
  --target-db-instance-identifier techx-tf3-postgres-drill-20260729-181943 `
  --restore-time 2026-07-29T12:03:00Z `
  --db-instance-class db.t4g.micro `
  --db-subnet-group-name techx-tf3-postgres `
  --vpc-security-group-ids sg-025478cd9d0ae1f52 `
  --db-parameter-group-name techx-tf3-postgres17 `
  --no-publicly-accessible
```

Rationale:

```text
The drill DB is restored as a separate private DB instance.
No production DB overwrite is performed.
No app secret, connection string, Kubernetes deployment, or GitOps manifest is changed.
```

## RTO Evidence

RPO:

```text
Target: <= 5 minutes
Evidence: T_restore was selected after GOOD commit and before corruption.
Delta from GOOD commit to T_restore: 41.248131 seconds.
Restored DB returned the GOOD marker.
Verdict: PASS for drill marker data.
```

RTO:

```text
RestoreStart=2026-07-29T12:40:03Z
InfrastructureAvailableAt=2026-07-29T13:03:53Z
Infrastructure available elapsed minutes=23.83
T_verify_good=not recorded
End-to-end RTO verdict=PENDING_TIMESTAMP_ADDENDUM
Target: <= 45 minutes
Restore correctness verdict: PASS
```

## Restored DB Verification

Verification must be read against the drill DB endpoint, not the production endpoint.

```text
Production local tunnel: 15432 -> techx-tf3-postgres.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com
Drill local tunnel: 15433 -> techx-tf3-postgres-drill-20260729-181943.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com
```

Expected restored DB query result:

```text
id: m20-rds-pitr-20260729-181943
expected_payload: GOOD_BEFORE_CORRUPTION
```

Observed in video 4:

```text
Restored drill DB returned GOOD_BEFORE_CORRUPTION for marker m20-rds-pitr-20260729-181943.
```

Verdict:

```text
PASS. Restored DB contains the pre-corruption marker state for T_restore.
```

## SLO / Revenue Path Safety

```text
No production restore overwrite.
No production endpoint replacement.
No secret rotation or app connection-string change.
No Kubernetes rollout/app restart.
No traffic repoint to drill DB.
Production RDS remained available.
Drill DB was private and isolated.
```

Impact assessment:

```text
Reliability/SLO impact: none expected from restore drill because it created an isolated DB instance.
Revenue path impact: none expected because browse/cart/checkout services were not repointed.
Cost impact: temporary RDS db.t4g.micro drill instance until cleanup.
```

## Cleanup

Cleanup status:

```text
Drill DB cleanup: pending or to be confirmed after evidence upload/review
Production marker cleanup: optional; default is keep marker as audit trail unless mentor asks cleanup
```

Safe cleanup commands after evidence is accepted:

```powershell
aws rds delete-db-instance `
  --region ap-southeast-1 `
  --db-instance-identifier techx-tf3-postgres-drill-20260729-181943 `
  --skip-final-snapshot

aws rds wait db-instance-deleted `
  --region ap-southeast-1 `
  --db-instance-identifier techx-tf3-postgres-drill-20260729-181943
```

If mentor asks to clean up the production marker, delete only the exact row:

```sql
DELETE FROM dr_drill.restore_probe
WHERE id = 'm20-rds-pitr-20260729-181943';
```

Do not run:

```sql
DROP SCHEMA dr_drill CASCADE;
```

## Final Verdict

```text
RDS PITR restore correctness: PASS
RPO target <= 5 minutes: PASS for drill marker, restored with 0 row data loss
Infrastructure available elapsed: 23.83 minutes
RTO target <= 45 minutes: PENDING successful-query timestamp addendum
Production traffic impact: none expected / no repoint performed
Evidence links: Drive folder and per-video links recorded above
Remaining Mandate 20 non-RDS items: see baseline/gap-analysis docs
```
