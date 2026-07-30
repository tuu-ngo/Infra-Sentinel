# PM-160 - Mandate #20: Kế hoạch Backup, PITR và Restore Drill thực tế

| Trường | Giá trị |
|---|---|
| Jira | PM-160 |
| Branch | `feat/pm-160-m20-backup-pitr-restore-drill` |
| Phạm vi | Backup tự động, RPO/RTO, PITR ra môi trường tách biệt và restore drill thật |
| Drill trọng tâm | Point-in-time restore RDS PostgreSQL |
| Trạng thái tài liệu | `REVIEW PLAN`; đây chưa phải runtime evidence và chưa được dùng để kết luận Mandate #20 hoàn thành |

## 1. Mục tiêu

PM-160 phải chứng minh dữ liệu trên luồng ra tiền có thể được khôi phục sau khi bị xóa nhầm hoặc ghi hỏng logic. Kết quả được đánh giá bằng RPO thực tế, RTO thực tế và tính toàn vẹn của dữ liệu sau restore, không phải bằng ảnh chụp cho thấy chức năng backup đã được bật.

Phạm vi cần hoàn thành:

1. Backup tự động cho mọi stateful store tham gia browse -> cart -> checkout.
2. RPO/RTO được phê duyệt và cadence backup đủ để đạt từng RPO.
3. Point-in-time restore ra môi trường tách biệt.
4. Drill theo luồng gây hỏng có kiểm soát -> restore -> kiểm tra integrity.
5. Recovery point được mã hóa và quyền xóa backup tách khỏi quyền vận hành thông thường.
6. Evidence đủ để mentor kiểm tra và tái hiện kết quả.

## 2. Hợp đồng an toàn

PR triển khai không được tự động chạy corruption hoặc production restore.

- Cấu hình backup lâu dài phải được quản lý bằng Terraform và qua workflow plan/apply hiện có.
- Drill chỉ chạy trong maintenance window được duyệt, có người thực hiện và witness rõ ràng.
- Corruption chỉ tác động lên probe data được tạo riêng cho PM-160.
- Không sửa bảng khách hàng, cart thật, order event thật hoặc Terraform state đang active.
- Restore target luôn là tài nguyên tạm mới trong private subnet; application không được chuyển traffic sang target này.
- Không sửa production secret hoặc ExternalSecret để trỏ vào tài nguyên drill.
- Chỉ cleanup sau khi evidence đã được lưu và mentor chấp nhận.
- Không thay đổi `/flagservice` hoặc cơ chế điều khiển sự cố runtime.
- Không bật Compliance-mode Vault Lock trước khi retention, chi phí và grace period được review, vì sau grace period cấu hình này không thể rollback.

## 3. Hiện trạng đã xác minh

Read-only audit ngày 2026-07-28 ghi nhận:

| Thành phần | Hiện trạng | Gap |
|---|---|---|
| RDS `techx-tf3-postgres` | Multi-AZ, encrypted, deletion protection, automated backup 7 ngày, PITR đang hoạt động | Chưa restore PITR ra môi trường tách biệt và chưa đo RTO |
| Valkey `techx-tf3-valkey` | Multi-AZ, encrypted, automatic failover, daily snapshot retention 3 ngày | Chưa chốt RPO/retention và chưa restore thử |
| MSK `techx-tf3-kafka` | 3 AZ, RF=3, min ISR=2, encrypted, log retention 7 ngày | Replication và retention không phải backup độc lập |
| S3 `techx-products-catalog-2026` | Versioning và public access block đã bật | Chưa có immutable backup và restore drill |
| S3 Terraform state | Versioning, SSE-S3 và public access block đã bật | Chưa có immutable recovery copy và isolated restore test |
| DynamoDB Terraform lock | Table đang active, chỉ phục vụ Terraform locking | PITR đang tắt |
| Legacy EBS/PVC | Có 3 PVC orphan, không được money-path pod hiện tại mount | Volume chưa mã hóa, không có snapshot và chưa chốt owner/exclusion |
| AWS Backup | Không có vault, plan, protected resource hoặc restore job | Chưa có lớp backup tập trung và chống xóa |
| IAM | Production operator chỉ có read-only | Terraform apply role và admin hiện vẫn có thể xóa recovery material |

