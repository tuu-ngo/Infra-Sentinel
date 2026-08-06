# ADR 0016 - Mandate #20: RDS PITR restore drill for CDO02 backup/recovery proof

**Ngày:** 2026-07-28  
**Người quyết định (ký):** Nguyễn Đỗ Hoàng Phúc - CDO02 (Reliability + Operations)  
**Directive:** `MANDATE-20-dr-backup-restore.md` - Backup/Restore DR  
**Trạng thái:** RDS PITR drill executed - RDS restore correctness passed; backup delete-protection remediation in progress with RDS AWS Backup Compliance Vault Lock; overall Mandate #20 còn phụ thuộc accepted scope/limitation cho non-RDS stores và hard backup-delete protection evidence
**Tham chiếu:** [docs/docx_cdo02/mandate-20-rds-pitr-restore-solution.md](../docx_cdo02/mandate-20-rds-pitr-restore-solution.md)

## Bối cảnh

Mandate #20 yêu cầu chứng minh hệ thống khôi phục được dữ liệu sau mất/hỏng dữ liệu, bằng một restore drill thật, có RPO/RTO đo được. Yêu cầu không được tính là đạt chỉ vì đã bật backup.

TF3 hiện đã migrate datastore chính lên managed service theo Mandate #8:

- RDS PostgreSQL `techx-tf3-postgres`
- ElastiCache Valkey `techx-tf3-valkey`
- MSK Kafka `techx-tf3-kafka`

RDS hiện là ứng viên tốt nhất để làm proof chính vì có Point-in-Time Restore native, có thể restore về mốc trước lỗi sang DB instance tách biệt, rồi kiểm chứng bằng SQL mà không đổi traffic production.

## Quyết định

CDO02 chọn **RDS PostgreSQL `techx-tf3-postgres` làm restore drill chính** cho phần Reliability/Operations của Mandate #20.

Drill sẽ chạy theo mô hình:

1. Tạo marker dữ liệu tốt với id duy nhất theo lần drill trong schema probe riêng `dr_drill` trên production RDS.
2. Ghi lại `T_good_commit`.
3. Gây hỏng có kiểm soát chỉ trên row probe, chuyển payload sang `CORRUPTED_AFTER_GOOD_TIME`.
4. Chọn `T_restore` nằm sau `T_good_commit` và trước `T_corrupt_commit`.
5. Restore RDS về `T_restore` sang DB instance tạm/tách biệt.
6. Query DB restored, chứng minh marker quay lại `GOOD_BEFORE_CORRUPTION`.
7. Đo RTO từ lúc bắt đầu restore tới lúc query restored DB thành công.
8. Lưu raw evidence và cleanup DB drill sau khi mentor/PM xác nhận đủ.

Target trước drill:

```text
RDS RPO target: <= 5 phút
RDS RTO target: <= 45 phút
Expected data loss in probe: 0 row
```

Kết quả drill đã ghi nhận ngày 2026-07-29:

```text
Evidence record: [docs/evidence/mandate-20/mandate-20-final-evidence-20260731.md](../evidence/mandate-20/mandate-20-final-evidence-20260731.md)
Drill marker id: m20-rds-pitr-20260729-181943
T_good_commit_utc: 2026-07-29T12:02:18.751869Z
T_restore: 2026-07-29T12:03:00Z
T_corrupt_commit_utc: 2026-07-29T12:15:18.439171Z
Restored DB result: GOOD_BEFORE_CORRUPTION
RPO evidence: T_restore cách T_good_commit_utc 41.248131 giây; probe data loss 0 row
RTO measured: 23.83 phút
RTO target: <= 45 phút
RDS PITR restore correctness: PASS
```

## Ranh giới an toàn

Trong drill CDO02 không được:

- Restore đè lên production RDS.
- Đổi `DB_CONNECTION_STRING` hoặc secret production.
- Repoint app sang DB drill.
- Rebuild image hoặc đổi Helm values.
- Chạy `DROP`, `DELETE`, `TRUNCATE`, `UPDATE` trên bảng khách hàng.
- Cleanup DB drill trước khi evidence được mentor/PM xác nhận.
- Drop schema/table probe trên production trong cleanup thường lệ.

DB drill chỉ là tài nguyên tạm để chứng minh restore, ví dụ:

