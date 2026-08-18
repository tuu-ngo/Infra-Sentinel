# Mandate 20 - Production baseline 2026-07-29

Baseline này khóa trạng thái production thật trước khi chạy RDS PITR restore drill Mandate 20. File này không phải template trống nữa; đây là baseline đã điền bằng các lệnh read-only trên AWS account `197826770971`.

Nguyên tắc:

- Chỉ thu thập inventory/evidence read-only.
- Không apply tay, không sửa production trực tiếp.
- Không claim Done chỉ từ baseline này; RDS drill result thật được ghi riêng trong [mandate-20-final-rds-pitr-evidence-20260729.md](mandate-20-final-rds-pitr-evidence-20260729.md).
- RDS là store dùng để chứng minh PITR drill chính. Các tầng còn lại được ghi theo dạng coverage hoặc limitation để không claim quá tay.

## Metadata

```text
Capture date: 2026-07-29 17:47 +07
Captured by: CDO02 / Nguyễn Đỗ Hoàng Phúc
AWS caller/account/region: arn:aws:iam::197826770971:user/cdo-2-admin-team / 197826770971 / ap-southeast-1
Git baseline: 74b8d8e / origin/main 74b8d8e
Evidence source: AWS CLI read-only output captured before drill
Related local/operator files:
- [docs/evidence/mandate-20/supporting-rds-pitr-preflight-20260729.md](supporting-rds-pitr-preflight-20260729.md)
- [docs/evidence/mandate-20/mandate-20-final-rds-pitr-evidence-20260729.md](mandate-20-final-rds-pitr-evidence-20260729.md)
```

## Scope

File này chỉ trả lời câu: trước khi chạy restore drill, production đang có backup/recovery baseline gì cho các stateful store trong scope Mandate 20.

File này không ghi nhận nội dung video và không thay thế drill result. Drill result thật đã được ghi riêng tại [docs/evidence/mandate-20/mandate-20-final-rds-pitr-evidence-20260729.md](mandate-20-final-rds-pitr-evidence-20260729.md).

## 1. RDS PostgreSQL

Mục tiêu: chứng minh store chính đã có nền backup/PITR trước buổi drill.

```text
DB identifier: techx-tf3-postgres
Endpoint: techx-tf3-postgres.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com
Status: available
Engine/version: postgres 17.9
Backup retention: 7 days
Latest restorable time: 2026-07-29T10:40:53Z
Encryption at rest: true
Deletion protection: true
Multi-AZ: true
Publicly accessible: false
Subnet group: techx-tf3-postgres
Security groups: sg-025478cd9d0ae1f52
RPO target: <= 5 phút, dựa trên RDS PITR/latest restorable time
RTO target: <= 45 phút cho drill restore sang DB instance tách biệt
Assessment: đủ điều kiện Go cho RDS PITR drill nếu SQL connectivity test pass.
```

Snapshot evidence:

```text
Automated snapshots observed: yes
Latest automated snapshot observed: rds:techx-tf3-postgres-2026-07-28-20-07, available, encrypted=true, size=20GiB
Manual snapshot observed: techx-tf3-postgres-pre-cleanup-20260721-2242, available, encrypted=true, size=20GiB
Snapshot cadence observed: automated daily snapshots are present across 2026-07-21 through 2026-07-28
```

Representative capture commands:

```powershell
aws rds describe-db-instances `
  --region ap-southeast-1 `
  --db-instance-identifier techx-tf3-postgres `
  --query "DBInstances[0].{Id:DBInstanceIdentifier,Status:DBInstanceStatus,Engine:Engine,EngineVersion:EngineVersion,Encrypted:StorageEncrypted,BackupRetention:BackupRetentionPeriod,LatestRestorableTime:LatestRestorableTime,DeletionProtection:DeletionProtection,MultiAZ:MultiAZ,Public:PubliclyAccessible,SubnetGroup:DBSubnetGroup.DBSubnetGroupName,VpcSecurityGroups:VpcSecurityGroups[].VpcSecurityGroupId,Endpoint:Endpoint.Address}" `
  --output json

aws rds describe-db-snapshots `
  --region ap-southeast-1 `
  --db-instance-identifier techx-tf3-postgres `
  --query "DBSnapshots[].{Id:DBSnapshotIdentifier,Type:SnapshotType,Status:Status,Created:SnapshotCreateTime,Encrypted:Encrypted,Size:AllocatedStorage}" `
  --output json
```

## 2. ElastiCache Valkey

Mục tiêu: chốt backup/recovery stance cho cart/session state. Đây là coverage phụ, không phải store dùng để chứng minh PITR chính.

