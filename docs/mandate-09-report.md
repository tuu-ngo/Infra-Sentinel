# CDO-02 — Mandate #9: Báo cáo M9-01 & quyết định DỪNG mandate

> **Nhóm:** CDO-02 · **Trụ:** Reliability + Cost Optimization · **Người làm:** Lê Văn Hải
> **Ngày:** 31/07/2026 · **Account:** `197826770971` (`ap-southeast-1`)
> **Liên quan:** solution [`mandate-09-zero-downtime-ops-solution.md`](docx_cdo02/mandate-09-zero-downtime-ops-solution.md) ·
> WBS [`mandate-09-work-breakdown.md`](docx_cdo02/mandate-09-work-breakdown.md) ·
> trình bày [`CDO02-TRINH-BAY-MANDATE-9-VA-12.md`](CDO02-TRINH-BAY-MANDATE-9-VA-12.md)

**⚠️ Trung thực đặt ngay đầu:**
1. Mandate #9 **KHÔNG đóng "xanh"**. Chỉ **một task (M9-01)** được code + unit-test xong trên **nhánh
   feature**, **chưa merge `main`, chưa deploy, chưa có live chaos evidence**. 21 task còn lại **chưa làm**.
2. Đây là **quyết định DỪNG có chủ đích**, không phải bỏ dở âm thầm — lý do + trạng thái bàn giao ghi ở §4–§6.
3. **Ảnh hưởng production = 0** (M9-01 chưa deploy); **không đảo ngược** bất kỳ kết quả nào của Mandate #8.

---

## 0. Tóm tắt điều hành

| Hạng mục | Trạng thái | Một dòng |
|---|---|---|
| **M9-01** — catalog stale-cache + readiness startup-latch (Go) | 🛠️ **Code + test xong (nhánh feature)** | Nền read-path chống-failover cho `product-catalog`: cache in-memory + latch, 18 hàm test PASS, **chưa deploy** |
| **Phần còn lại Mandate #9** (21 task: reviews cache, accounting idempotent, rotation, schema migration, MSK/RDS upgrade, param reboot, rehearsal, prod W1/W2…) | 🛑 **DỪNG — chưa bắt đầu** | Mới ở mức **thiết kế** trong solution v3.2; quyết định không thực thi |

**Quyết định:** **dừng Mandate #9** sau khi hoàn tất M9-01 (code+test). Ba lý do (chi tiết §4):
1. **Thời gian có hạn** — Phase 3 kết thúc 31/07; lịch an-toàn-sớm-nhất của mandate kéo tới **13/08** (vượt hạn).
2. **Conflict với hệ thống sống các nhóm khác đang dùng** — các change-window còn lại thao tác trực tiếp lên
   RDS/MSK/ElastiCache + cluster **dùng chung**, trong khi các nhóm khác đang chạy mandate khác trên cùng account.
3. **Mandate #9 KHÔNG bắt buộc với nhóm** — directive quy định "mỗi đội chỉ làm **một trong hai** #8/#9"; TF3 **đã
   hoàn tất #8** (3/3 store lên managed, mentor PASS) nên #9 là tuỳ chọn.

→ Chốt: **nhường hệ thống** (các cửa sổ thay đổi trên store/cluster sống) cho các nhóm đang chạy mandate **bắt
buộc**, tránh giẫm chân và rủi ro sự cố chéo. M9-01 giữ lại ở nhánh feature làm nền, nối tiếp được nếu cần.

---

## 1. Bối cảnh — Mandate #9 lớn cỡ nào

Mandate #9 = **sau khi đã lên managed, vẫn phải thay đổi hạ tầng dữ liệu dưới tải mà 0 request khách rớt** — 5 yêu
cầu: (1) online schema migration; (2) nâng major version; (3) đổi param cần reboot; (4) xoay credential live;
(5) app nuốt được blip khi kết nối đổi.

Solution v3.2 + WBS chia thành **22 task, 4 người** (Hải/Đức/Đông/Mến), lịch earliest-safe: staging-ready 05/08 →
rehearsal PASS 10/08 → prod W1 11/08 → bake ≥24h → prod W2 (FINAL) 13/08. Đây là **bài khó nhất nhóm managed** và
cần **staging MSK cluster thật** (~$18–25/ngày) + **cửa sổ mentor quan sát** cho các thao tác một-chiều.

---

## 2. ĐÃ LÀM — M9-01 (catalog stale-cache + readiness startup-latch)

**Nhánh:** `feat/m9-01-catalog-stale-cache-readiness-startup-latch-go` · **commit code:** `c8958ec`
(nhánh đã merge `main` vào để đồng bộ; **chưa merge ngược vào `main`** — verify:
`git merge-base --is-ancestor <branch> origin/main` → sai).

