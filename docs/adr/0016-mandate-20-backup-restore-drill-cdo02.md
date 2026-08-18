# ADR 0016 - Mandate #20: RDS PITR restore drill for CDO02 backup/recovery proof

**Ngày:** 2026-07-28  
**Người quyết định (ký):** Nguyễn Đỗ Hoàng Phúc - CDO02 (Reliability + Operations)  
**Directive:** `MANDATE-20-dr-backup-restore.md` - Backup/Restore DR  
**Trạng thái:** RDS PITR drill executed - RDS restore correctness passed; overall Mandate #20 còn phụ thuộc accepted scope/limitation cho non-RDS stores và delete-authority posture  
**Tham chiếu:** [docs/docx_cdo02/mandate-20-rds-pitr-restore-solution.md](../docx_cdo02/mandate-20-rds-pitr-restore-solution.md)

**RPO/RTO contract + drill selection:** [docs/docx_cdo02/mandate-20-rpo-rto-contract-and-drill-selection.md](../docx_cdo02/mandate-20-rpo-rto-contract-and-drill-selection.md)

## Bối cảnh

Mandate #20 yêu cầu chứng minh hệ thống khôi phục được dữ liệu sau mất/hỏng dữ liệu, bằng một restore drill thật, có RPO/RTO đo được. Yêu cầu không được tính là đạt chỉ vì đã bật backup.

TF3 hiện đã migrate datastore chính lên managed service theo Mandate #8:

- RDS PostgreSQL `techx-tf3-postgres`
- ElastiCache Valkey `techx-tf3-valkey`
- MSK Kafka `techx-tf3-kafka`

RDS hiện là ứng viên tốt nhất để làm proof chính vì có Point-in-Time Restore native, có thể restore về mốc trước lỗi sang DB instance tách biệt, rồi kiểm chứng bằng SQL mà không đổi traffic production.

Valkey không được chọn làm main proof vì current recovery path là daily snapshot, không phải timestamp-addressable PITR, và cart/session là soft state thay vì durable business ledger. MSK không được chọn vì recovery path là retention/offset replay/reconciliation; replay không phải point-in-time restore và cần guard chống duplicate side effect. Decision matrix và contract định lượng nằm trong [RPO/RTO contract + drill selection](../docx_cdo02/mandate-20-rpo-rto-contract-and-drill-selection.md).

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
Evidence record: [docs/evidence/mandate-20/mandate-20-final-rds-pitr-evidence-20260729.md](../evidence/mandate-20/mandate-20-final-rds-pitr-evidence-20260729.md)
Drill marker id: m20-rds-pitr-20260729-181943
T_good_commit_utc: 2026-07-29T12:02:18.751869Z
T_restore: 2026-07-29T12:03:00Z
T_corrupt_commit_utc: 2026-07-29T12:15:18.439171Z
Restored DB result: GOOD_BEFORE_CORRUPTION
RPO evidence: T_restore cách T_good_commit_utc 41.248131 giây; probe data loss 0 row
Infrastructure available elapsed: 23.83 phút
RTO target: <= 45 phút
RDS PITR restore correctness: PASS
End-to-end RTO verdict: pending successful-query timestamp addendum
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
- End-to-end RTO measured tới successful restored-data query.
- Cleanup DB drill; production marker cleanup nếu có thì chỉ xóa đúng marker id của lần drill, hoặc giữ lại làm audit trail.
- Coverage matrix cho store khác: ElastiCache, MSK, DynamoDB lock, EBS legacy, GitOps/IaC state.

CDO02 không claim hoàn tất toàn bộ yêu cầu Security của Mandate #20 nếu chưa có evidence enforcement hoặc accepted-risk note cho quyền xóa backup.

## Security / delete-authority posture

Phần Security/delete-authority cần được review hoặc ghi accepted risk rõ ràng:

- Encryption/KMS posture của datastore và backup/snapshot.
- Ai được phép xóa RDS snapshot/automated backup.
- IAM deny, permission boundary, hoặc process break-glass cho hành động xóa backup.
- Retention/security guardrail.
- Accepted limitation nếu account còn admin rộng hoặc không dùng SCP.

