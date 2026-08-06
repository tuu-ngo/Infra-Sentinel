# Mandate 20 final evidence - backup/restore DR

## Summary

Đây là file evidence chính để nộp Mandate 20. Link này được dùng làm entrypoint duy nhất cho mentor/client; các file `supporting-*` chỉ là phụ lục baseline/gap, không phải file final riêng.

RDS PITR restore drill đã được thực hiện cho production RDS `techx-tf3-postgres` bằng marker riêng trong schema `dr_drill`. Drill chứng minh restored DB có thể quay về mốc trước controlled corruption, trong khi production marker hiện tại vẫn ở trạng thái corrupted.

```text
Overall Mandate 20 status after mentor feedback: NOT YET FULL PASS
RDS PITR restore correctness: PASS
RPO target: <= 5 minutes
RPO evidence: T_restore is 41.248131 seconds after GOOD commit and restored marker was recovered
Probe data loss: 0 row
RTO measured: 23.83 minutes
RTO target: <= 45 minutes
Backup delete protection: PARTIAL / REMEDIATION IN PROGRESS for Directive #20 YC#5
RDS Vault Lock remediation: Terraform adds AWS Backup Compliance Vault Lock; pending CI apply, recovery point evidence, and 3-day cooling-off
Valkey/ElastiCache restore: PARTIAL, restore target created but canary not recovered
MSK/Kafka replay proof: BLOCKED by Kyverno approved-image governance
Traffic impact from RDS drill: none observed / no app repoint performed
Traffic impact from Valkey rescue attempt: cart/checkout/Grafana SLO dropped; drill stopped
Production restore-overwrite: not performed
Drill DB: separate RDS instance, private, same DB subnet group
Video links: Drive folder and per-video links recorded in Video Evidence Index
```

## Scope

This evidence file covers the current Mandate 20 submission state after mentor feedback:

- RDS PITR restore drill result.
- RPO/RTO proof and video links.
- Non-RDS money-path store status: Valkey and MSK.
- Backup delete-protection evidence for normal operator / CI apply paths.
- Current limitations that still need mentor acceptance or follow-up.

Supporting baseline/gap details remain documented in:

- [docs/evidence/mandate-20/supporting-production-baseline-20260729.md](supporting-production-baseline-20260729.md)
- [docs/evidence/mandate-20/supporting-scope-gap-analysis.md](supporting-scope-gap-analysis.md)
- [docs/evidence/mandate-20/mandate-20-backup-delete-protection-policy.json](mandate-20-backup-delete-protection-policy.json)
- [docs/adr/0016-mandate-20-backup-restore-drill-cdo02.md](../../adr/0016-mandate-20-backup-restore-drill-cdo02.md)

## Coverage Matrix

| Store / state | Current evidence in this file | Verdict | Remaining condition |
|---|---|---|---|
| RDS PostgreSQL `techx-tf3-postgres` | PITR drill restored GOOD marker to separate DB; RPO/RTO measured | PASS | None for RDS drill correctness |
| ElastiCache Valkey `techx-tf3-valkey` | Source baseline, automatic snapshots, manual snapshot, drill RG available | PARTIAL | Canary key was not recovered from drill Valkey; needs rerun in SLO-green window or explicit mentor acceptance |
| MSK Kafka `techx-tf3-kafka` | Managed cluster baseline; replay attempt blocked before pod creation | BLOCKED | Needs approved Kafka client through GitOps/CI or explicit mentor acceptance |
| DynamoDB lock table | Treated as Terraform lock/state support, not business money-path data | EXCLUSION NEEDS ACCEPTANCE | Confirm exclusion if mentor asks |
| GitOps/IaC state | Git/state backend strategy documented in supporting baseline | PARTIAL | Optional final capture of commit/state backend if mentor asks |
| Backup delete authority | IAM explicit deny applied to operator/admin group and CI apply role; Terraform remediation adds AWS Backup Compliance Vault Lock for the RDS recovery path | PARTIAL / REMEDIATION IN PROGRESS FOR YC#5 | Must merge/apply, capture vault lock/recovery-point evidence, and wait for AWS Backup compliance cooling-off; Valkey/MSK are not covered by AWS Backup in ap-southeast-1 |

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
RestoreEnd=2026-07-29T13:03:53Z
RTO measured minutes=23.83
Target: <= 45 minutes
Verdict: PASS
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