Inventory phải được chạy lại ngay trước khi triển khai. Nếu dependency hoặc owner của datastore thay đổi, coverage matrix phải được review lại.

## 4. Phạm vi từng datastore

Mỗi store phải có đúng một verdict trong ADR:

- `COVERED`: có backup tự động, retention, restore procedure và owner.
- `EXCLUDED`: không phải money-path state, có thể dựng lại và được owner ký xác nhận loại trừ.
- `BLOCKED`: thiết kế backup/restore chưa hoàn tất; chưa được đóng Mandate #20.

Verdict đề xuất để review:

| Store | Verdict đề xuất | Việc cần làm |
|---|---|---|
| RDS PostgreSQL | `COVERED` sau drill | Giữ native PITR, thêm recovery point chống xóa và chạy drill |
| Valkey cart | `COVERED` sau restore test | Tăng retention và chứng minh snapshot restore |
| MSK orders | `BLOCKED` đến khi có archive | Archive order event độc lập và chứng minh replay |
| Product catalog S3 | `COVERED` sau backup/restore | Continuous/versioned backup và isolated object restore |
| Terraform state S3 | `COVERED` sau backup/restore | Immutable backup và restore vào key/workspace tạm |
| DynamoDB lock | `COVERED` như support component | Bật PITR; không restore đè active lock table |
| Legacy EBS/PVC | `EXCLUDED` nếu owner xác nhận | Lưu evidence không còn workload sử dụng và chốt retention/cleanup owner |
| GitOps repository | `COVERED` sau bundle automation | Backup Git history định kỳ vào nơi lưu trữ immutable |

## 5. RPO/RTO đề xuất

Các giá trị dưới đây là target để review, chưa phải kết quả đã đạt. Target chỉ trở thành cam kết sau khi data owner và mentor ký ADR. Evidence cuối cùng phải ghi cả target và số đo thực tế.

| Tầng dữ liệu | RPO đề xuất | RTO đề xuất | Cadence/retention | Điều kiện pass |
|---|---:|---:|---|---|
| RDS PostgreSQL | <= 5 phút | <= 45 phút | Continuous PITR, retention 7 ngày, daily recovery point | Restore point mất không quá 5 phút dữ liệu và SQL validation hoàn tất trong 45 phút |
| Valkey cart | <= 24 giờ | <= 60 phút | Daily native snapshot, retention 7 ngày | Temporary replication group có đúng probe key trong 60 phút |
| MSK order archive | <= 5 phút | <= 60 phút | Continuous archive sang immutable S3, source retention 7 ngày | Archive lag <= 5 phút và checksum event replay khớp trong 60 phút |
| Product catalog S3 | <= 15 phút | <= 60 phút | Versioning + continuous backup, retention 30 ngày | Object bị xóa/ghi hỏng được restore sang destination tách biệt |
| Terraform state S3 | <= 15 phút | <= 30 phút | Versioning + continuous backup, retention 30 ngày | State version restore đọc được mà không thay active backend object |
| DynamoDB lock table | <= 5 phút | <= 30 phút | Native DynamoDB PITR | Restore tạo table mới, source table vẫn active |
| GitOps/IaC repository | <= 24 giờ | <= 30 phút | Daily `git bundle`, retention 30 ngày và Git history | Clone từ bundle pass `git fsck` và có đúng commit đã ghi nhận |

Valkey cần quyết định nghiệp vụ riêng. Nếu không chấp nhận mất tối đa 24 giờ cart data, PM-160 phải bổ sung hourly snapshot scheduler và retention cleanup. Không được cam kết RPO 1 giờ khi hệ thống chỉ snapshot mỗi ngày.