Trong account hiện tại có nhiều principal quyền rộng, nên ADR này **không claim chống xóa backup tuyệt đối** nếu chưa có SCP/permission boundary/explicit deny hoặc accepted-risk note.

## Mandate #20 data-tier commitments

ADR này ghi cam kết vận hành theo từng tầng dữ liệu để khớp yêu cầu Mandate #20. RDS đã có drill evidence thật; các store/state còn lại giữ ở dạng coverage/limitation để không overclaim.

| Tầng dữ liệu / state | Vai trò trong hệ thống | RPO target | RTO target | Backup / recovery strategy | Cadence / retention | CDO02 claim | Security / delete-permission verdict |
|---|---|---|---|---|---|---|---|
| RDS PostgreSQL `techx-tf3-postgres` | Store chính cho catalog/reviews/accounting/order data | `<= 5 phút` theo PITR window | `<= 45 phút` từ restore request tới successful restored-data query; infrastructure available elapsed `23.83 phút` | RDS automated backup + PITR; restore về `T_restore` sang DB drill tách biệt | Automated backup retention 7 ngày; manual snapshot phụ nếu có | Restore correctness và marker RPO pass; end-to-end RTO cần timestamp query thành công | Cần ghi ai được xóa snapshot/automated backup và KMS posture; nếu admin-wide còn rộng thì ghi accepted risk |
| ElastiCache Valkey `techx-tf3-valkey` | Cart/session cache trên luồng browse -> cart -> checkout | `<= 24 giờ` theo tuổi snapshot | `<= 60 phút` tới lúc sample keys/value/TTL trên restored endpoint pass | Restore snapshot sang replication group tách biệt; cart là soft-state, không dùng làm PITR proof chính | Daily snapshot window `14:00-15:00 UTC`; retention `3 ngày` | Contract defined; secondary restore drill pending | Cần ghi encryption/snapshot delete permission hoặc accepted risk |
| MSK Kafka `techx-tf3-kafka` | Order event stream cho checkout -> accounting/fraud | `0 phút acknowledged-event loss` trong retention window | `<= 60 phút` cho controlled replay tới lúc scoped lag `0` và reconciliation pass | MSK retention/reset offset/replay; không gọi là PITR backup | Continuous replication; `log.retention.hours=168` | Contract defined; bounded replay/reconciliation drill pending | Cần ghi KMS/IAM/delete topic/config destructive control nếu claim |
| DynamoDB `techx-tf3-terraform-lock` | Terraform lock table, không phải dữ liệu khách hàng | `N/A` cho business data nếu exclusion được phê duyệt | `<= 15 phút` để recreate và prove acquire/release lock | Exclusion with reason, không dùng làm data restore proof | Không yêu cầu customer-data retention khi exclude | Contract defined; mentor approval/rebuild record pending | Nếu team muốn protect, cần xác nhận PITR/IAM |
| EBS/PVC stateful data | Không có trong current revenue-path inventory | `NOT_PRESENT`; phải định nghĩa trước khi tái xuất hiện | `NOT_APPLICABLE` khi inventory vẫn trống | Stateful EBS mới bị chặn cho tới khi có snapshot/RPO/RTO contract | Backup cadence/retention là admission gate cho volume mới | Conditional exclusion; re-inventory required | Nếu xuất hiện volume, cần encryption/delete policy verdict |
| GitOps/IaC/config/secret references | Manifest, config, Terraform state/source of truth | `<= 15 phút` từ accepted change tới durable version | `<= 60 phút` tới lúc state/config validation và reconciliation pass | Git history + S3 state version + Argo reconciliation + secret version/reference recovery | Mỗi Git commit/state write/secret version; retention/delete control cần evidence | Contract defined; recovery drill pending | Cần xác nhận state bucket/Object Lock/IAM delete protection nếu claim |

## Backup deletion authority