### 2.1 Nội dung (chỉ sửa `src/product-catalog/main.go`, +`main_test.go`)

| Khả năng | Cơ chế | Bằng chứng |
|---|---|---|
| list/get/search **không chạm DB** trên đường khách | `productSnapshot` bất biến, swap bằng `atomic.Pointer`; get=map, search=lọc in-memory giữ semantics `LOWER(name/desc) LIKE` | `main.go`; test `TestCacheList/Get/Search` |
| DB down mà **browse vẫn phục vụ** (serve stale) | prime→refresh 30s; refresh lỗi **giữ last-known-good**, không xoá cache | test `TestRefreshFailureKeepsLastKnownGood` |
| Pod **không bị rút khỏi endpoints** khi DB down | **Startup-latch**: `ready() = ever_primed && !shutdown && cache_schema_valid`; DB reachability **không** nằm trong readiness (chỉ degraded-signal). Ép `""`=NOT_SERVING trước `Serve()` đóng race | test `TestReadinessStartupLatch`, `TestReadinessSchemaMismatch` |
| Cold-start giữa outage **không CrashLoop** | decouple gRPC start khỏi DB init (handle lazy), prime nền; liveness `tcpSocket` độc lập DB | notes §2.3 |
| Nuốt blip ngắn | retry **4 lần / 100+200+400ms = 700ms**, transient-only; `ConnMaxLifetime` 5m→60s | test `TestRetryBudgetIs700ms`, `TestLoadWithRetry*` |
| Quan sát outage | metric `cache_primed`/`ever_primed`/`cache_age_seconds`/`served_stale_total`/`db_retry_*` | test `TestMetricsInstrumentsAndServedStale` |

### 2.2 Kiểm chứng (chạy lại được từ source)

| Chỉ số | Giá trị | Cách đo |
|---|---:|---|
| Số hàm test | **18** (19 test-case tính cả subtest) | `grep -c '^func Test' main_test.go` |
| `go build` (single-file kiểu Dockerfile) + `go vet` + `gofmt` | **OK / sạch** | container `golang:1.26.5-bookworm` |
| `go test -race ./...` | **PASS** | container `golang:1.26.5-bookworm` |
| Budget retry blip | **700ms** (4 lần) | hằng số `retryBackoffs` + test |

### 2.3 Sản phẩm bàn giao (đều nằm trên nhánh feature)
- Code: [`product-catalog/main.go`](<../phase3 - information/techx-corp-platform/src/product-catalog/main.go>) + [`main_test.go`](<../phase3 - information/techx-corp-platform/src/product-catalog/main_test.go>)
- Ghi chú triển khai: [`docx_cdo02/mandate-09-m9-01-catalog-implementation-notes.md`](docx_cdo02/mandate-09-m9-01-catalog-implementation-notes.md)
- Chaos runbook + alert 15′: [`runbooks/mandate-09-m9-01-catalog-cache-chaos.md`](runbooks/mandate-09-m9-01-catalog-cache-chaos.md)

### 2.4 Trạng thái đúng mức
**"Đã code + đã unit-test"**, KHÔNG phải "đã trên production". Acceptance duy nhất **còn dở** của M9-01 là
**live chaos 60–120s** (pod trong endpoints, browse 200 stale, cold-start không vào endpoints) — cần image deploy
mới đo được, thuộc bước integration/rehearsal đã dừng.

---

## 3. CHƯA LÀM — phần còn lại của Mandate #9

Không task nào dưới đây được bắt đầu (mới ở mức thiết kế trong solution v3.2):

| Pha | Task | Owner (WBS) | Việc | Trạng thái |
|---|---|---|---|---|
| Nền tảng | M9-00 | Đông | Bộ đo "error=0" + load harness + timeout budget | ❌ chưa làm |
| Nền tảng | M9-02 | Đông | reviews: cache customer-path + negative-cache + latch (Python) | ❌ |
| Nền tảng | M9-03 | Đức | accounting idempotent (23505) + bump producer | ❌ |
| Chuẩn bị | M9-04 | Mến | 3 rotation scope (alternating-users) + Lambda network + ESO | ❌ |
| Chuẩn bị | M9-05a/b/c | Đức/Hải/Đông | generation reload (accounting/.NET · catalog/Go · reviews/Py) | ❌ (M9-05b nối tiếp M9-01) |
| Chuẩn bị | M9-07d/07i | Đức | schema design + implementation (dual-write/A-B/contract) | ❌ |
| Chuẩn bị | M9-08 | Mến | param `pg_stat_statements` (pending-reboot) plan/runbook | ❌ |
| Chuẩn bị | M9-10 | Mến | MSK 3.9→4.0 prep + client gate + staging cluster plan | ❌ |
| Chuẩn bị | M9-06 | Hải | integration dormant-mode + staging-ready | ❌ |
| Chuẩn bị | M9-11 | Mến | ADR hợp nhất + runbook/evidence pack | ❌ |
| Tổng duyệt | M9-12 | All | staging rehearsal (RDS clone + MSK staging thật) | ❌ |
| Demo | M9-13 | All | **PROD W1**: 4 thao tác, schema pre-contract | ❌ |
| Demo | M9-14 | Đức | **PROD W2**: contract `SET NOT NULL` + `DROP COLUMN` | ❌ |
| Gate | M9-15a/b/c | Đức/Hải | mentor design sign-off + prod W1/W2 approval | ❌ |
| Bonus/post | M9-09, M9-16 | Mến | RDS 17→18 Blue/Green · IAM DB auth | ❌ |