## Non-RDS Money-Path Store Status

Mandate 20 requires all stateful stores on the browse -> cart -> checkout path to be accounted for. The RDS drill above is the only restore-proven PITR drill in this submission. The non-RDS stores are documented below so the submission does not overclaim.

### ElastiCache Valkey

Source baseline:

```text
Replication group: techx-tf3-valkey
Status: available
Multi-AZ: enabled
Automatic failover: enabled
Transit encryption: enabled
At-rest encryption: enabled
Auth token: enabled
Snapshot retention: 3 days
Snapshot window: 14:00-15:00 UTC
Primary endpoint: master.techx-tf3-valkey.pkeslh.apse1.cache.amazonaws.com
```

Valkey rescue/drill identifiers:

```text
ProbeKey: m20:valkey:restore-probe:20260731-014800
Expected value: GOOD_BEFORE_RESTORE_TEST
Manual snapshot: m20-valkey-restore-probe-20260731-014800
Drill replication group: m20-valkey-drill-20260731-014800
Drill endpoint: master.m20-valkey-drill-20260731-014800.pkeslh.apse1.cache.amazonaws.com
```

Observed result:

```text
Production Valkey GET ProbeKey:
GOOD_BEFORE_RESTORE_TEST

Manual snapshot:
available

Drill replication group:
available

Drill Valkey EXISTS ProbeKey:
0
```

Timing and SLO incident:

```text
Snapshot time: 2026-07-30T19:20:19Z
Snapshot succeeded: 2026-07-30T19:27:30Z from techx-tf3-valkey-002
Drill restore succeeded: 2026-07-30T19:49:07Z
ElastiCache failover: techx-tf3-valkey-002 -> techx-tf3-valkey-001 at 2026-07-30T19:22:54Z
SLO guard: cart, checkout, and Grafana showed a drop during the manual snapshot / Valkey rescue attempt around video 2
```

Verdict:

```text
ElastiCache restore target creation succeeded.
Production traffic was not repointed to the drill Valkey.
The canary key was not recovered from the drill Valkey.
Valkey canary restore proof is NOT PROVEN.
The drill was stopped to protect SLO after cart/checkout/Grafana degradation and failover timing noise.
```

Current recovery check after stopping the drill:

```text
Namespace: techx-tf3
cart pods: 2/2 Running
checkout pods: 2/2 Running
grafana pod: Running
prometheus pod: Running
Observation source: kubectl get pods via private EKS tunnel on 2026-07-31
```

### MSK Kafka

Baseline:

```text
MSK cluster: techx-tf3-kafka
Status: ACTIVE
Broker count: 3
TLS/SASL/SCRAM: enabled
At-rest encryption: KMS
Bootstrap endpoint: available
```

Attempted replay evidence path:

```text
Create temporary Kafka client pod in namespace techx-tf3.
Use canary topic/event.
Replay with a fresh consumer group.
```

Actual blocker:

```text
admission webhook "validate.kyverno.svc-fail" denied the request
policy: allow-approved-external-image-digests
reason: External images must match the reviewed exact-digest catalog.
```

Verdict:

```text
MSK replay proof is BLOCKED by expected governance.
No temporary pod was created successfully.
No production order/money-path topic was touched.
No Kyverno policy bypass was attempted.
```

Next acceptable path:

```text
Use an approved Kafka client workload through GitOps/CI, or use an existing trusted workload with Kafka client capability.
Then produce a canary event to a canary topic and replay it with a fresh consumer group from retention.
```

## Backup Delete Protection

Mentor feedback called out that backups must be safe from normal operator deletion. The current remediation is IAM explicit deny, not Vault Lock/SCP/root-level immutability.

Current state:

