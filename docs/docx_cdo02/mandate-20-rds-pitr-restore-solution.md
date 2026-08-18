# Solution Mandate #20 - RDS PITR restore drill

Tài liệu này là bản solution hiện hành cho Mandate #20 sau khi ADR/runbook/evidence scaffold đã merge vào `main`.

## Trạng thái hiện tại

```text
ADR: [docs/adr/0016-mandate-20-backup-restore-drill-cdo02.md](../adr/0016-mandate-20-backup-restore-drill-cdo02.md)
Runbook: [docs/runbooks/mandate-20-rds-pitr-drill.md](../runbooks/mandate-20-rds-pitr-drill.md)
Evidence index: [docs/evidence/mandate-20/README.md](../evidence/mandate-20/README.md)
Video script: incident_report/mandate20-video-script-rds-pitr-drill-2026-07-29.md (operator-local, not pushed as PR evidence)
RDS preflight evidence: [docs/evidence/mandate-20/supporting-rds-pitr-preflight-20260729.md](../evidence/mandate-20/supporting-rds-pitr-preflight-20260729.md)
RDS drill evidence: [docs/evidence/mandate-20/mandate-20-final-rds-pitr-evidence-20260729.md](../evidence/mandate-20/mandate-20-final-rds-pitr-evidence-20260729.md)
RPO/RTO contract and drill selection: [docs/docx_cdo02/mandate-20-rpo-rto-contract-and-drill-selection.md](mandate-20-rpo-rto-contract-and-drill-selection.md)
Status: RDS PITR restore correctness passed; Drive video links recorded in final evidence; overall Mandate #20 depends on accepted non-RDS scope/limitations and delete-authority posture
```

Mandate #20 không chấm theo câu "đã bật backup". Điểm cần chứng minh là:

1. Có RPO/RTO đã cam kết.
2. Có backup/PITR phù hợp với RPO.
3. Có một lần restore thật vào môi trường tách biệt.
4. Có dữ liệu bị hỏng có kiểm soát rồi được restore về đúng trạng thái trước lỗi.
5. Có evidence/video/raw output và RTO đo được.

## Quyết định

CDO02 chọn **RDS PostgreSQL `techx-tf3-postgres`** làm proof chính cho Mandate #20.

Lý do:

- RDS có native Point-in-Time Restore.
- Có thể restore về mốc `T_restore` sang DB instance tạm/tách biệt.
- Có thể kiểm chứng bằng SQL rõ ràng.
- Không cần đổi code, secret, Helm values, ArgoCD sync, hoặc traffic production.

Không chọn Valkey làm main proof vì production recovery path là daily snapshot và cart/session là soft state, không phải timestamp-addressable durable ledger. Không chọn MSK vì reset offset/replay/reconciliation không phải PITR và có duplicate-side-effect risk nếu consumer không được cô lập. Bảng so sánh và contract định lượng nằm tại [RPO/RTO contract and drill selection](mandate-20-rpo-rto-contract-and-drill-selection.md).

Target trong ADR 0016:

```text
RDS RPO target: <= 5 phút
RDS RTO target: <= 45 phút
Expected data loss in probe: 0 row
```

## Cơ chế drill

Drill dùng marker probe trong schema riêng `dr_drill`, không đụng bảng khách hàng.

Luồng evidence:

```text
Production RDS:
1. Tạo marker GOOD_BEFORE_CORRUPTION
2. Ghi T_good_commit_utc
3. Update đúng marker đó thành CORRUPTED_AFTER_GOOD_TIME
4. Ghi T_corrupt_commit_utc

RDS PITR:
5. Chọn T_restore sao cho:
   T_good_commit_utc < T_restore < T_corrupt_commit_utc
6. Restore source DB sang DB drill tạm:
   techx-tf3-postgres-drill-YYYYMMDD-HHMMSS

Restored drill DB:
7. Query marker phải trả GOOD_BEFORE_CORRUPTION
8. Đo RTO từ lúc bắt đầu restore tới lúc query restored DB thành công
```

Nếu restored DB trả `CORRUPTED_AFTER_GOOD_TIME`, missing row, hoặc RTO vượt 45 phút thì không claim pass.

## Kết quả drill ngày 2026-07-29

```text
Drill marker id: m20-rds-pitr-20260729-181943
Drill DB id: techx-tf3-postgres-drill-20260729-181943
T_good_commit_utc: 2026-07-29T12:02:18.751869Z
T_restore: 2026-07-29T12:03:00Z
T_corrupt_commit_utc: 2026-07-29T12:15:18.439171Z
RestoreStart: 2026-07-29T12:40:03Z
RestoreEnd: 2026-07-29T13:03:53Z
RPO target: <= 5 phút
RPO evidence: T_restore cách T_good_commit_utc 41.248131 giây và restored DB trả lại marker GOOD
Probe data loss: 0 row
Infrastructure available elapsed: 23.83 phút
RTO target: <= 45 phút
Restored DB marker: GOOD_BEFORE_CORRUPTION
RDS PITR restore correctness: PASS
End-to-end RTO verdict: pending successful-query timestamp addendum
Video evidence: 4 videos captured, Drive links recorded in final evidence
```

Lưu ý khi đọc video:

```text
Một query trung gian trong video 3 trả CORRUPTED_AFTER_GOOD_TIME vì local tunnel đang trỏ production endpoint trên port 15432.
Video 4 mở tunnel riêng sang drill endpoint trên port 15433 và verify restored DB trả GOOD_BEFORE_CORRUPTION.
Đây là port-forward context issue, không phải restore failure.
```