```text
techx-tf3-postgres-drill-YYYYMMDD-HHMMSS
```

## Phạm vi CDO02 claim

CDO02 claim các phần sau:

- RPO/RTO vận hành cho RDS restore drill.
- Runbook restore an toàn, không ảnh hưởng production traffic.
- Evidence SQL: GOOD -> CORRUPTED -> RESTORED GOOD.
- RTO measured.
- Cleanup DB drill; production marker cleanup nếu có thì chỉ xóa đúng marker id của lần drill, hoặc giữ lại làm audit trail.
- Coverage matrix cho store khác: ElastiCache, MSK, DynamoDB lock, EBS legacy, GitOps/IaC state.

CDO02 ghi nhận IAM explicit deny cho direct backup/snapshot/object delete API trên normal operator/CI apply path, nhưng không claim YC#5 pass. Follow-up review chỉ ra guard hiện tại tự gỡ được bởi admin-capable principal và chưa phủ các đường phá backup qua modify/delete/KMS. ADR này bổ sung hướng hard guard cho RDS bằng AWS Backup Compliance Vault Lock trong Terraform; phần này chỉ được claim immutable sau khi CI apply, có recovery point trong vault, và hết 3 ngày cooling-off.

## Security / delete-authority posture

Phần Security/delete-authority đã được remediated một phần cho normal operating paths:

- Encryption/KMS posture của datastore và backup/snapshot.
- Normal operator group `AIO2-Admin` bị IAM explicit deny với direct delete API đã review, nhưng vẫn có quyền IAM đủ để tự gỡ policy/đổi group/tạo admin path khác.
- CI apply role `techx-corp-tf3-gha-terraform-apply` bị IAM explicit deny với direct delete API đã review.
- CI plan role `techx-corp-tf3-gha-terraform-plan` vốn là read-only và simulation trả `implicitDeny`.
- Break-glass/account-owner path vẫn tồn tại và phải được xem là quyền khẩn cấp có audit/approval.
- Retention/security guardrail.

Trong account hiện tại không có AWS Organizations/SCP, nên ADR này **không claim chống xoá backup tuyệt đối ở cấp root/organization** cho toàn bộ scope. Mức claim hiện tại:

- Direct delete API đã bị chặn bằng IAM explicit deny cho normal operator/CI apply path, nhưng guard này self-removable.
- Terraform thêm AWS Backup Compliance Vault Lock cho RDS recovery points: `techx-tf3-m20-vault`, `changeable_for_days = 3`, retention 14 ngày.
- AWS Backup ở `ap-southeast-1` không cover ElastiCache/Valkey hoặc MSK, nên Valkey/MSK không được claim immutable nhờ vault này.
- YC#5 vẫn partial cho tới khi có apply evidence, LockDate/cooling-off evidence, state Object Lock hoặc accepted limitation cho GitOps/IaC state, và quyết định cuối cho Valkey/MSK.

## Mandate #20 data-tier commitments

ADR này ghi cam kết vận hành theo từng tầng dữ liệu để khớp yêu cầu Mandate #20. RDS đã có drill evidence thật; các store/state còn lại giữ ở dạng coverage/limitation để không overclaim.