Mandate #20 yêu cầu ghi rõ **ai được xóa backup**. ADR này ghi policy mong muốn, phần đã vận hành trong drill, và chỗ cần evidence enforcement hoặc accepted risk.

| Principal / nhóm | Quyền xóa backup mong muốn | Trạng thái trong ADR này | Evidence cần có |
|---|---|---|---|
| Read-only / reviewer / mentor viewer | Không được xóa | Policy target | IAM policy/console role evidence nếu claim enforcement |
| CDO02 operator chạy drill | Không được xóa backup production; chỉ được tạo/xóa DB drill tạm sau approval | CDO02 operating rule | Runbook/evidence cleanup chỉ áp dụng DB drill identifier |
| CI Terraform plan role | Không được xóa backup; chỉ plan/read | Policy target | CI/IAM evidence nếu claim enforcement |
| CI Terraform apply role | Không được xóa backup production ngoài PR được review và approved | Security/delete-authority verdict | IAM guard, permission boundary, hoặc accepted limitation |
| Break-glass / account owner | Có thể xóa trong tình huống khẩn cấp có ticket/MFA/owner approval | Accepted operational reality nếu account còn admin rộng | CloudTrail/audit process + named owner từ PM/account owner |
| Unknown/admin-wide principals | Không claim đã chặn tuyệt đối nếu chưa có SCP/permission boundary | **Open risk** | Security verdict hoặc accepted risk |

Kết luận: trước khi có enforcement evidence hoặc accepted-risk note, CDO02 chỉ claim phần restore drill và ghi rõ delete-protection là limitation. Mandate #20 overall chưa nên claim Done nếu bảng deletion authority chưa được review hoặc accepted-risk chưa được PM/mentor chấp nhận.

## Coverage matrix

| Store / state | Quyết định CDO02 | Điều kiện evidence |
|---|---|---|
| RDS PostgreSQL | Drill chính bằng PITR | Restored DB trả marker GOOD, end-to-end RTO measured tới successful query |
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
- Security/delete-permission vẫn cần evidence enforcement hoặc accepted-risk note, không được claim tuyệt đối nếu account còn admin-wide.

## Evidence record sau drill

Evidence record chính đã được tạo tại [docs/evidence/mandate-20/mandate-20-final-rds-pitr-evidence-20260729.md](../evidence/mandate-20/mandate-20-final-rds-pitr-evidence-20260729.md). Record này gồm:

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
Infrastructure available elapsed: 23.83 phút
End-to-end RTO: pending successful-query timestamp addendum
Production corrupt query: CORRUPTED_AFTER_GOOD_TIME
Restored DB GOOD query: GOOD_BEFORE_CORRUPTION
Witness mode: recorded video, Drive links recorded in final evidence
```

## Trạng thái pass/fail hiện tại

Tại thời điểm cập nhật evidence:

- Thiết kế RDS PITR drill: **Accepted**
- Hạ tầng nền để chạy drill: **Sẵn sàng**
- Restore drill evidence: **Có - RDS restore correctness PASS; infrastructure available elapsed 23.83 phút**
- RPO evidence: **Có - T_restore nằm sau GOOD 41.248131 giây, restored marker GOOD, 0 row data loss**
- Data-tier commitment matrix: **Đã ghi target/verdict; non-RDS store giữ ở coverage/limitation**
- RTO end-to-end: **Cần timestamp của successful query trên drill DB để tính đúng contract**
- Security/delete-permission verdict: **Cần enforcement evidence hoặc accepted risk**

Vì vậy CDO02 có thể claim: **RDS PITR restore correctness passed**. Không claim RTO end-to-end chỉ từ mốc DB `available`; Mandate #20 overall chỉ nên claim Done khi có timestamp query thành công, scope/limitation cho Valkey/MSK/DynamoDB/EBS/GitOps và delete-authority posture được mentor/PM chấp nhận.

## Chữ ký

Nguyễn Đỗ Hoàng Phúc - CDO02 (Reliability + Operations) - 2026-07-28

