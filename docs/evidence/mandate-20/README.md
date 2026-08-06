# Mandate 20 Evidence Index

Evidence index cho Mandate #20 Backup/Restore DR.

## File Cần Đọc Trước

| Loại | File | Vai trò |
|---|---|---|
| Final evidence | [mandate-20-final-evidence-20260731.md](mandate-20-final-evidence-20260731.md) | File chính để nộp Mandate 20: RDS drill, RPO/RTO, video links, Valkey/MSK status, backup delete-protection |
| Supporting evidence | [supporting-production-baseline-20260729.md](supporting-production-baseline-20260729.md) | Baseline production thật cho các data-tier/state trước drill |
| Supporting evidence | [supporting-rds-pitr-preflight-20260729.md](supporting-rds-pitr-preflight-20260729.md) | Preflight RDS/PITR read-only trước drill |
| Supporting evidence | [supporting-scope-gap-analysis.md](supporting-scope-gap-analysis.md) | Matrix đối chiếu directive với scope đã claim, limitation, và phần cần accepted risk |
| Template | [production-baseline-template.md](production-baseline-template.md) | Mẫu trống cho lần baseline sau; không phải evidence của drill 2026-07-29 |

## Design / Runbook

| File | Vai trò |
|---|---|
| [docs/adr/0016-mandate-20-backup-restore-drill-cdo02.md](../../adr/0016-mandate-20-backup-restore-drill-cdo02.md) | ADR RPO/RTO, backup strategy/cadence, retention, delete-authority posture, restore drill approach |
| [docs/runbooks/mandate-20-rds-pitr-drill.md](../../runbooks/mandate-20-rds-pitr-drill.md) | Runbook chạy RDS PITR drill an toàn, restore sang DB tách biệt |
| [docs/docx_cdo02/mandate-20-rds-pitr-restore-solution.md](../../docx_cdo02/mandate-20-rds-pitr-restore-solution.md) | Solution note cho CDO02/mentor review |

## Current Status

```text
CDO02 design/ADR: ready
RDS PITR drill evidence: completed, Drive links recorded
RDS RPO target <= 5 minutes: PASS for drill marker
RDS RTO target <= 45 minutes: PASS, measured 23.83 minutes
Current top-level status: see mandate-20-final-evidence-20260731.md
MSK/Kafka replay proof: BLOCKED by Kyverno governance, not yet replay-proven
Valkey restore target: PARTIAL, drill RG available, canary restore not proven
Backup delete-permission verdict: PARTIAL / REMEDIATION IN PROGRESS for Directive #20 YC#5
Backup delete-protection evidence: IAM deny evidence plus Terraform remediation for RDS AWS Backup Compliance Vault Lock
Mandate #20 overall: NOT YET; RDS drill passed, but MSK replay, Valkey canary restore, and hard backup delete-protection evidence still need completion or explicit acceptance
```

## Required evidence fields

Each drill record must include:

```text
Git baseline:
AWS caller/account/region:
RDS source inventory:
T_good_commit:
T_restore:
T_corrupt_commit:
DB drill identifier:
Drill marker id:
Restore start/end:
RTO measured:
Production corrupt query:
Restored DB GOOD query:
Cleanup result:
Witness mode: mentor/PM live hoặc recorded video
```

## Coverage matrix status

| Store / state | RPO/RTO status | Backup/retention status | Evidence |
|---|---|---|---|
| RDS PostgreSQL | Target set: RPO <= 5 phút, RTO <= 45 phút; RPO passed with 0 row data loss; measured RTO 23.83 phút | Automated backup/PITR 7 ngày, RDS PITR drill passed | [mandate-20-final-evidence-20260731.md](mandate-20-final-evidence-20260731.md) |
| ElastiCache Valkey | Restore target became available; canary restore not proven | Snapshot retention observed as 3 ngày; manual drill snapshot created; rerun only in SLO-green window | [mandate-20-final-evidence-20260731.md](mandate-20-final-evidence-20260731.md) |
| MSK Kafka | Replay/reconciliation target pending; do not call PITR | Managed MSK baseline captured; replay blocked by Kyverno exact-digest governance until approved client exists | [mandate-20-final-evidence-20260731.md](mandate-20-final-evidence-20260731.md) |
| DynamoDB lock | Pending exclusion/verdict | Exclude if Terraform lock only | Exclusion reason |
| EBS legacy | Pending M8/M18 decision | Do not use as M20 proof unless ownership is clarified | Pending/accepted limitation |
| GitOps/IaC state | Pending state restore target if claimed | Git/state/versioning/Object Lock evidence if claimed | Commit/state/backend evidence |
| IAM/KMS/delete permission | PARTIAL / REMEDIATION IN PROGRESS for YC#5 | IAM explicit deny applied to `AIO2-Admin` and `techx-corp-tf3-gha-terraform-apply`; Terraform now adds RDS AWS Backup Compliance Vault Lock, but it still needs CI apply, first recovery point evidence, and 3-day cooling-off; Valkey/MSK/state remain separate gaps | [mandate-20-final-evidence-20260731.md](mandate-20-final-evidence-20260731.md) |

## Current Recommendation

Sau feedback mentor, CDO02 nên:

- Dùng [mandate-20-final-evidence-20260731.md](mandate-20-final-evidence-20260731.md) làm file chính duy nhất khi gửi mentor/client về Mandate 20.
- Dùng các file `supporting-*` để giải thích baseline, preflight, scope và limitation.
- Không claim Mandate 20 full Done cho tới khi MSK replay, Valkey canary restore, và hard backup delete-protection được apply/capture đủ evidence hoặc mentor/PM accept limitation.
- Cleanup tài nguyên drill tạm sau khi mentor/PM xác nhận đã lưu đủ evidence.

Lý do: Mandate 20 chấm trên toàn bộ tầng dữ liệu và trạng thái cụm/hạ tầng, không chỉ riêng RDS PITR drill.