| Tầng dữ liệu / state | Vai trò trong hệ thống | RPO target | RTO target | Backup / recovery strategy | Cadence / retention | CDO02 claim | Security / delete-permission verdict |
|---|---|---|---|---|---|---|---|
| RDS PostgreSQL `techx-tf3-postgres` | Store chính cho catalog/reviews/accounting/order data | `<= 5 phút` theo PITR window | `<= 45 phút` cho restore drill; measured `23.83 phút` | RDS automated backup + PITR; restore về `T_restore` sang DB drill tách biệt; AWS Backup plan + Compliance Vault Lock remediation | Automated backup retention 7 ngày; AWS Backup recovery point retention 14 ngày trong locked vault | **Claim chính của CDO02 đã pass RDS drill**; Vault Lock remediation pending apply/cooling-off; evidence [mandate-20-final-evidence-20260731.md](../evidence/mandate-20/mandate-20-final-evidence-20260731.md) | IAM deny chặn direct snapshot delete nhưng self-removable; Vault Lock là hard guard cho RDS recovery points sau LockDate |
| ElastiCache Valkey `techx-tf3-valkey` | Cart/session cache trên luồng browse -> cart -> checkout | Target theo snapshot window; nếu không claim restore cart, ghi accepted cart-state strategy | Target theo restore snapshot hoặc accepted recovery strategy | ElastiCache snapshot/restore hoặc accepted limitation: cart state là soft-state, không dùng làm PITR proof chính | Snapshot retention quan sát: 3 ngày | Restore target tạo được nhưng canary chưa proven; incident SLO/failover được ghi trong rescue status | Normal operator/CI apply `elasticache:DeleteSnapshot` bị IAM explicit deny |
| MSK Kafka `techx-tf3-kafka` | Order event stream cho checkout -> accounting/fraud | Target: `0 acknowledged order lost` trong retention window nếu producer/consumer replay đúng | Target theo consumer replay/reconciliation, cần evidence sau drill/record riêng | MSK retention/replay; không gọi là PITR backup | Topic retention cần được capture trong evidence; prior docs ghi 168h | CDO02 ghi replay/reconciliation strategy, không dùng làm PITR proof chính | Cần ghi KMS/IAM/delete topic/config destructive control nếu claim |
| DynamoDB `techx-tf3-terraform-lock` | Terraform lock table, không phải dữ liệu khách hàng | Excluded nếu chỉ là lock tái tạo được | Rebuild/recreate lock table nếu mất | Exclusion with reason, không dùng làm data restore proof | Không yêu cầu retention khách hàng nếu exclude | CDO02 claim exclude nếu team xác nhận chỉ là lock | Nếu team muốn protect, cần xác nhận PITR/IAM |
| EBS/PVC legacy volumes | Legacy artifacts từ pre-managed datastore / Mandate #8/#18 | Không claim RPO/RTO cho production data | Không claim restore path trong M20 drill | Không dùng làm backup proof chính; pending Mandate #8 acceptance / Mandate #18 cleanup | Không dùng làm retention proof nếu legacy/available | CDO02 ghi pending/accepted limitation để không gạt M8/M18 | Nếu giữ làm artifact, cần encryption/delete policy verdict |
| GitOps/IaC state | Manifest, config, Terraform state/source of truth | Git RPO: last pushed commit; Terraform state RPO phụ thuộc backend versioning | Target restore/reconcile phải được đo trong DR/state runbook nếu claim | Git history + Terraform state backend/versioning/Object Lock nếu có | Retention/versioning phải capture từ backend thực tế | CDO02 claim GitOps source-of-truth process; state bucket versioning captured | State/audit object delete and retention bypass bị IAM explicit deny cho normal operator/CI apply path; state bucket chưa có Object Lock |

## Backup deletion authority

Mandate #20 yêu cầu ghi rõ **ai được xóa backup**. ADR này ghi policy mong muốn, phần đã vận hành trong drill, và chỗ cần evidence enforcement hoặc accepted risk.

| Principal / nhóm | Quyền xóa backup mong muốn | Trạng thái trong ADR này | Evidence cần có |
|---|---|---|---|
| Read-only / reviewer / mentor viewer | Không được xóa | Policy target | IAM policy/console role evidence nếu claim enforcement |
| CDO02 operator chạy drill | Không được xóa backup production; chỉ được tạo/xóa DB drill tạm sau approval | CDO02 operating rule | Runbook/evidence cleanup chỉ áp dụng DB drill identifier |
| CI Terraform plan role | Không được xóa backup; chỉ plan/read | Policy target | CI/IAM evidence nếu claim enforcement |
| CI Terraform apply role | Direct delete API bị deny; YC#5 chưa pass đầy đủ | Partial | IAM explicit deny policy `Mandate20BackupDeleteProtectionDeny`; cần hard guard không tự gỡ được |
| Break-glass / account owner | Có thể xóa trong tình huống khẩn cấp có ticket/MFA/owner approval | Accepted operational reality nếu account còn admin rộng | CloudTrail/audit process + named owner từ PM/account owner |
| Unknown/admin-wide principals | Không claim đã chặn tuyệt đối nếu chưa có SCP/permission boundary | **Residual risk** | Break-glass/account-owner governance |

