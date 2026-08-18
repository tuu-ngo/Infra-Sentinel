# Mandate #20 - RPO/RTO contract and main restore-drill selection

**Owner:** CDO02 - Reliability + Operations

**Effective:** contract v1 becomes normative when this PR is merged

**Related ADR:** [ADR 0016](../adr/0016-mandate-20-backup-restore-drill-cdo02.md)

**Evidence index:** [Mandate 20 evidence](../evidence/mandate-20/README.md)

## Purpose

Tài liệu này đóng hai quyết định của Mandate #20:

1. Giải thích vì sao RDS PostgreSQL được chọn làm **main restore-drill proof**, thay vì Valkey hoặc MSK Kafka.
2. Định nghĩa contract RPO/RTO có số đo, điểm bắt đầu/kết thúc và cadence tương ứng cho từng data tier/state hiện có.

Contract và evidence là hai gate khác nhau:

- `CONTRACT_DEFINED`: đã có target và cách đo rõ ràng.
- `MECHANISM_CONFIGURED`: backup/retention/recovery path đã được cấu hình.
- `DRILL_PROVEN`: đã có restore/replay drill và raw evidence đạt target.
- `SECURITY_CLOSED`: encryption, retention và delete-authority đã được enforce hoặc có quyết định rủi ro được phê duyệt.

PR tài liệu này có thể đóng task định nghĩa/feedback, nhưng không tự động biến data tier chưa drill thành `DRILL_PROVEN` và không thay thế gate delete-authority.

## Main drill decision

CDO02 chọn **RDS PostgreSQL `techx-tf3-postgres`** làm main restore-drill proof.

Main proof phải đồng thời chứng minh được:

- một stateful store có dữ liệu nghiệp vụ bền vững trên revenue path;
- khôi phục về một mốc thời gian cụ thể trước corruption;
- restore sang môi trường tách biệt, không đè production;
- có thể tạo corruption marker an toàn và xác minh kết quả chính xác;
- đo được RPO và RTO bằng timestamp/raw output.

### Decision matrix

| Tiêu chí main proof | RDS PostgreSQL | Valkey | MSK Kafka |
|---|---|---|---|
| Dữ liệu được dùng làm system of record | Có: catalog/reviews/accounting/order state | Không: cart/session là soft state, có thể thay đổi hoặc hết hạn | Event log dùng để replay, không phải snapshot quan hệ tại một thời điểm |
| Native restore tới timestamp trước sự cố | Có: RDS Point-in-Time Restore | Không: restore theo snapshot, không phải PITR tùy ý | Không: reset offset/replay, không tạo bản store tại timestamp |
| Restore sang tài nguyên tách biệt | Có: DB instance drill riêng | Có thể tạo replication group mới từ snapshot | Có thể dùng consumer group/topic test, nhưng đó là replay chứ không phải backup restore |
| Corruption có kiểm soát và assertion rõ | Có: một row marker `GOOD -> CORRUPTED -> restored GOOD` | Có thể kiểm tra key, nhưng TTL/eviction làm assertion yếu hơn | Replay có thể tạo duplicate side effect nếu consumer/idempotency không được cô lập |
| RPO/RTO của main drill đo trực tiếp | Có: timestamp WAL/PITR và SQL verification | Chỉ phản ánh snapshot cadence; hiện tối đa một ngày theo contract | Phụ thuộc retention, offset, backlog và tốc độ consumer/reconciliation |
| Kết luận | **Chọn làm main proof** | Secondary snapshot-recovery proof | Secondary replay/reconciliation proof |

### Vì sao không chọn Valkey làm main proof

Valkey vẫn nằm trong coverage Mandate #20, nhưng không thay RDS làm proof chính vì:

1. Production hiện dùng snapshot hằng ngày và giữ 3 ngày. Cơ chế này chỉ khôi phục về snapshot gần nhất, không chứng minh PITR tới một timestamp tùy chọn.
2. Cart/session là soft state: key có TTL, có thể bị eviction và không phải sổ cái order/accounting cuối cùng. Khôi phục key cart không chứng minh durable business records đã quay lại đúng trạng thái.
3. Valkey restore phù hợp cho secondary drill: restore snapshot sang replication group tách biệt, đọc sample keys, đo RPO theo tuổi snapshot và RTO tới lúc key verification thành công.