## 6. Kiến trúc backup mục tiêu

### 6.1 AWS Backup foundation

Tạo module Terraform `infra/modules/backup-recovery/` gồm:

- customer-managed KMS key và alias cho backup;
- AWS Backup vault;
- vault access policy từ chối xóa recovery point đối với operator và CI role thông thường;
- backup plan/selection cho RDS, S3 và EBS được chọn bằng tag;
- continuous backup cho RDS/S3 được hỗ trợ;
- periodic recovery point cho resource cần snapshot định kỳ;
- retention lifecycle có giới hạn, không giữ vô hạn;
- EventBridge/SNS notification khi backup job failed, aborted hoặc expired;
- output không nhạy cảm gồm vault ARN, plan ID và notification target.

RDS và S3 production phải được chọn bằng exact ARN. EBS có thể dùng tag `BackupTier=money-path`, nhưng PR phải chứng minh volume nào thật sự có tag. Một selection không match volume nào không được tính là EBS backup evidence.

### 6.2 Vault Lock rollout

Vault Lock được rollout qua hai gate:

1. Triển khai governance mode với min/max retention đã review.
2. Chạy backup và restore validation trong khoảng còn thay đổi được.
3. Mentor/security duyệt retention, chi phí và break-glass owner.
4. Chuyển sang compliance mode bằng PR riêng với grace period đã ghi rõ.

Không gộp Compliance-mode Vault Lock vào PR tạo vault lần đầu. Sau khi grace period kết thúc sẽ không còn đường rollback.

### 6.3 RDS

Giữ native RDS PITR làm cơ chế point-in-time chính và khai báo rõ trong Terraform:

- `backup_retention_period >= 7`;
- backup window cố định ngoài giờ traffic chính;
- storage và snapshot được mã hóa;
- source DB bật deletion protection;
- source deletion luôn tạo final snapshot;
- chỉ có một continuous backup plan phù hợp, tránh cấu hình trùng lặp không cần thiết.

### 6.4 Valkey

ElastiCache sử dụng native snapshot:

- tăng `snapshot_retention_limit` từ 3 lên 7 ngày;
- cấu hình snapshot window cố định;
- giữ encryption at-rest và in-transit;
- ghi rõ daily RPO có được business chấp nhận hay không;
- nếu cần hourly RPO, tạo scheduler với quyền tối thiểu cho `CreateSnapshot`, kiểm tra trạng thái và cleanup snapshot hết hạn;
- restore snapshot được chọn thành temporary replication group trong drill window.

### 6.5 MSK

Broker replication và `log.retention.hours=168` hỗ trợ availability/replay nhưng không bảo vệ trước topic deletion hoặc logical corruption.

Thiết kế bắt buộc:

1. Archive money-path topic `orders` bằng dedicated consumer hoặc MSK Connect sink được phê duyệt.
2. Ghi record vào S3 theo topic/date/partition.
3. Lưu topic, partition, offset, event ID và checksum cùng archived record.
4. Bucket archive phải có versioning, encryption, retention và delete protection.
5. Cảnh báo khi archive consumer lag vượt RPO 5 phút.
6. Có replay tool mặc định chỉ ghi vào isolated drill topic, không ghi live topic.

Không được đánh dấu MSK `COVERED` nếu chỉ có RF=3 hoặc broker retention 7 ngày.

### 6.6 GitOps, Terraform state và DynamoDB

- Thêm Terraform state bucket vào continuous S3 backup.
- Chỉ restore state sang bucket/key tạm hoặc local file để kiểm tra integrity.
- So sánh `lineage`, `serial` và resource count; không chạy `terraform apply` với restored state trong drill.
- Bật PITR cho `techx-tf3-terraform-lock` trong `infra/bootstrap/backend/main.tf`.
- DynamoDB PITR chỉ restore sang table có tên mới.
- Tạo scheduled `git bundle --all` và lưu bundle vào backup bucket được bảo vệ.
- Clone bundle trong thư mục tách biệt và chạy `git fsck` để xác minh.