Kết luận: CDO02 không nên claim delete-protection pass cho YC#5 ngay tại thời điểm PR. Mandate #20 overall chưa nên claim Done nếu Valkey/MSK non-RDS proof và hard backup-delete protection hoặc accepted limitation chưa được PM/mentor chấp nhận.

## Coverage matrix

| Store / state | Quyết định CDO02 | Điều kiện evidence |
|---|---|---|
| RDS PostgreSQL | Drill chính bằng PITR | Restored DB trả marker GOOD, RTO measured |
| ElastiCache Valkey | Coverage phụ | Snapshot/restore evidence hoặc accepted cart-state strategy |
| MSK Kafka | Coverage riêng bằng retention/replay | Producer/consumer replay hoặc order reconciliation; không gọi là PITR |
| DynamoDB lock | Exclude nếu chỉ là Terraform lock | Ghi rõ tái tạo được, không phải dữ liệu khách hàng |
| EBS legacy | Không dùng làm backup proof chính | Pending Mandate #8/#18 hoặc cleanup sau nghiệm thu |
| GitOps/IaC state | Covered bằng Git/state/versioning nếu team claim | Link commit, state bucket/versioning/Object Lock nếu có |

## Hệ quả

Ưu điểm:

- Chứng minh đúng trọng tâm Mandate #20: restore thật, RPO/RTO thật.
- Không cần sửa code ứng dụng.
- Không đụng traffic production.
- Dễ mentor kiểm chứng bằng console/CLI/SQL.

Đánh đổi:

- Chỉ RDS là proof chính; store khác cần coverage matrix hoặc evidence riêng.
- Tạo DB drill tạm phát sinh chi phí nhỏ trong cửa sổ nghiệm thu.
- Security/delete-permission mới partial/remediation in progress: IAM explicit deny có evidence nhưng self-removable; RDS Vault Lock đang được thêm bằng Terraform và chỉ immutable sau CI apply + recovery point + 3 ngày cooling-off.

## Evidence record sau drill

Evidence record chính đã được tạo tại [docs/evidence/mandate-20/mandate-20-final-evidence-20260731.md](../evidence/mandate-20/mandate-20-final-evidence-20260731.md). Record này gồm:

```text
AWS caller/account/region: recorded
RDS source inventory: recorded in baseline/preflight docs
T_good_commit: 2026-07-29T12:02:18.751869Z
T_restore: 2026-07-29T12:03:00Z
T_corrupt_commit: 2026-07-29T12:15:18.439171Z
DB drill identifier: techx-tf3-postgres-drill-20260729-181943
Drill marker id: m20-rds-pitr-20260729-181943
RPO evidence: <= 5 phút target met for drill marker; 0 row data loss
Restore start/end: 2026-07-29T12:40:03Z / 2026-07-29T13:03:53Z
RTO measured: 23.83 phút
Production corrupt query: CORRUPTED_AFTER_GOOD_TIME
Restored DB GOOD query: GOOD_BEFORE_CORRUPTION
Witness mode: recorded video, Drive links recorded in final evidence
```

## Trạng thái pass/fail hiện tại

Tại thời điểm cập nhật evidence:

- Thiết kế RDS PITR drill: **Accepted**
- Hạ tầng nền để chạy drill: **Sẵn sàng**
- Restore drill evidence: **Có - RDS restore correctness PASS, RTO 23.83 phút**
- RPO evidence: **Có - T_restore nằm sau GOOD 41.248131 giây, restored marker GOOD, 0 row data loss**
- Data-tier commitment matrix: **Đã ghi target/verdict; non-RDS store giữ ở coverage/limitation**
- Security/delete-permission verdict: **Partial / remediation in progress - IAM explicit deny chặn direct delete API; RDS Vault Lock Terraform remediation cần apply/cooling-off để đủ hard evidence**

Vì vậy CDO02 có thể claim: **RDS PITR restore drill passed**. Mandate #20 overall chỉ nên claim Done khi scope/limitation cho Valkey/MSK/DynamoDB/EBS/GitOps và hard backup-delete protection được mentor/PM chấp nhận hoặc có evidence bổ sung.

## Chữ ký

Nguyễn Đỗ Hoàng Phúc - CDO02 (Reliability + Operations) - 2026-07-28