```text
Replication group: techx-tf3-valkey
Status: available
Primary endpoint: master.techx-tf3-valkey.pkeslh.apse1.cache.amazonaws.com
Reader endpoint: replica.techx-tf3-valkey.pkeslh.apse1.cache.amazonaws.com
Snapshot retention / cadence: 3 days, snapshot window 14:00-15:00
Encryption at rest: true
Transit encryption: true
Auth token: enabled
Automatic failover: enabled
Multi-AZ: enabled
Recovery stance: restore from managed ElastiCache snapshot if cart-state restore is required.
RPO target: <= 24h if relying only on daily snapshot window; không claim RDS-like PITR.
RTO target: best-effort/manual restore, cần đo riêng nếu mentor yêu cầu cart-state drill.
Assessment: có managed snapshot baseline, nhưng không dùng để chứng minh PITR point-in-time như RDS.
```

Representative capture command:

```powershell
aws elasticache describe-replication-groups `
  --region ap-southeast-1 `
  --output json
```

## 3. MSK Kafka

Mục tiêu: chốt recovery path theo retention/replay, không gọi nhầm đây là PITR.

```text
Cluster name: techx-tf3-kafka
Cluster type: PROVISIONED
Status: ACTIVE
Kafka version: 3.9.x.kraft
Broker nodes: 3
Storage mode: LOCAL
Encryption at rest: KMS key arn:aws:kms:ap-southeast-1:197826770971:key/4be8eff8-ce84-4192-bb85-d7e118f06124
Transit encryption: TLS client-broker, in-cluster encryption=true
Recovery path: retention/replay/reconciliation, không phải point-in-time restore.
RPO target: phụ thuộc topic retention và producer/consumer replay window; không claim nếu chưa capture topic configs.
RTO target: phụ thuộc replay/reconciliation runbook; không claim trong RDS PITR drill.
Assessment: MSK đang active và encrypted; Mandate 20 RDS drill không chứng minh MSK data restore.
```

Representative capture commands:

```powershell
aws kafka list-clusters-v2 `
  --region ap-southeast-1 `
  --output json

aws kafka describe-cluster-v2 `
  --region ap-southeast-1 `
  --cluster-arn <techx-tf3-kafka-arn> `
  --output json
```

## 4. DynamoDB

Mục tiêu: xác nhận có bảng nào thuộc business flow hay chỉ là Terraform lock để exclude hợp lệ.

```text
Tables observed: techx-tf3-terraform-lock
Business-data table observed: none from current list-tables output
Continuous backups: ENABLED
Point-in-time recovery: DISABLED
Recovery stance: exclude from business-data restore scope because observed table is Terraform lock state, not browse/cart/checkout data.
RPO target: not applicable for business flow under current evidence.
RTO target: Terraform lock table is rebuildable by IaC/bootstrap if needed.
Assessment: không claim DynamoDB PITR for business data. Nếu sau này xuất hiện business table, phải capture PITR và restore stance riêng.
```

Representative capture commands:

```powershell
aws dynamodb list-tables `
  --region ap-southeast-1 `
  --output json

aws dynamodb describe-continuous-backups `
  --region ap-southeast-1 `
  --table-name techx-tf3-terraform-lock `
  --output json
```

## 5. EBS / Legacy Volumes

Mục tiêu: chốt rõ legacy artifact nào còn cần tính trong M20, artifact nào chỉ là pending M8/M18.

```text
Available legacy EBS volumes observed: 3
Total available legacy EBS size: 6GiB
Snapshots owned by account for these volumes: none observed
AWS Backup plans: none observed
DLM lifecycle policies: none observed
```

Observed available volumes:

| Volume | Size | Type | Encrypted | PVC tag | Current interpretation |
|---|---:|---|---|---|---|
| `vol-05d59d76c58a9d835` | 1GiB | gp2 | false | `valkey-cart` | legacy artifact, overlaps Mandate 8/18 |
| `vol-0a22f104910589929` | 3GiB | gp2 | false | `kafka-data` | legacy artifact, overlaps Mandate 18 / Kafka migration history |
| `vol-0f4b0c53ef8091d52` | 2GiB | gp2 | false | `postgresql-data` | legacy artifact, overlaps managed RDS migration history |

Assessment:

```text
Do not delete/detach these during Mandate 20. They are not the primary RDS PITR proof and may be evidence or pending cleanup for Mandate 8/18. Because no EC2 snapshots/AWS Backup/DLM plan were observed, do not claim EBS backup coverage unless mentor/client accepts them as excluded legacy artifacts.
```

Representative capture commands:

```powershell
aws ec2 describe-volumes `
  --region ap-southeast-1 `
  --filters "Name=status,Values=available" `
  --output json