```text
Audit trail S3 bucket:
- Object Lock: enabled
- Mode: COMPLIANCE
- Default retention: 14 days

Terraform state bucket:
- Versioning: enabled
- Encryption: enabled
- Object Lock: not configured

AWS Backup vault:
- Terraform remediation added for an RDS AWS Backup vault, backup plan, and Compliance Vault Lock
- Expected vault name after CI apply: techx-tf3-m20-vault
- Compliance cooling-off: 3 days, which is the AWS minimum
- Lock is not immutable until AWS reaches the computed lock date
- This covers supported AWS Backup recovery points for the RDS path only

AWS Organizations / SCP:
- AWSOrganizationsNotInUseException; SCP is not available from the current account state
```

AWS Backup scope note:

```text
Read-only AWS check in ap-southeast-1 shows AWS Backup supports RDS, EBS, DynamoDB,
S3, EKS, and several other resource types, but not ElastiCache/Valkey or MSK.

Therefore this remediation must not be presented as Valkey/MSK backup immutability.
Valkey/MSK still need a separate accepted strategy or separate restore/replay proof.
```

IAM guard applied live:

```text
Policy name: Mandate20BackupDeleteProtectionDeny
Operator/admin group: AIO2-Admin
CI apply role: techx-corp-tf3-gha-terraform-apply
CI plan role: unchanged; already implicitDeny through ReadOnlyAccess
Policy document: mandate-20-backup-delete-protection-policy.json
```

Policy intent:

```text
Deny destructive backup/snapshot delete APIs for RDS, ElastiCache, and AWS Backup.
Deny object/version deletion and retention bypass for Terraform state and audit trail buckets.
Avoid broad DB/cache destroy or Modify* deny in this first pass to avoid breaking unrelated Terraform maintenance.
```

Post-remediation IAM simulation:

| Principal | Delete action result | Evidence interpretation |
|---|---|---|
| `user/cdo-2-admin-team` via `AIO2-Admin` | `explicitDeny` | normal operator path cannot delete the reviewed direct backup/snapshot/state-object resources while the deny policy remains attached |
| `role/techx-corp-tf3-gha-terraform-apply` | `explicitDeny` | CI apply path cannot delete the reviewed direct backup/snapshot/state-object resources while the deny policy remains attached |
| `role/techx-corp-tf3-gha-terraform-plan` | `implicitDeny` | CI plan role remains read-only |

Reviewed actions:

```text
rds:DeleteDBSnapshot
rds:DeleteDBClusterSnapshot
elasticache:DeleteSnapshot
backup:DeleteRecoveryPoint
backup:DeleteBackupVault
backup:DeleteBackupPlan
backup:DeleteBackupVaultLockConfiguration
backup:PutBackupVaultLockConfiguration
backup:UpdateRecoveryPointLifecycle
s3:DeleteObject
s3:DeleteObjectVersion
s3:PutObjectRetention
s3:BypassGovernanceRetention
```

Known gaps found by follow-up review:

```text
1. The IAM deny is self-removable by the same admin-capable operator path.
   Simulated allowed actions include:
   - iam:DeleteGroupPolicy
   - iam:PutGroupPolicy
   - iam:RemoveUserFromGroup
   - iam:CreateUser
   - iam:AttachUserPolicy

2. Additional destructive paths remain open outside the current direct-delete deny:
   - rds:ModifyDBInstance
   - rds:DeleteDBInstance
   - elasticache:DeleteReplicationGroup
   - kms:ScheduleKeyDeletion

3. `rds:ModifyDBInstance` can reduce/disable backup retention, which can remove automated backup/PITR history.

4. `kms:ScheduleKeyDeletion` on the datastore KMS key can make encrypted recovery data unusable.
```

Updated remediation in this PR:

```text
Terraform file: infra/live/production/backup-vault-lock.tf
Resources added:
- aws_backup_vault.mandate20
- aws_backup_vault_lock_configuration.mandate20_compliance
- aws_backup_plan.mandate20_rds
- aws_backup_selection.mandate20_rds
- aws_iam_role.mandate20_aws_backup

Mode: Compliance Vault Lock
changeable_for_days: 3
min_retention_days: 7
max_retention_days: 35
backup recovery point retention: 14 days
Selected protected resource: production RDS instance ARN from module.datastores.rds_instance_arn
```