### 6.7 EBS

Trước khi bật EBS selection:

1. Map từng attached EBS volume với workload và data classification.
2. Chỉ tag active money-path volume bằng `BackupTier=money-path`.
3. Theo dõi ba orphan PVC volume trong một verdict riêng.
4. Không giữ vô hạn stale unencrypted data chỉ để có dấu tick backup.
5. Nếu owner yêu cầu retention trước cleanup, tạo encrypted final snapshot có expiry và evidence.

Nếu không có active money-path EBS volume, ADR phải ghi `NOT APPLICABLE` kèm live attachment/mount evidence. Không được dùng một EBS selection rỗng để claim MSK-managed broker storage đã được backup.

## 7. File dự kiến thay đổi

| File/path | Thay đổi dự kiến |
|---|---|
| `docs/adr/0016-mandate-20-backup-restore.md` | ADR ký RPO/RTO, coverage, retention, owner và quyền xóa |
| `infra/modules/backup-recovery/` | KMS, vault, policy, plan, selection và notification |
| `infra/live/production/backup-recovery.tf` | Kết nối RDS/S3/EBS production vào module |
| `infra/live/production/m20-variables.tf` | Retention, lock mode và feature gate |
| `infra/live/production/outputs.tf` | Vault/plan identifier phục vụ evidence |
| `infra/modules/datastores/rds.tf` | Backup window/retention contract nếu cần |
| `infra/modules/datastores/elasticache.tf` | Retention 7 ngày và snapshot window |
| `infra/bootstrap/backend/main.tf` | DynamoDB PITR và metadata backup state |
| `scripts/mandate-20/` | Inventory, drill orchestration, validation và cleanup script |
| `scripts/ci/test_mandate20_backup_contract.py` | Static contract test cho coverage/cadence/isolation/retention |
| `.github/workflows/validate-mandate20-backup.yml` | Chỉ validate Terraform và contract; không production restore |
| `docs/runbooks/mandate-20-restore-drill.md` | Runbook có gate, witness và rollback |
| `docs/evidence/mandate-20/README.md` | Evidence index và completion checklist |

Tên file có thể được điều chỉnh theo ownership hiện có, nhưng backup resource, drill automation, ADR và evidence phải được tách thành các phần review độc lập.

## 8. CI và contract gate

CI phải fail khi:

- RDS retention thấp hơn target đã duyệt;
- DynamoDB PITR không có trong khi lock table tồn tại;
- Terraform state bucket không bật versioning;
- required RDS/S3 ARN không nằm trong backup selection;
- EBS coverage được claim nhưng không có volume match tag hoặc signed exclusion;
- vault không có encryption hoặc deletion-deny policy;
- retention ngắn hơn recovery window đã cam kết;
- restore resource có thể public;
- drill target có thể trùng production identifier;
- cleanup script có thể chọn production RDS identifier;
- workflow corruption/restore chạy từ event `pull_request` hoặc `push`.

Validation gồm Terraform format, init không dùng backend khi phù hợp, `terraform validate`, IaC security scan và Mandate 20 contract test. CI xanh chỉ chứng minh cấu hình hợp lệ, không phải restore evidence.

## 9. Gate trước drill

Mentor-witnessed drill chỉ bắt đầu khi tất cả điều kiện đều đạt:

1. ADR RPO/RTO đã ký.
2. Backup job đã tạo recovery point trạng thái available.
3. RDS `LatestRestorableTime` đủ mới cho mốc test.
4. Restore role được tạo drill target nhưng không có quyền sửa/xóa source RDS.
5. Drill security group private và chỉ mở cho operator path được duyệt.
6. Storefront, browse, cart và checkout đang healthy.
7. Argo CD Synced/Healthy; pre-existing exception không liên quan phải được ghi nhận.
8. Không có migration, production deployment hoặc load test khác chạy cùng lúc.
9. Temporary resource có cost/TTL owner.
10. Evidence directory, UTC timestamp source và witness đã chuẩn bị trước corruption.