aws ec2 describe-snapshots `
  --region ap-southeast-1 `
  --owner-ids self `
  --output json

aws backup list-backup-plans `
  --region ap-southeast-1 `
  --output json

aws dlm get-lifecycle-policies `
  --region ap-southeast-1 `
  --output json
```

## 6. GitOps / IaC State

Mục tiêu: chứng minh phần trạng thái cụm/hạ tầng có source-of-truth và recovery path.

```text
Git source of truth: GitHub origin/main
Current local commit: 74b8d8e
Current origin/main commit: 74b8d8e
Terraform backend bucket: techx-tf3-197826770971-tfstate
Terraform backend key: eks-baseline/terraform.tfstate
Terraform lock table: techx-tf3-terraform-lock
Terraform state encryption setting in backend: encrypt=true
State bucket versioning: Enabled
State bucket encryption: AES256
State bucket public access block: all four public access blocks enabled
State bucket Object Lock: not configured
Secret/config reference path: GitOps/IaC manifests in repo; runtime secret values are not printed in evidence.
RPO target: repo state bounded by Git history; Terraform state bounded by S3 versioning.
RTO target: manual rehydrate via GitOps/IaC after access restored; not measured in RDS PITR drill.
Assessment: Git/IaC source-of-truth exists; state bucket has versioning/encryption/public-block but no Object Lock.
```

Representative capture commands:

```powershell
git rev-parse --short HEAD
git rev-parse --short origin/main

aws s3api get-bucket-versioning `
  --bucket techx-tf3-197826770971-tfstate `
  --output json

aws s3api get-bucket-encryption `
  --bucket techx-tf3-197826770971-tfstate `
  --output json

aws s3api get-public-access-block `
  --bucket techx-tf3-197826770971-tfstate `
  --output json

aws s3api get-object-lock-configuration `
  --bucket techx-tf3-197826770971-tfstate `
  --output json
```

## 7. Backup Deletion Authority

Mục tiêu: khóa rõ phần CDO02 claim được và phần security/delete-authority posture. Vì account hiện có admin-wide principal, không claim tách quyền tuyệt đối nếu chưa có policy/SCP/permission boundary chứng minh.

| Principal / nhóm | Có được xóa backup không | Evidence / note |
|---|---|---|
| Read-only / reviewer | Không nên | policy target, không dùng để thao tác drill |
| CDO02 operator | Không nên xóa backup production | chỉ được xóa DB drill tạm sau khi đã capture evidence |
| CI plan role | Không nên có quyền xóa backup | cần policy evidence nếu claim enforcement |
| CI apply role | Chỉ qua PR/approval nếu có quyền | cần policy evidence nếu claim enforcement |
| Break-glass / owner | Có điều kiện | accepted risk / MFA / approval / CloudTrail |
| Admin-wide principal | Open risk | ghi accepted risk nếu chưa có SCP/permission boundary |

Assessment:

```text
Backup safety partially satisfied by managed encryption, deletion protection, state bucket versioning, and CloudTrail/account audit posture. Strong "operator cannot delete backup" separation is not proven by this baseline alone. Record as accepted risk or attach IAM/SCP evidence before claiming fully satisfied.
```

## 8. Overall Verdict

```text
Requirement 1 - all stores covered:
Partial but explicit. RDS is ready for PITR proof. Valkey has managed snapshots. MSK is replay/retention based. DynamoDB observed table is Terraform lock only. EBS legacy artifacts are not backed by observed snapshots/plans and should be excluded or accepted as limitation.

Requirement 2 - RPO/RTO and cadence:
RDS target is defined in drill evidence: RPO <= 5 minutes passed for the drill marker with 0 row data loss. The 23.83-minute value is infrastructure available elapsed; end-to-end RTO <= 45 minutes remains pending a successful-query timestamp addendum. Valkey contract is RPO <= 24 hours / RTO <= 60 minutes with 3-day daily snapshots. MSK uses the separate retention/replay contract; DynamoDB/EBS remain conditional exclusions unless separate evidence is added.

Requirement 3 - point-in-time restore proof:
Passed for RDS. Drill restored to 2026-07-29T12:03:00Z and restored DB returned GOOD_BEFORE_CORRUPTION.

Requirement 4 - tested restore drill:
Done for RDS. Evidence record: [mandate-20-final-rds-pitr-evidence-20260729.md](mandate-20-final-rds-pitr-evidence-20260729.md). Video links are recorded in the final evidence file.

Requirement 5 - backup safety:
Encryption and RDS deletion protection are present. Terraform state bucket versioning/encryption/public-block are present. Strong delete-authority separation is not proven; record accepted risk or attach IAM/SCP evidence.

Go / No-Go:
RDS PITR drill passed. Overall Mandate 20 Done still depends on accepted scope/limitations for non-RDS stores and delete-authority posture.
```