## Vì sao không xóa dữ liệu thật

Marker là dữ liệu thật được commit vào production RDS và đi qua cùng cơ chế WAL/PITR với dữ liệu app. Việc phá marker là corruption có kiểm soát để chứng minh restore mechanism.

Không xóa data customer/order/payment thật vì:

- có thể tạo incident thật;
- có thể ảnh hưởng SLO và luồng ra tiền;
- mandate yêu cầu restore proof, không yêu cầu gây outage production;
- restore phải vào môi trường tách biệt, không đè production.

## Hạ tầng tạm cần tạo

Chỉ tạo một RDS instance restore tạm:

```text
techx-tf3-postgres-drill-YYYYMMDD-HHMMSS
```

Không tạo DB production mới. Không repoint app. Không đổi `DB_CONNECTION_STRING`.

Tạo bằng AWS CLI theo runbook/video script. Terraform IaC cho drill là optional và chỉ dùng nếu mentor yêu cầu; không phải đường mặc định cho buổi quay.

## Đường kết nối SQL khi quay video

Vì RDS là private, dùng SSM port-forward qua bastion:

```text
Local Docker psql -> host.docker.internal:15432
localhost:15432 -> SSM bastion -> techx-tf3-postgres:5432
```

Tool hiện hành:

```text
Docker Desktop: running
Docker image: postgres:17
SQL client: docker run postgres:17 psql
Local psql: not required
```

## Data-tier coverage

Mandate #20 yêu cầu không sót store/stateful state. CDO02 claim theo mức sau:

| Store/state | Vai trò | Mandate #20 stance |
|---|---|---|
| RDS PostgreSQL `techx-tf3-postgres` | Store chính cho catalog/reviews/accounting/order data | Proof chính bằng PITR restore drill |
| ElastiCache Valkey `techx-tf3-valkey` | Cart/session cache | Snapshot recovery contract: RPO `<= 24h`, RTO `<= 60m`; secondary drill pending |
| MSK Kafka `techx-tf3-kafka` | Event stream | Replay/reconciliation contract: no acknowledged-event loss in 168h window, RTO `<= 60m`; không gọi là PITR |
| DynamoDB `techx-tf3-terraform-lock` | Terraform lock | Business-data RPO `N/A`; rebuild RTO `<= 15m`, pending approved exclusion |
| EBS/PVC stateful data | Không có trong current revenue-path inventory | `NOT_PRESENT`; mở lại contract gate nếu stateful volume tái xuất hiện |
| GitOps/IaC/config/secret references | Source of truth cấu hình/hạ tầng | RPO `<= 15m`, RTO `<= 60m`; recovery evidence pending |

## Backup safety / delete authority

ADR 0016 đã ghi bảng quyền xóa backup. Với bối cảnh account có nhiều admin-wide principal, CDO02 không nên claim đã chống xóa backup tuyệt đối bằng SCP.

Cách nói khi quay:

```text
RDS có encryption, backup retention, snapshot baseline và deletion protection.
Operator CDO02 trong drill không xóa backup production, chỉ xóa DB drill tạm sau evidence.
Nếu cần chặn tuyệt đối mọi admin-wide principal thì đó là IAM/SCP/permission-boundary hardening hoặc accepted risk riêng.
Trong buổi drill này, em chứng minh restore path và ghi rõ delete-authority posture.
```

## Evidence cần có để pass

Trước drill:

- Git baseline.
- AWS caller/account/region.
- RDS source inventory.
- RDS automated backup/PITR baseline.
- RDS snapshot list.
- Stale drill DB check.
- Security/delete authority note hoặc accepted risk.

Trong drill:

- `DrillMarkerId`.
- `T_good_commit_utc`.
- `T_corrupt_commit_utc`.
- `T_restore`.
- Restore command/output.
- DB drill identifier/endpoint.
- Restore start/end.
- End-to-end RTO measured tới successful restored-data query.

Sau restore:

- Production marker vẫn `CORRUPTED_AFTER_GOOD_TIME` nếu query lại production.
- Restored DB marker trả `GOOD_BEFORE_CORRUPTION`.
- Cleanup DB drill sau khi đã capture đủ.
- Witness mode: recorded video hoặc mentor/PM live.

## Pass/fail

Có thể claim Mandate #20 pass khi:

- RDS PITR restore drill chạy thật.
- Restored DB trả marker GOOD.
- RTO thực tế đạt `<= 45 phút`.
- Evidence/video/raw output được lưu.
- Không ảnh hưởng production traffic/SLO.
- Backup delete-authority được ghi rõ: enforced, hoặc accepted risk/admin-wide limitation.

Trạng thái hiện tại:

```text
RDS PITR restore drill: PASS
RPO <= 5 phút: PASS cho marker drill, 0 row data loss
RTO <= 45 phút: pending end-to-end timestamp; 23.83 phút is infrastructure available elapsed
Production traffic/SLO impact: none expected / no repoint performed
Drive links: recorded in [docs/evidence/mandate-20/mandate-20-final-rds-pitr-evidence-20260729.md](../evidence/mandate-20/mandate-20-final-rds-pitr-evidence-20260729.md)
Mandate #20 overall: cần mentor/PM chấp nhận scope/limitation cho non-RDS stores và delete-authority posture trước khi claim Done toàn bộ
```