Evidence required after merge/apply:

```powershell
aws backup describe-backup-vault `
  --region ap-southeast-1 `
  --backup-vault-name techx-tf3-m20-vault

aws backup describe-backup-vault-lock-configuration `
  --region ap-southeast-1 `
  --backup-vault-name techx-tf3-m20-vault

aws backup list-backup-plans `
  --region ap-southeast-1

aws backup list-recovery-points-by-backup-vault `
  --region ap-southeast-1 `
  --backup-vault-name techx-tf3-m20-vault
```

Expected interpretation:

```text
Before CI apply: remediation is code-reviewed only.
After CI apply but before LockDate: Vault Lock is configured but still in cooling-off.
After LockDate: Compliance Vault Lock becomes immutable for retained recovery points.
```

Verdict:

```text
Backup delete-protection after this PR: PARTIAL / REMEDIATION IN PROGRESS for Directive #20 YC#5.
IAM explicit deny is useful as a first guard but remains self-removable by an admin-capable path.
The new Terraform Vault Lock remediation is the correct hard-control direction for RDS recovery points,
but it is not evidence-complete until CI applies it, a recovery point exists in the vault, and the
3-day compliance cooling-off reaches the LockDate.
This PR still must not claim YC#5 full pass yet.
```

Required next hardening:

```text
1. Merge/apply the RDS AWS Backup Compliance Vault Lock Terraform remediation.
2. Capture vault lock configuration, LockDate, backup plan, and first RDS recovery point evidence.
3. Wait until the 3-day compliance cooling-off expires before calling the RDS vault immutable.
4. Enable Object Lock for the Terraform state bucket if the team wants hard evidence for GitOps/IaC state artifacts.
5. Add or move remaining delete guardrails to a control plane that normal operators cannot self-remove.
6. Extend or accept risk for backup retention tampering, DB deletion, replication group deletion, and KMS key deletion.
```

## Cleanup

Cleanup status:

```text
RDS drill DB: techx-tf3-postgres-drill-20260729-181943, available, created 2026-07-29T12:43:10Z
Valkey drill RG: m20-valkey-drill-20260731-014800, available, created 2026-07-30T19:39:57Z
Cleanup decision: keep only until mentor/client has reviewed the evidence link, then delete to avoid unnecessary cost
Cleanup deadline: same day as evidence acceptance, or before final project close if mentor does not need another review window
Production marker cleanup: optional; default is keep marker as audit trail unless mentor asks cleanup
```

Safe RDS cleanup commands after evidence is accepted:

```powershell
aws rds delete-db-instance `
  --region ap-southeast-1 `
  --db-instance-identifier techx-tf3-postgres-drill-20260729-181943 `
  --skip-final-snapshot

aws rds wait db-instance-deleted `
  --region ap-southeast-1 `
  --db-instance-identifier techx-tf3-postgres-drill-20260729-181943
```

Safe Valkey drill cleanup command after evidence is accepted:

```powershell
aws elasticache delete-replication-group `
  --region ap-southeast-1 `
  --replication-group-id m20-valkey-drill-20260731-014800
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
Overall Mandate 20 status after mentor feedback: NOT YET FULL PASS
RDS PITR restore correctness: PASS
RPO target <= 5 minutes: PASS for drill marker, restored with 0 row data loss
RTO target <= 45 minutes: PASS, measured 23.83 minutes
Backup delete-protection: PARTIAL / REMEDIATION IN PROGRESS for Directive #20 YC#5
Valkey restore proof: PARTIAL / NOT PROVEN because canary key was not recovered from drill Valkey
MSK replay proof: BLOCKED by Kyverno approved-image governance before any pod/topic impact
Production traffic impact from RDS drill: none expected / no repoint performed
Production traffic impact from Valkey rescue: SLO drop observed, drill stopped
Evidence links: Drive folder and per-video links recorded above
Remaining path to full pass: mentor acceptance for Valkey/MSK limitations or rerun non-RDS proof through approved/SLO-green path; plus applied Vault Lock evidence and cooling-off completion for RDS backup immutability; plus state/Object Lock or accepted limitation for GitOps/IaC state
```