Thiếu bất kỳ gate nào thì verdict là `BLOCKED`; không ứng biến bỏ qua gate trong lúc drill.

## 10. RDS PITR drill trọng tâm

### 10.1 Tạo probe an toàn

Sử dụng schema riêng như `dr_drill`, không chứa customer data.

1. Tạo `dr_drill.restore_probe` gồm test ID, payload, timestamp và checksum.
2. Ghi marker `GOOD_BEFORE_CORRUPTION`.
3. Đọc lại record và lưu `good_time_utc`, output cùng checksum.
4. Chờ `LatestRestorableTime >= good_time_utc`.
5. Xác nhận drill SQL không chọn bảng khách hàng.

### 10.2 Gây hỏng có kiểm soát

1. Ghi `incident_start_utc` ngay trước corruption.
2. Chỉ `DROP TABLE dr_drill.restore_probe` hoặc ghi hỏng đúng probe table.
3. Xác nhận probe đã mất/hỏng trên source DB.
4. Không restore probe ngược vào production; customer traffic tiếp tục dùng source DB bình thường.

### 10.3 Restore theo point-in-time

1. Chọn restore timestamp sau good write và trước corruption.
2. Restore thành `techx-tf3-postgres-m20-drill-<UTC timestamp>`.
3. Dùng private DB subnet và drill-only security group.
4. Dùng instance class nhỏ nhất được phê duyệt và bắt buộc có TTL tag.
5. Không tạo public connectivity.
6. Không sửa app secret, GitOps manifest hoặc DNS.
7. Theo dõi trạng thái tới khi available và lưu state transition.

### 10.4 Kiểm tra integrity

1. Kết nối qua SSM/bastion path được duyệt.
2. Query probe trên restored DB.
3. Kiểm tra ID, payload, timestamp và checksum khớp evidence trước corruption.
4. Xác nhận endpoint đang query thuộc drill DB và source vẫn là production DB.
5. Ghi `validation_complete_utc`.
6. Tính RTO thực bằng `validation_complete_utc - incident_start_utc`.
7. Tính RPO quan sát từ restore time và last verified good write.

Chỉ pass khi integrity khớp và RPO/RTO nằm trong target đã ký. DB đạt trạng thái `available` nhưng SQL validation fail vẫn là drill fail.

### 10.5 Cleanup

Cleanup là action có xác nhận riêng:

- giữ drill DB đến khi mentor chấp nhận evidence;
- chỉ cho phép identifier có approved drill prefix;
- lưu metadata cuối trước khi xóa;
- chỉ xóa temporary DB và temporary security group;
- không dùng wildcard resource selector;
- lưu thời gian cleanup và xác nhận production DB vẫn available;
- chạy lại storefront/datastore health check.

## 11. Restore test bổ sung

| Store | Corruption an toàn | Isolated restore | Integrity proof |
|---|---|---|---|
| Valkey | Xóa key `m20:probe:*` sau snapshot | Temporary replication group | Value và checksum của key khớp |
| Product catalog S3 | Xóa/ghi hỏng object dưới `m20-drill/` | Bucket hoặc prefix tách biệt | Version ID, body hash và metadata khớp |
| Terraform state | Không làm hỏng active state; chọn historical version | Temporary key/local file | JSON parse được; `lineage`, `serial`, resource count được ghi nhận |
| DynamoDB lock | Ưu tiên không corruption active lock | PITR sang table mới | Status, schema và item count đúng |
| MSK | Không xóa live topic/event | Replay archived probe vào isolated topic | Event ID, partition metadata và checksum khớp |
| GitOps | Không phá live repository | Clone từ stored bundle | `git fsck` pass và expected commit tồn tại |