**Bốn cửa sổ thay đổi cốt lõi (compliance #1–#4) — chưa thực thi cái nào:**
schema migration (expand→dual-write→backfill→validate→contract) · MSK 3.9→4.0 rolling · RDS reboot-with-failover
(đổi param) · Secrets Manager alternating-users rotation.

---

## 4. VÌ SAO DỪNG (3 lý do)

### 4.1 Thời gian có hạn
Phase 3 kết thúc **31/07/2026**. Lịch **earliest-safe** trong WBS (đã tính ngày làm việc, không rút ngắn được):
staging-ready 05/08 · rehearsal PASS 10/08 · prod W1 11/08 · bake ≥24h · prod W2/FINAL **13/08** — **vượt hạn ~2
tuần**. Chính solution cấm "rút ngắn rehearsal/bake để giữ ngày" (thao tác một-chiều trên store sống, sai là mất
đơn/kẹt partition). Không có đường ép mandate này vào hạn mà vẫn an toàn.

### 4.2 Conflict với hệ thống các nhóm khác đang dùng
Phần còn lại của #9 **không phải code app** — nó là **thao tác phá vỡ trên hạ tầng dữ liệu SỐNG dùng chung**:
reboot-with-failover RDS (ngắt 60–120s toàn cục), rolling upgrade MSK từng broker, DDL trên bảng
`accounting.orderitem`/`catalog.products`, xoay credential của cả 3 app-user. RDS/MSK/ElastiCache + cluster
`techx-corp-tf3` là **tài nguyên chung của cả TF**, trong khi các thành viên khác **đang chạy mandate khác trên
đúng account/cluster đó** (ví dụ CDO01 đang dở batch Karpenter — CLAUDE.md ghi rõ *"đừng đụng nodegroup khi họ chưa
xong"*; tiền lệ **sự cố 20/07** NetworkPolicy gây outage checkout ~30ph). Mở các cửa sổ thay đổi của #9 song song
= **rủi ro sự cố chéo cao + khó quy trách nhiệm** (một khi cửa sổ mở, mọi customer-fail đều làm gate FAIL bất kể
root cause). Cần **freeze window + mentor quan sát riêng** — chi phí phối hợp lớn.

### 4.3 Mandate #9 không bắt buộc với nhóm
Directive #9 ghi rõ: **áp cho TF đã ở managed từ trước; đội chưa managed làm Directive #8 thay — "mỗi đội chỉ làm
một trong hai"**. TF3 **chưa managed từ trước** và đã **hoàn tất Directive #8** (Valkey→ElastiCache, Postgres→RDS,
Kafka→MSK; 3/3 store, zero-loss/zero-downtime, **mentor PASS**). Theo luật "một trong hai", nhóm **đã thoả nghĩa
vụ** ở #8 → **#9 là tuỳ chọn**, không phải điều kiện đóng Phase 3.

**Kết luận:** giá trị biên của việc cố hoàn tất một mandate **không bắt buộc**, **vượt hạn**, lại **phải giành hạ
tầng sống** với các nhóm đang chạy mandate **bắt buộc** → **không đáng**. Dừng #9, **nhường hệ thống** cho các nhóm
đó, là lựa chọn đúng về cả rủi ro lẫn phối hợp.

---

## 5. Ảnh hưởng & rủi ro khi dừng

| Khía cạnh | Đánh giá |
|---|---|
| **Production hiện tại** | **0 thay đổi** — M9-01 chưa deploy; không có gì để rollback. |
| **Kết quả Mandate #8** | **Nguyên vẹn** — 3 store managed Multi-AZ vẫn HA; không SPOF datastore. Dừng #9 **không** đụng #8. |
| **Cái không có** | Bằng chứng zero-downtime cho migration/upgrade/reboot/rotation dưới tải. Vì #9 **không bắt buộc** → chấp nhận được, khai báo minh bạch (không claim PASS). |
| **Nợ kỹ thuật xấu** | **Không** — M9-01 là nhánh feature độc lập, không merge nên không ảnh hưởng ai; `main` sạch. |
| **Chi phí tránh được** | Không dựng **staging MSK cluster** (~$18–25/ngày) + staging RDS clone — phù hợp bối cảnh ngân sách đang sát trần. |

---

## 6. Trạng thái bàn giao & cách nối lại (nếu chương trình gia hạn / nhóm khác tiếp)

**Giữ lại nguyên trạng, không cần dọn:**
- Nhánh `feat/m9-01-catalog-stale-cache-readiness-startup-latch-go` (commit `c8958ec`) — code + test + runbook + notes.
- Solution v3.2 + WBS + implementation notes — điểm khởi đầu đầy đủ (4 người, lịch, dependency, risk).

**Đường nối lại M9-01 → live (ngắn nhất để lấy evidence):**
```
merge main  →  CI build image (build-push-ecr)  →  bump imageOverride digest trong values-prod.yaml
   →  ArgoCD sync (verify 2/2 Ready, ever_primed=1, cache_age_seconds < 30s)
   →  chạy chaos runbook (RDS reboot/failover, browse 200 stale, 0 fail; cold-start không vào endpoints)
```
**Nối lại cả mandate:** theo đúng critical path WBS (M9-00/03/04 chạy song song trước → M9-07/08/10 → integration
M9-06 → rehearsal M9-12 trên staging → prod W1/W2). Cần mentor gia hạn (M9-15a) làm hard-gate.

---

## 7. Đánh đổi — cố ý KHÔNG làm gì (để minh bạch)

| Việc đã cân nhắc | Vì sao không làm |
|---|---|
| Cố ép prod W1/W2 vào trước 31/07 | Phải cắt rehearsal/bake — solution cấm; thao tác một-chiều trên store sống, sai = mất đơn/kẹt partition |
| Merge + deploy M9-01 luôn "cho có số live" | Deploy + chaos là scope integration/M9-00, cần image build + cửa sổ có kiểm soát; deploy vội lên cluster chung = rủi ro không cần thiết |
| Chạy các change-window #9 song song mandate nhóm khác | Giành hạ tầng sống dùng chung → rủi ro sự cố chéo; #9 không bắt buộc nên không đáng đánh đổi |
| Dựng staging MSK cluster để rehearsal | ~$18–25/ngày, chỉ để phục vụ mandate tuỳ chọn — không hợp lý khi ngân sách sát trần |

---

## 8. Kết luận

Nhóm CDO-02 **hoàn tất phần nền read-path (M9-01) ở mức code + unit-test** và **chủ động dừng phần còn lại của
Mandate #9**, vì mandate này **không bắt buộc** với nhóm (đã làm #8), lịch an toàn **vượt hạn 31/07**, và các cửa sổ
thay đổi còn lại sẽ **giành hạ tầng sống** với các nhóm đang chạy mandate bắt buộc. Quyết định ưu tiên **an toàn hệ
thống chung + phối hợp** hơn là cố đóng một mandate tuỳ chọn. Toàn bộ thiết kế + M9-01 được giữ lại, **nối tiếp
được** nếu chương trình gia hạn hoặc nhóm khác muốn tiếp nhận.

---

### Phụ lục — Chỉ mục bằng chứng (kiểm chứng 31/07)

| Loại | Đường dẫn / lệnh |
|---|---|
| Solution | [`docx_cdo02/mandate-09-zero-downtime-ops-solution.md`](docx_cdo02/mandate-09-zero-downtime-ops-solution.md) |
| WBS | [`docx_cdo02/mandate-09-work-breakdown.md`](docx_cdo02/mandate-09-work-breakdown.md) |
| Implementation notes | [`docx_cdo02/mandate-09-m9-01-catalog-implementation-notes.md`](docx_cdo02/mandate-09-m9-01-catalog-implementation-notes.md) |
| Chaos runbook | [`runbooks/mandate-09-m9-01-catalog-cache-chaos.md`](runbooks/mandate-09-m9-01-catalog-cache-chaos.md) |
| Code (nhánh) | `product-catalog/main.go` + `main_test.go` trên `feat/m9-01-catalog-stale-cache-readiness-startup-latch-go` |
| Chưa vào main | `git merge-base --is-ancestor c8958ec origin/main` → sai (NOT in main) |
| Đếm test | `git show <branch>:".../product-catalog/main_test.go" \| grep -c '^func Test'` → **18** |
| Nền #8 (đã PASS) | [`mandate-08-bao-cao-tong-ket.md`](mandate-08-bao-cao-tong-ket.md) · ADR [`adr/0009-mandate-08-managed-migration-cdo02.md`](adr/0009-mandate-08-managed-migration-cdo02.md) |

*Mọi trạng thái phản ánh đúng hiện trạng 31/07/2026. Phần chưa deploy / chưa làm được ghi rõ, không tô xanh quá mức.*