Vì vậy verdict là `COVERED_BY_SNAPSHOT`, không phải `MAIN_PITR_PROOF`.

### Vì sao không chọn MSK Kafka làm main proof

MSK vẫn nằm trên checkout path và phải có recovery contract, nhưng không phải main backup-restore proof vì:

1. Kafka recovery ở kiến trúc hiện tại dựa trên replication, retention 168 giờ, consumer offset reset và replay. Đây không phải point-in-time restore của một store.
2. Replay phải chứng minh idempotency và reconciliation. Nếu chạy không cô lập, cùng một event có thể tạo side effect lặp lại ở RDS/accounting/fraud.
3. RTO phụ thuộc lượng backlog và tốc độ consumer; trạng thái `broker ACTIVE` chưa có nghĩa dữ liệu nghiệp vụ đã reconcile xong.
4. Kafka phù hợp cho một replay drill riêng với test consumer group, bounded event window và đối soát `acknowledged = persisted`, không thay thế RDS PITR drill.

Vì vậy verdict là `COVERED_BY_RETENTION_AND_REPLAY`, không gọi là `PITR` hoặc `SNAPSHOT_RESTORE`.

## Normative RPO/RTO contract v1

Tất cả timestamp dùng UTC. `RTO PASS` chỉ được ghi khi đã đạt **end condition** của dòng tương ứng, không dừng timer chỉ vì hạ tầng chuyển sang `available`.

| Data tier/state | RPO target | RTO target | Recovery mechanism | Cadence / retention | End condition để RTO PASS | Evidence state |
|---|---:|---:|---|---|---|---|
| RDS PostgreSQL `techx-tf3-postgres` | `<= 5 phút` | `<= 45 phút` | Automated backup + PITR sang DB drill private/tách biệt | Continuous PITR; retention `7 ngày` | Query đúng drill endpoint trả marker/data pre-corruption và integrity check pass | Restore correctness và marker RPO đã pass; cần timestamp query thành công để khóa RTO end-to-end |
| ElastiCache Valkey `techx-tf3-valkey` | `<= 24 giờ` | `<= 60 phút` | Restore snapshot sang replication group tách biệt | Daily snapshot window `14:00-15:00 UTC`; retention `3 ngày` | Replication group available, sample keys/value/TTL được xác minh, production endpoint không đổi | Snapshot/config observed; restore drill pending |
| MSK Kafka `techx-tf3-kafka` | `0 phút acknowledged-event loss` trong retention window | `<= 60 phút` cho controlled replay window | Replication + reset offset/replay + reconciliation; không gọi PITR | Continuous replication; `log.retention.hours=168` | Test consumer hoạt động, scoped lag về `0`, và `acknowledged events = persisted/reconciled events`, không duplicate | Retention/encryption observed; bounded replay drill pending |
| DynamoDB `techx-tf3-terraform-lock` | `N/A` cho business data; table chỉ giữ coordination lock tạm | `<= 15 phút` | Recreate bằng bootstrap Terraform rồi prove acquire/release lock | Không yêu cầu customer-data retention khi exclusion được phê duyệt | Table ACTIVE và một lock acquire/release test pass | Exclusion/rebuild record pending mentor approval |
| GitOps/IaC/config/secret references | `<= 15 phút` từ accepted change tới durable Git/state/secret version | `<= 60 phút` | Git history + S3 state object version + Argo reconciliation + secret version/reference recovery | Mỗi Git commit/state write/secret version; state bucket versioning enabled | Chọn đúng version, `terraform plan` đọc state thành công, Argo app Synced/Healthy và secret references resolve | Versioning/config observed; recovery drill and retention/delete control pending |
| EBS/PVC stateful data | `NOT_PRESENT` trong current revenue-path inventory | `NOT_APPLICABLE` | Không được đưa stateful EBS vào production trước khi có snapshot/RPO/RTO contract | EBS encryption-by-default, backup cadence và retention là admission gate nếu tái xuất hiện | Inventory chứng minh không có in-scope volume, hoặc contract mới được phê duyệt trước deployment | Current exclusion; re-inventory required trước acceptance |