RDS là corruption/PITR demonstration bắt buộc. Restore test phụ không thay thế RDS drill trừ khi mentor duyệt ADR mới.

## 12. Rollback

- Có thể revert backup plan trước Compliance Lock mà không xóa recovery point đã có.
- Backup job fail sẽ chặn rollout nhưng không được dùng làm lý do tắt native backup.
- Drill fail phải lưu verdict `FAILED_SAFE` và điều tra root cause trước khi chạy lại.
- Không xóa recovery point chỉ để làm Terraform plan xanh.
- Compliance Vault Lock không có rollback sau grace period, nên phải là approval riêng.
- Chỉ cleanup temporary resource bằng exact identifier sau khi evidence được chấp nhận.
- Application route và production secret không thay đổi nên rollback không cần chuyển traffic.

## 13. Mapping với yêu cầu Mandate #20

| Yêu cầu | Bằng chứng dự kiến | Gate hoàn thành |
|---|---|---|
| Backup mọi money-path store | Coverage matrix và cơ chế backup tự động từng store | Không còn money-path store `BLOCKED` |
| RPO/RTO từng tầng | Signed ADR và cadence contract | Số đo thực đạt target |
| Point-in-time restore | RDS restore về trước corruption vào private instance mới | Probe trên restored DB khớp checksum |
| Tested restore drill thật | Drop probe table -> PITR -> SQL validation | Mentor chứng kiến và RTO đạt cam kết |
| GitOps/IaC state dựng lại được | S3 version restore và Git bundle validation | Temporary restore pass integrity |
| DynamoDB PITR nếu có | `describe-continuous-backups` và restored table riêng | PITR bật, target tách source |
| EBS snapshot | Recovery point của active money-path volume hoặc signed N/A | Có recovery point hoặc exclusion được duyệt |
| Backup an toàn | Encryption, Vault Lock, delete-deny và break-glass owner | Operator/CI thông thường không xóa được recovery point |

## 14. Definition of Done

PM-160 chỉ hoàn thành khi:

- mọi stateful component có verdict `COVERED` hoặc `EXCLUDED` được ký;
- không còn money-path store `BLOCKED`;
- automated backup job đã tạo recovery point đúng cadence;
- ADR RPO/RTO được ký trước official drill;
- RDS controlled corruption và isolated PITR thành công;
- checksum sau restore khớp checksum trước corruption;
- RPO/RTO thực tế đạt target;
- Valkey, S3 state/catalog và MSK archive/replay có restore evidence hoặc scope decision được mentor duyệt rõ;
- recovery point encrypted và operator/CI thông thường không xóa được;
- production routing, customer data và `/flagservice` không bị thay đổi;
- storefront, browse, cart và checkout pass sau drill;
- evidence và cleanup record được mentor review.

Nếu thiếu bất kỳ điều kiện nào, trạng thái đúng là `IN PROGRESS` hoặc `BLOCKED`, không phải `DONE`.

## 15. Quyết định cần review trước khi triển khai

1. Valkey cart RPO 24 giờ có chấp nhận được không, hay bắt buộc hourly snapshot?
2. MSK archive dùng dedicated consumer hay MSK Connect sink?
3. Bucket/account nào lưu immutable Git bundle và Kafka archive?
4. Role nào là MFA-protected break-glass backup deletion owner?
5. Min/max retention và Vault Lock grace period là bao nhiêu?
6. Ba orphan EBS/PVC được exclude, giữ tạm hay cleanup có kiểm soát?
7. RDS RPO <= 5 phút và RTO <= 45 phút có được chấp nhận không?
8. Ai là mentor/witness và maintenance window nào được dùng cho drill thật?

Chỉ bắt đầu bằng các backup control có thể rollback và CI contract. Corruption/restore drill cùng Compliance Lock tiếp tục bị gate cho tới khi các quyết định trên được ghi nhận.
