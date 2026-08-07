# PM-161 — Mandate #20: Backup Security Execution Plan

| Field | Value |
|---|---|
| Jira | PM-161 (thuộc epic PM-158 — Mandate #20 DR Backup & Restore) |
| Phối hợp | PM-160 — Backup coverage, RPO/RTO và restore drill thật |
| Assignee | Tuấn Anh |
| Deadline | 27/07/2026 |
| AWS scope | Account `197826770971`, region `ap-southeast-1` |
| Accountable function | Security — CDO01 |
| Document state | `PLAN / EVIDENCE CONTRACT`; **không phải** bằng chứng PM-161 đã Done |

## 1. Mục tiêu và kết quả bắt buộc

PM-161 trực tiếp triển khai security controls cho backup, không chờ CDO02 chủ trì phần encryption/IAM. Mục tiêu là đóng ba rủi ro:

1. Mất bí mật: backup hoặc snapshot tồn tại nhưng không encrypted at rest.
2. Mất khả dụng do xoá nhầm/ransomware: operator thường hoặc workflow dùng chung có thể xoá backup.
3. Retention sai: thời hạn quá ngắn để restore, hoặc vô hạn gây chi phí và khó quản trị.

Evidence cuối phải chứng minh bằng CLI/runtime chain sau, không suy luận từ Terraform comment hay ảnh console:

```text
backup/snapshot thật đang tạo
  -> Encrypted = true
  -> KMS key hoặc encryption type xác định được
  -> operator delete nhận AccessDenied
  -> cleanup role riêng xoá test artifact thành công
  -> retention là số cụ thể và khớp contract PM-160
```

Trong tài liệu này, “PR 161” luôn là Jira PM-161. GitHub Pull Request triển khai sẽ có số riêng, không được mặc định là GitHub PR #161.

## 2. Trạng thái, dependency và gate

PM-161 **không bị block hoàn toàn**. Có thể làm song song ngay: inventory live, xác minh encryption, bật EBS encryption-by-default, thiết kế IAM deny/roles, bảo vệ KMS key, tạo isolated test artifact, scripts verify, ADR/runbook/evidence contract.

DoD retention chỉ có thể đóng sau khi PM-160 bàn giao contract sau:

| Contract field | Ví dụ | Owner |
|---|---|---|
| Exact production resources được backup | RDS identifier, EBS/PVC, DynamoDB table, ElastiCache | PM-160/CDO02 |
| RPO / RTO | `1h` / `2h` | PM-160 |
| Recovery horizon | `7d`, `14d`, `35d` | PM-160 |
| Backup frequency | hourly/daily/weekly | PM-160 |
| Restore drill result | restore duration và data loss quan sát được | PM-160 |
| Exclusions và lý do | Terraform lock table, cache tái tạo được | PM-160 + PM-161 review |
| Test/restore artifact dùng cho RDS delete demo | exact identifier/ARN và guardrails | PM-160 |

Trước khi contract này có đủ, trạng thái đúng là:

```text
Encryption + IAM complete, retention contract missing
=> IN PROGRESS — BLOCKED BY PM-160 RETENTION CONTRACT
```

Không tự chọn retention production rồi kết luận `Done`.

## 3. Baseline đã kiểm trong Git và điều cần xác minh live

| Resource | Git baseline | Live verdict hiện tại | PM-161 action |
|---|---|---|---|
| RDS PostgreSQL | `storage_encrypted=true`, retention `7`, deletion protection, final snapshot | `UNKNOWN` | Check DB/snapshot encryption, KMS ID, retention |
| ElastiCache Valkey | at-rest encryption, snapshot retention `3` | `UNKNOWN` | Include inventory; confirm scope/retention |
| EBS/PVC | EBS CSI addon exists | `UNKNOWN` | Inventory volume/snapshot/default encryption/lifecycle |
| DynamoDB application | Không thấy application table trong IaC đã kiểm | `UNKNOWN` | Inventory; conditional PITR/backup review |
| DynamoDB Terraform lock | Bootstrap state lock table | `UNKNOWN` | PM-160 quyết định exclude/protect |
| AWS Backup vault | Chưa thấy IaC | `UNKNOWN` | Inventory vault, plans, recovery points, lock/policy |
| Terraform GitHub apply role | `AdministratorAccess` attached | bypass risk | Explicit deny destructive backup/KMS actions |

`UNKNOWN != PASS`. Repo không phải source duy nhất của IAM hoặc AWS inventory; mọi verdict closure phải dựa trên live account/region đúng scope.

RDS dùng AWS-managed key là encryption hợp lệ nếu DB `StorageEncrypted=true` và `KmsKeyId` xác định được. Không migration RDS sang CMK chỉ để đẹp tài liệu: nếu `terraform plan` tạo replacement/destroy, dừng PM-161 path và tách migration có snapshot copy/restore drill với PM-160.

## 4. Scope matrix và boundary

Mỗi dòng sau phải nhận một verdict cuối: `IN_SCOPE`, `EXCLUDED_WITH_REASON`, `NOT_PRESENT`, hoặc `BLOCKED`; không được để trống.

| Resource | Repo evidence | Backup security action |
|---|---|---|
| RDS automated backup; manual/final/test snapshot | Có | Encryption, IAM delete separation, retention contract |
| ElastiCache snapshot | Có | Encryption, IAM, retention contract hoặc exclusion chính thức |
| EBS volume/snapshot in account/region | Partial | Default encryption, old-resource inventory, lifecycle/retention |
| DynamoDB application table | Chưa xác minh | SSE, PITR/on-demand/AWS Backup, delete controls nếu in scope |
| AWS Backup vault/recovery point | Chưa xác minh | Vault KMS, policy, lifecycle, lock decision nếu in scope |
| KMS key bảo vệ backup | Conditional | Separate key administration/destructive key controls |
| IAM human/CI/apply path | Có một phần IaC | Audit policy/trust/role chaining/OIDC, deny bypass |

Out of scope: PM-160 backup-coverage/RPO/RTO design và production restore drill; MSK backup khi chưa có mechanism xác nhận; production backup deletion để demo; RDS CMK replacement chưa review; immediate Compliance Vault Lock; automatic deletion lịch sử chưa inventory; application/flagd/HPA/Karpenter/datastore cutover.

## 5. Design decisions

### D1 — Encryption and KMS

- AWS-managed `aws/rds`/service key được chấp nhận cho existing RDS khi live check PASS.
- Chỉ tạo dedicated CMK `alias/techx-tf3-backup` khi PM-160 sử dụng AWS Backup, encrypted snapshot copy, hoặc customer-managed control thực sự cần thiết.
- Backup CMK có rotation, deletion window tối thiểu 30 ngày, service-use least privilege, restore use/decrypt path, và role `tf3-backup-kms-admin` riêng.
- Không tái sử dụng datastore CMK đang dành cho MSK/SCRAM: tách blast radius và key lifecycle.
- EBS encryption-by-default phải được bật. Existing unencrypted volume/snapshot không thể flip tại chỗ; remediation là snapshot, encrypted copy, restored encrypted volume, consistency/restore verification, approved cutover, rồi mới xử lý artifact cũ.

### D2 — IAM separation / fail closed

| Persona | Describe | Create backup | Restore | Change retention | Delete test | Delete prod | Manage KMS |
|---|---:|---:|---:|---:|---:|---:|---:|
| `tf3-production-operator` | Yes | Limited/request | Limited/request | No | No | No | No |
| Backup automation | Yes | Yes | No | Fixed IaC only | Lifecycle only | No | Use only |
| `tf3-backup-test-cleanup` | Yes | No | No | No | tagged/exact test ARN only | No | No |
| `tf3-backup-breakglass-delete` | Yes | No | No | No | Yes | approved scope only | No |
| `tf3-backup-kms-admin` | Describe | No | No | No | No | No | Key admin |
| Terraform plan | Read | No | No | No | No | No | No |
| Terraform apply | reviewed IaC | Config only | Config restore only | reviewed IaC | no direct delete | denied direct delete | limited |

Routine human principals and shared operator roles receive explicit deny at least for:

```json
{
  "Effect": "Deny",
  "Action": [
    "rds:DeleteDBSnapshot", "rds:DeleteDBClusterSnapshot",
    "rds:DeleteDBInstanceAutomatedBackup", "rds:DeleteDBClusterAutomatedBackup",
    "ec2:DeleteSnapshot", "ec2:ModifySnapshotAttribute",
    "dynamodb:DeleteBackup", "dynamodb:UpdateContinuousBackups",
    "elasticache:DeleteSnapshot",
    "backup:DeleteRecoveryPoint", "backup:UpdateRecoveryPointLifecycle",
    "backup:DeleteBackupVault", "backup:DeleteBackupPlan", "backup:UpdateBackupPlan",
    "backup:DeleteBackupVaultAccessPolicy", "backup:DeleteBackupVaultLockConfiguration",
    "kms:DisableKey", "kms:ScheduleKeyDeletion"
  ],
  "Resource": "*"
}
```

The exact resource/action condition must be checked with IAM Access Analyzer and live resource types. A deny on the operator alone is insufficient: the current Terraform apply role is an AdministratorAccess bypass. Short-term required path is explicit deny on the apply role too; least-privilege redesign can be a follow-up, but direct backup deletion must fail closed now.

Test cleanup must only delete `Mandate20Test=true`, `Owner=PM-161`, and an explicit `ExpiresAt`. If a delete API lacks tag condition support, issue a short-lived policy/session with exact test ARN; never use unrestricted `Resource:"*"` for the positive demo. Break-glass requires approved trust, MFA or a proven protected-environment equivalent, short session, ticket/reason where supported, and CloudTrail evidence. It is not attached to an admin team by default.

If AWS Backup is in scope, add a vault resource policy deny for delete/lifecycle mutation except exact break-glass principal; do not rely only on identity policy.

### D3 — Retention and Vault Lock

Current `7` day RDS and `3` day ElastiCache values are baseline only. Do not reduce them before PM-160 approval. Production expiry should be lifecycle-driven, not daily human deletion.

All manual artifacts must have these tags: `BackupClass`, `Owner`, `CreatedBy`, `ExpiresAt`, `RPOClass`, `Mandate=20`. A manual snapshot without `ExpiresAt` is `NON_COMPLIANT_RETENTION`; initial enforcement reports/dry-runs rather than deleting historical artifacts.

Use vault policy/IAM separation first. Governance Vault Lock may be considered only after the retention contract exists. Do not enable Compliance Vault Lock before restore drill, retention/cost approval, approved grace period/rollback understanding, and a dedicated signed ADR.

## 6. Execution phases

### Phase 0 — Contract request and coordination

Request the seven PM-160 fields in section 2. Record the response in the approved retention contract. Coordinate snapshot/restore testing with PM-155 performance benchmark to avoid noise; do not proceed if benchmark is running.

### Phase 1 — Live baseline inventory

Preflight fails unless caller account is `197826770971`, region is `ap-southeast-1`, and `aws`, `jq`, `terraform`, `python3` are available. Capture caller ARN, UTC timestamp, Git SHA, Terraform workspace/state serial.

Inventory commands include:

```bash
aws rds describe-db-instances
aws rds describe-db-snapshots --snapshot-type manual
aws rds describe-db-instance-automated-backups
aws elasticache describe-replication-groups
aws elasticache describe-snapshots
aws ec2 get-ebs-encryption-by-default
aws ec2 get-ebs-default-kms-key-id
aws ec2 describe-volumes
aws ec2 describe-snapshots --owner-ids self
aws dynamodb list-tables && aws dynamodb list-backups
aws backup list-backup-vaults && aws backup list-backup-plans
aws iam get-account-authorization-details
```

Assertions: in-scope RDS has `StorageEncrypted=true`, nonempty `KmsKeyId`, `BackupRetentionPeriod>0`, deletion protection; manual snapshot has `Encrypted=true` and KMS ID. ElastiCache has at-rest encryption and approved retention. EBS classification covers encrypted state/key/attachment/tags/creation/test-orphan. Each in-scope DynamoDB table gets `describe-table` and `describe-continuous-backups`. For each backup vault, capture encryption key, lock state, access policy, recovery-point lifecycle and expiry.

IAM audit must map every principal, policy source, trust/assume path, human/CI/service classification, risk and remediation for delete/retention/encryption/KMS destructive actions. Include group/user/role policies, permission sets, inline policies, role chaining, GitHub Actions and service roles.

### Phase 2 — Encryption guardrails

Implement EBS default encryption in production IaC. Use a dedicated backup CMK only when D1 conditions are met. Run and preserve `terraform plan`; any RDS replacement/destroy is a stop condition, not a merge candidate. For DynamoDB application tables, check SSE and enable PITR/backup only after PM-160 scope confirms it. Verify Valkey snapshot existence and final retention after contract.

### Phase 3 — IAM implementation

Implement the operator/apply explicit denies, test-cleanup role, break-glass role, backup KMS admin separation, and conditional vault resource policy. Validate policy syntax and Access Analyzer findings before live tests. Do not let a policy change expand cleanup beyond isolated artifacts.

### Phase 4 — Retention implementation

Only after PM-160 contract, apply exact RDS/ElastiCache/AWS Backup/DynamoDB values plus manual snapshot expiry controls. The machine-readable contract is:

`docs/evidence/mandate-20/pm-161/retention/approved-retention.json`

```json
{
  "schemaVersion": 1,
  "approvedBy": ["PM-160-owner", "PM-161-owner"],
  "approvedAt": "UTC timestamp",
  "resources": [{
    "type": "RDS",
    "resource": "identifier-or-tag-selector",
    "rpo": "1h",
    "rto": "2h",
    "backupFrequency": "hourly/daily",
    "retentionDays": 0,
    "restoreDrillEvidence": "path-or-url",
    "costOwner": "CDO02"
  }]
}
```

`retentionDays` must be positive. The validator fails for missing in-scope resource, zero/null/unlimited/forever retention, frequency below RPO, horizon mismatch, live RDS/ElastiCache/AWS Backup mismatch, or manual snapshot without valid expiry/cleanup path.

### Phase 5 — Isolated deletion-separation verification

EBS is the mandatory independent test: create a small encrypted test volume and snapshot, tag it, verify encryption/KMS, then test negative/positive delete. Prefer PM-160 restore-test DB for RDS; never snapshot a production DB merely to demo permission. DynamoDB/AWS Backup tests are conditional on scope and use dedicated test table/vault only.

Negative test under `tf3-production-operator` must prove all of: expected caller ARN, artifact exists, non-zero exit, `AccessDenied` caused by IAM deny, and artifact remains. It is invalid if failure is wrong region/ID, expired credentials, not found, dependency error, malformed input or vault-lock-only denial.

Positive test under `tf3-backup-test-cleanup` must prove expected caller ARN, delete success, artifact absent after waiter/describe, and matching CloudTrail event. Cleanup failure never justifies expanding operator permissions. IAM simulation is a pre-check only; it does not replace the live test.

## 7. Repository deliverables

```text
docs/
  adr/<next>-mandate-20-backup-encryption-delete-separation.md
  docx_cdo01/plan/mandate-20/PM-161-backup-security-execution-plan.md
  evidence/mandate-20/pm-161/{README.md,baseline,encryption,iam,retention,deletion-test,final}
  runbooks/{mandate-20-backup-delete-breakglass.md,mandate-20-backup-security-verify.md}
infra/live/production/{backup-security.tf,iam-backup-protection.tf,production.auto.tfvars}
scripts/security/mandate20/{inventory-backups.sh,verify-encryption.sh,verify-retention.py,create-test-artifacts.sh,verify-delete-separation.sh,cleanup-test-artifacts.sh}
```

Create `infra/modules/backup-security/` only when implementation scope is sufficiently large; do not introduce a module merely to increase file count.

Evidence must be sanitized: never commit access keys, session tokens, secret values, database content or Terraform sensitive values. Preserve principal/resource/KMS ARNs and CloudTrail event IDs. Required evidence includes raw baseline output, encryption summary, IAM matrix/policies/validation, approved and live retention summaries, negative/positive deletion test outputs, CloudTrail events, final no-replacement plan, closure checklist and mentor-demo log.

## 8. PR and rollback strategy

Use reversible PRs/commits in this order:

1. Audit/contract: scripts, evidence structure, retention schema, ADR draft; no production mutation.
2. Encryption guardrails: EBS encryption default, conditional backup CMK, outputs and no-replacement plan; no volume/snapshot migration.
3. IAM separation: deny, cleanup, break-glass, KMS admin, conditional vault policy.
4. Retention: only after PM-160 approved contract.
5. Verification/evidence: isolated artifact, deny/allow tests, CloudTrail, final report.

If a single PR is mandated, keep commits independently revertible and run destructive verification only after merge, outside PR CI. Rollback never routinely disables/schedules deletion of KMS keys or deletes aliases. If IAM deny blocks valid work, find exact action/resource and grant it to automation/dedicated role—not to operator. If a backup CMK causes provisioning failure, stop new provisioning and repair policy/grants before considering any key change.

## 9. Stop conditions and closure definition

Stop immediately on: wrong account/region; RDS production replacement/destroy plan; unencrypted in-scope production artifact without tracked migration; operator delete success; cleanup deleting outside its test allow-list; Terraform apply bypass remaining; operator KMS key admin; unapproved retention apply; Compliance Vault Lock outside approval; production artifact used for demo; invalid AccessDenied reason; missing decrypt permission in restore path; scope change after inventory; PM-155 benchmark interference.

PM-161 reaches `Done` only when all of these are evidenced: PM-160 exact scope/RPO/RTO/horizon/frequency and restore evidence; completed live inventory; encrypted RDS/Valkey/EBS and all relevant snapshots; resolved EBS exceptions; DynamoDB/AWS Backup verdicts; explicit operator and apply-role delete deny; destructive KMS separation; scoped cleanup and approved break-glass; valid operator denial and cleanup success with CloudTrail; positive numeric retention validated against PM-160; usable KMS restore path; no production deletion; no RDS replacement; signed ADR; sanitized committed evidence; mentor rehearsal pass; no unowned Critical/High gaps.

## 10. Comment for PM/CDO02

> PM-161 will directly implement Mandate 20 Security controls: encryption-at-rest verification/remediation; explicit IAM deny for routine operator and Terraform apply path; dedicated test-cleanup/break-glass/KMS roles; retention enforcement; and live deletion-separation verification. PM-161 can proceed with inventory, encryption and IAM now. Final retention and DoD require PM-160 to confirm exact resource coverage, RPO, RTO, recovery horizon, frequency, restore-drill evidence, exclusions/reason and safe RDS test restore resource. Current repo values—RDS 7 days and ElastiCache 3 days—are baseline only, not final policy. Retention will not be reduced and Compliance Vault Lock will not be enabled before that contract.

Proposed titles:

- `docs(mandate-20): add PM-161 backup security execution plan`
- `feat(mandate-20): enforce backup encryption and delete-role separation`
- `feat(mandate-20): apply PM-160 backup retention contract`