Giá trị configuration hiện hành được trace về IaC:

- [RDS backup retention/encryption/deletion protection](../../infra/modules/datastores/rds.tf)
- [Valkey encryption/snapshot retention](../../infra/modules/datastores/elasticache.tf)
- [MSK replication/retention/encryption](../../infra/modules/datastores/msk.tf)
- [Terraform state versioning/encryption](../../infra/bootstrap/backend/main.tf)

### Contract boundaries

- Valkey RPO `<= 24 giờ` không được diễn giải thành `<= 5 phút`; daily snapshot không đáp ứng RPO 5 phút.
- MSK RPO chỉ có hiệu lực cho event đã được producer xác nhận và còn trong retention window 168 giờ. Ngoài cửa sổ đó là contract breach, không được gọi là replay-safe.
- DynamoDB lock được exclude vì không chứa dữ liệu khách hàng. Nếu xuất hiện application table, table đó phải có contract/PITR riêng trước khi claim coverage.
- EBS/PVC là `NOT_PRESENT`, không phải được miễn vĩnh viễn. Bất kỳ stateful volume mới nào đều mở lại gate backup/security.
- RDS `DeletionProtection=true` bảo vệ DB instance nhưng không chứng minh operator không xóa được snapshot/backup. Delete-authority là gate riêng.

## Measurement rules

### RDS

```text
RPO_observed = T_restore - T_last_good_commit
RTO_start    = timestamp ngay trước restore API request
RTO_end      = timestamp của successful query trên restored drill DB
RTO_observed = RTO_end - RTO_start
```

`DBInstanceStatus=available` là checkpoint hạ tầng, không phải `RTO_end`.

### Valkey

```text
RPO_observed = T_incident_or_drill_cut - T_snapshot_create
RTO_start    = timestamp ngay trước create/restore replication-group request
RTO_end      = timestamp khi sample keys/value/TTL trên restored endpoint pass
```

Restore phải dùng endpoint/credentials tách biệt và không repoint production application.

### MSK

```text
RPO_observed = count/timestamp của acknowledged events không xuất hiện sau replay
RTO_start    = timestamp khai báo controlled recovery/replay
RTO_end      = timestamp khi scoped consumer lag = 0 và reconciliation pass
```

Pass condition bắt buộc là `missing=0` và `duplicate=0` trong controlled event window. Chỉ chứng minh broker/topic tồn tại hoặc consumer chạy lại là chưa đủ.

### GitOps/IaC/config

```text
RPO_observed = T_incident - timestamp của newest durable recoverable version
RTO_start    = timestamp bắt đầu chọn/restore version
RTO_end      = timestamp khi state/config validation và reconciliation pass
```

Không đưa secret value vào Git hoặc evidence. Chỉ lưu version identifier, reference path và kết quả resolve đã được sanitize.

## Acceptance mapping for the two documentation tasks

### Task: feedback why Valkey/Kafka are not the main restore proof

- RDS/Valkey/MSK đã được so sánh theo cùng một bộ tiêu chí.
- Valkey được giữ trong snapshot coverage với secondary drill rõ ràng.
- MSK được giữ trong replay/reconciliation coverage và không bị gọi nhầm là PITR.
- Lý do chọn RDS gắn trực tiếp với requirement point-in-time, isolation, integrity và measurable RTO.

### Task: define RPO/RTO contract

- Mỗi data tier/state có target hoặc exclusion có điều kiện.
- Có cadence/retention tương ứng với RPO.
- Có start/end condition để đo RTO, tránh dừng timer ở trạng thái infrastructure-only.
- Contract target và evidence status được tách riêng để không overclaim Mandate #20 overall.

## Remaining gates outside these two tasks

Hai task docs được coi là hoàn tất khi PR này được review/merge. Mandate #20 overall vẫn cần:

- timestamp end-to-end cho RDS successful restored-data query;
- Valkey isolated snapshot-restore drill;
- MSK bounded replay/reconciliation drill;
- approved DynamoDB/EBS exclusions và GitOps/IaC recovery evidence;
- backup delete-authority enforcement hoặc quyết định rủi ro được PM/mentor phê duyệt;
- cleanup drill DB sau khi evidence được chấp nhận.
