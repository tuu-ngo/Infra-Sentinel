# product-reviews Sprint 3 — Báo cáo hoàn thành Release A: Tier-2 PostgreSQL fallback

**Ngày thực hiện:** 29/07/2026
**Người thực hiện:** CDO01
**Nguồn code:** AIO02 — nhánh `feature/product-review` @ `98f67031f55b6a1716b18a0431f3722a5a43c597`
**Base tích hợp:** `main` @ `19d15bef5d3339905760259019cfe2b08343caf9`
**Trụ:** Reliability · chạm Auditability
**Trạng thái:** ✅ Release A PASS — đã live production. ⚠️ Release B (S6) **OPEN**, chưa làm.
**Kế hoạch gốc:** [`docs/runbooks/aio02-product-reviews-sprint3-integration-deployment-plan.md`](runbooks/aio02-product-reviews-sprint3-integration-deployment-plan.md)
**Evidence:** [`docs/evidence/product-reviews-sprint3/`](evidence/product-reviews-sprint3/)

---

## 1. Mục tiêu & ràng buộc

Đưa phần code AI mới của AIO02 (BigUpdate Sprint 3) từ nhánh `feature/product-review` vào `main` và lên
production.

Ràng buộc do người yêu cầu đặt ra:

- **không downtime**;
- **không apply tay** — mọi thay đổi runtime đi qua PR + ArgoCD.

Giá trị nghiệp vụ của Release A: khi Bedrock lỗi / circuit breaker OPEN / rate-limit / timeout,
`AskProductAIAssistant` trả **bản tóm tắt canonical đã được duyệt gần nhất** từ PostgreSQL (Tier-2)
thay vì rơi thẳng xuống thông báo tĩnh *"The AI is busy right now"* (Tier-3).

---

## 2. Vì sao KHÔNG merge nhánh AIO

Đối chiếu hai snapshot:

```
main                     19d15be
feature/product-review   98f6703
merge-base               24e854a  (tách từ 07/07/2026)

khoảng cách: main 1.440 commit  ·  feature 14 commit
diff toàn cây: 1.314 file, +23.099 / −294.793 dòng
```

Nhánh feature **thiếu 1.440 commit của `main`**, và commit `860c116` đã chủ động xoá phần lớn cây mã
nguồn ngoài `product-reviews`. Mọi phương án sau đều bị loại: merge trực tiếp, rebase, cherry-pick cả
chuỗi, checkout đè thư mục.

Cụ thể, merge/copy nguyên nhánh sẽ **mất** các fix production sau:

| Safeguard trên `main` | Nhánh AIO |
|---|---|
| Readiness DB-aware (REL-02) — pod mất RDS bị rút khỏi Service | Trả `SERVING` vô điều kiện |
| Admission control PM-0016 (semaphore cap 4, shed 50ms) | Đã gỡ |
| `GRPC_MAX_WORKERS` env-tunable, mặc định 12 | Hardcode 50 |
| Connection pool 1/10 + xử lý `PoolError` (REL-05) | Pool 5/30, rebuild khi cạn → rò connection |
| Dockerfile digest-pinned, vá OpenSSL, non-root 65532 | Bỏ hết, **kể cả `COPY migration.sql`** |
| `migration.sql` dùng `CREATE INDEX CONCURRENTLY` + grant sequence | Hạ xuống `CREATE INDEX` thường, bỏ grant |

Đáng chú ý: nhánh AIO thêm bảng mới mà `migration.sql` cần, nhưng Dockerfile của chính nó lại xoá dòng
`COPY migration.sql` — **tính năng không chạy được như bàn giao**.

→ Phương án thực hiện: **port chọn lọc theo từng hunk** lên nhánh mới tách từ `origin/main`.

---

## 3. Phạm vi đã port

**Đã lấy:**

- `reviews.product_summaries` — schema + grants (append vào `migration.sql`, giữ nguyên Step 1–4 của `main`);
- `save_product_summary()` / `fetch_product_summary_from_db()` trong `database.py`;
- `resolve_fallback_summary()` + nối vào **7 đường fallback** hiện có;
- persist bản tóm tắt sau khi judge duyệt;
- label `tier` cho metric `app_ai_fallback_total`;
- 3 file test tương thích sẵn của AIO.

**Cố ý không lấy** — toàn bộ nhóm ở §2, cộng thêm:

- hunk trong `guardrails/fallback.py`: **dead code**, cả hai caller đều gọi `handle_exception(e)` không
  truyền `product_id`;
- `BEDROCK_GUARDRAIL_ID=3ab7r29x59x4`: ID thuộc **AWS account khác**, bật lên sẽ `AccessDenied` mọi lệnh gọi;
- nhóm thay đổi hành vi trả lời AI (2 deterministic router mới, viết lại prompt, ép output tiếng Anh,
  nới regex off-topic) — hoãn sang PR riêng vì **chưa có eval set** (AIO-15) chứng minh là cải thiện;
- Release B / S6 — xem §11.

Diff cuối: **3 file sửa + 6 file thêm**, đều nằm trong allowlist của kế hoạch; **không đụng file nào
trong denylist** (`values-aio-llm.yaml`, `infra/iam.tf`, chart templates, `values.schema.json`, `.env.override`).

**flagd giữ nguyên tuyệt đối:** `llmInaccurateResponse`, `llmRateLimitError`, `check_feature_flag`,
`FlagdProvider` — không đổi một dòng, và có test assert trên source để khoá lại.

---

## 4. Hai lỗi nghiệp vụ trong code AIO — đã vá khi port

### 4.1 Persist không giới hạn theo intent

Bảng khoá theo `product_id`, mỗi sản phẩm giữ **đúng một** bản tóm tắt. Nhưng code AIO persist **mọi**
câu trả lời có `judge_status ∈ {approved, deterministic}`, không hề kiểm tra loại câu hỏi.

Kịch bản hỏng, đi từ đầu đến cuối:

1. User A hỏi *"Is this waterproof?"* → trả `"No reviews mention waterproofing."`
2. Câu đó được ghi thành **bản tóm tắt** của sản phẩm.
3. Circuit breaker mở. User B hỏi *"Summarize the customer reviews"*.
4. Tier-2 trả lại đúng câu trả lời chống nước kia.

`judge_status` một mình không chặn được: `"deterministic"` đến từ các router trả lời câu hỏi hẹp, còn
`"approved"` áp cho **mọi** câu trả lời grounded khi `judge_all_grounded_answers` bật.

**Vá:** thêm gate `is_summary_request(safe_question)` vào điều kiện persist.

### 4.2 Không kiểm tra `review_version`

Code AIO **có** đọc `review_version` từ DB nhưng **không bao giờ** so với version hiện tại. Hệ quả: trả
bản tóm tắt mô tả một tập review đã thay đổi. Đó là câu trả lời **sai**, không phải câu trả lời cũ.

**Vá:** `resolve_fallback_summary()` so `review_version` lưu kèm với `get_review_version()` hiện tại;
lệch hoặc NULL thì rơi Tier-3 (fail closed).

### 4.3 Thay đổi thứ ba: đưa persist ra khỏi đường nóng

Code AIO ghi DB **đồng bộ** trong khối `finally`, cộng một round-trip RDS vào p99 của **mọi** câu trả lời
AI thành công — cho một bản ghi chỉ phục vụ sự cố trong tương lai. Đã chuyển sang `db_write_executor`,
đúng pattern `log_fidelity_audit_async` mà `main` có sẵn.

### 4.4 Test của AIO đang khẳng định cả hai hành vi lỗi là ĐÚNG

`test_fallback_tier2.py:52-69` dựng summary `review_version="v1_old"` trong khi version hiện tại là
`"v1_test"`, rồi assert summary **vẫn được trả**. `test_summary_persistence.py` assert câu hỏi
*"Is this product good?"* **được persist**.

→ Hai file này đã được **viết lại**, không mang sang.

---

## 5. Test

Service này trước đó **chưa từng có test nào chạy trong CI**.

| File | Xử lý |
|---|---|
| `test_tool_validator.py`, `test_circuit_breaker.py`, `test_database_summary.py` | Port nguyên từ AIO |
| `test_fallback_tier2.py` | Viết lại — khớp version → Tier-2; lệch / NULL / DB lỗi / bảng rỗng → Tier-3 |
| `test_summary_persistence.py` | Viết lại — chỉ câu hỏi summary mới persist; ghi DB hỏng không làm hỏng response |
| `test_main_safeguards.py` | **Mới** (CDO-04) — khoá readiness DB-aware, admission control, xử lý `PoolError`, và cả 3 đường đọc flagd |
| `test_runtime_guardrails.py`, `test_error_injection.py` | Chưa lấy — gắn với nhóm thay đổi hành vi AI đang hoãn |

`test_main_safeguards.py` tồn tại vì trước đây **không test nào bảo vệ ba safeguard đó**, nên nhánh AIO gỡ
được cả ba mà không có gì báo. Giờ gỡ là CI đỏ, kèm lý do trong docstring.

**Kết quả:** 55/55 xanh trên `python:3.12` (khớp runtime image).

**Kiểm chứng test có tác dụng thật (mutation test)** — gỡ hai chỗ vá ở §4 thì 4 test đỏ ngay:

```
FAILED test_fallback_tier2.py::TestTier2VersionGuard::test_null_version_falls_through_to_tier3
FAILED test_fallback_tier2.py::TestTier2VersionGuard::test_stale_version_falls_through_to_tier3
FAILED test_summary_persistence.py::TestPersistenceIntentGate::test_narrow_question_approved_is_not_persisted
FAILED test_summary_persistence.py::TestPersistenceIntentGate::test_narrow_question_deterministic_is_not_persisted
  AssertionError: Expected 'save_product_summary_async' to not have been called.
  Calls: [call('PROD001', 'The average score is 4.2.', 'v1_test')]
```

Dòng cuối chính là kịch bản hỏng ở §4.1 hiện ra nguyên hình.

**CDO-03:** thêm workflow `.github/workflows/product-reviews-tests.yml`, chạy trên PR và push `main`.

---

## 6. Migration qua GitOps — không apply tay

`gitops/jobs/product-reviews-schema-migration.yaml` (bản cũ) **cố ý** nằm ngoài ArgoCD và phải
`kubectl apply` tay, nên không dùng được cho ràng buộc lần này.

Đã tạo **Application riêng** `product-reviews-schema-migration` trỏ vào
`gitops/jobs/product-reviews-sprint3/`. App-of-apps tự nhặt → merge PR là Argo apply Job.

Ba lựa chọn cấu hình dễ bị hiểu nhầm là thiếu sót, đều có lý do:

| Cấu hình | Lý do |
|---|---|
| **không** `ttlSecondsAfterFinished` | TTL xoá Job trong khi nó **vẫn còn trong git** → Argo thấy thiếu resource → tạo lại → migration chạy lặp |
| `selfHeal: false` | PodTemplate của Job là **immutable**; selfHeal sẽ liên tục thử patch một resource không patch được |
| `prune: true` | Chỉ dọn khi file **đã rời khỏi git** — đúng thứ cần, không gây lặp |

**Verify mở rộng (CDO-05):** `CREATE TABLE IF NOT EXISTS` vẫn báo thành công khi bảng cũ **sai schema**,
nên `to_regclass` một mình không kết luận được gì. Job kiểm và **exit 1** nếu sai: từng cột
(type/length/nullable/default), primary key, owner, grants, và **probe upsert thật trong transaction rồi
`ROLLBACK`** xác nhận không để lại row.

**Kết quả:**

```
SCHEMA MIGRATION OK
  [OK ] productreviews.is_safe / prod_safe_idx valid / fidelity_audit exists
  [OK ] column set + cả 5 cột đúng type/length/nullable
  [OK ] updated_at has default: CURRENT_TIMESTAMP
  [OK ] primary key: ['product_id']
  [OK ] probe upsert+read / probe rolled back cleanly: 0
SCHEMA VERIFICATION OK
```

---

## 7. Rollout

Trình tự, mỗi bước là một cổng riêng:

```
PR #590  code + test + docs        → không deploy, digest chưa đổi
         CI build → Trivy → Cosign → bot mở PR #593
PR #591  Application + Job migration (pin digest candidate)
         → Argo apply Job → SCHEMA VERIFICATION OK
PR #593  image bump                → Argo rolling deploy
```

Ràng buộc kỹ thuật buộc phải theo thứ tự này: `build-push-ecr.yml` **chặn dispatch từ nhánh không phải
`main`**, nên không thể build image candidate từ nhánh feature — PR code phải merge trước.

Digest candidate `sha256:be5cd78a…` được kiểm trước khi pin vào Job: OCI image index có cả
`linux/amd64` và `linux/arm64`, Trivy pre+post-push HIGH/CRITICAL sạch, Cosign `Verified OK`.

---

## 8. Kết quả — không downtime

```
07:06:19  img=old  ready/avail/upd/total=2/2/2/2
07:06:34  img=NEW  2/2/1/3   surge pod rjhbh@ip-10-0-42-133  Pending
07:06:50  img=NEW  2/2/2/3   rjhbh Running/True, d67zz@ip-10-0-0-54 Pending
07:07:06  img=NEW  2/2/2/2   cả hai pod mới Running/True
```

| Chỉ số | Kết quả |
|---|---|
| Thời gian rollout | 45 giây |
| `readyReplicas` | **không lúc nào tụt dưới 2** |
| Restart | 0 |
| Read path đo liên tục xuyên rollout | **45/45 request trả `200`, 0 lỗi** |
| `product-catalog` / `accounting` | 2/2 · 1/1 — không ảnh hưởng |
| ArgoCD | `Synced` / `Healthy` |

Bảo đảm bởi `maxUnavailable: 0` + PDB `minAvailable: 1`.

---

## 9. Verify Tier-2 trên production

**Đường ghi — ĐÃ kiểm chứng:**

```
AI_OUTCOME product_id=L9ECAV7KIM stage=runtime_judge outcome=approved
[DATABASE] Saved static summary for product_id: L9ECAV7KIM
[DB_SUMMARY] Persisted canonical summary product_id=L9ECAV7KIM version=0c21528a59c7
```

Gate `is_summary_request` hoạt động đúng qua storefront thật:

| Câu hỏi | Đường đi | Persist? |
|---|---|---|
| *"Can you summarize the customer reviews?"* | `[CACHE] Hit!` → return sớm | Không — đúng, cache hit không ghi lại |
| *"Is this product waterproof?"* | cache miss → `outcome=no_info`, judge `skipped` | **Không** |
| *"Please give me an overview of what customers say in their reviews"* | cache miss → `outcome=approved` | **Có** |

> ### ⚠️ Đường đọc — CHƯA kiểm chứng end-to-end
>
> Mới chứng minh được **ghi**. Việc **đọc** — fallback thật sự trả bản tóm tắt với `tier=2`, và rơi
> `tier=3` khi `review_version` lệch — đòi bơm lỗi LLM vào production (`llmRateLimitError` gây lỗi cho
> **~50% request thật**). Đó là thay đổi ảnh hưởng người dùng, nên **chưa làm, chờ quyết định**.
>
> Đường đọc hiện chỉ được bảo đảm bằng unit test đã mutation-verified.
>
> **Không kết luận "Tier-2 hoạt động đầy đủ trên production"** cho tới khi làm xong.

---

## 10. Sự cố nhỏ trong quá trình và cách xử lý

**Job migration lần đầu exit 1 — nhưng migration đã thành công.** Job assert `otelu` không có quyền
`DELETE`; thực tế `otelu` là **owner** của bảng, mà owner trong PostgreSQL mặc nhiên có toàn quyền và
`role_table_grants` báo cả quyền owner. **Assertion đó không thể nào đúng.**

Đây không phải vấn đề mới sinh: `reviews.fidelity_audit` trên `main` cũng do `otelu` tạo với `GRANT` y
hệt — cũng là no-op từ trước.

Đã sửa assertion cho đúng ({SELECT, INSERT, UPDATE} ⊆ privileges; chỉ kiểm "không DELETE" khi bảng không
do `otelu` sở hữu), chạy lại Job dưới tên `-r2`, kết quả `SCHEMA VERIFICATION OK`.

**Đính chính đã ghi vào decision log AIO-07:** khẳng định ban đầu "không cấp `DELETE`" là **sai**.
Least privilege thật cần bảng do role admin sở hữu rồi mới `GRANT` — **ghi nhận OPEN**.

---

## 11. Sai sót của người thực hiện

Ghi lại để không lặp lại, cả hai đều **không gây hại production**:

**11.1 — Một PR thừa (#594 → revert #601).** Preflight lúc 06:20 kết luận pod surge sẽ hết chỗ do nodepool
ARM của CDO01 thêm taint. Kết luận đó đúng **tại thời điểm đo**, nhưng CDO01 đã tự xử lý lúc ~06:37 bằng
`187c55c feat: migrate product reviews to ARM`. Người thực hiện **khuyến nghị merge lúc 06:55 mà không
kiểm tra lại `main`**, dù đã biết CDO01 đang làm dở việc ARM.

Kết quả: `values-mandate13.yaml` là file **#4**, load **sau** `values-prod.yaml` (#3), và `tolerations` là
**list** nên Helm **THAY THẾ** cả list → thay đổi ở `values-prod.yaml` **không bao giờ tới output**. Đã
kiểm chứng bằng render: có hay không có #594 đều ra 22.908 dòng giống hệt nhau.

Cách CDO01 làm còn đúng hơn: ghim `arch=arm64` làm số domain của topologySpread **giảm từ 4 xuống 2**, nên
`2,1 → skew 1` thoả `maxSkew=1`. Pool amd64 cap cứng ở 2 node và đã đầy — đó mới là chỗ kẹt thật.

**11.2 — Khẳng định sai trong decision log** (xem §10).

Bài học đã ghi vào `CLAUDE.md` để phiên sau không rơi lại vào bẫy values-prod vs values-mandate13.

---

## 12. Còn OPEN — không gộp vào kết luận Release A

| Hạng mục | Ghi chú |
|---|---|
| **Release B / S6 isolation** | Xem §13 |
| **Đường đọc Tier-2** | Chưa verify end-to-end trên production (§9) |
| Nhóm thay đổi hành vi trả lời AI | 2 deterministic router, prompt rewrite, ép tiếng Anh, regex off-topic — **cần eval set của AIO02 (AIO-15)** |
| Bedrock Guardrail | Cần ARN hợp lệ trong account `197826770971`; PR Terraform riêng |
| Least privilege `product_summaries` + `fidelity_audit` | Bảng do `otelu` sở hữu → `GRANT` không thu hẹp được gì |
| CDO-06 | Candidate Deployment tách selector cho smoke |
| CDO-11 | CI mới render **3/6** lớp values — lỗi ở 3 lớp còn lại chỉ lộ ra khi ArgoCD `ComparisonError`, chết cả Application |

---

## 13. Đánh giá Release B — có cần làm không

**Có, nhưng chưa gấp, và phải thiết kế lại chứ không port bản của AIO.**

**Mục đích:** làm cho độ trễ read RPC **độc lập với tải AI**. Hiện `GetProductReviews`,
`GetAverageProductReviewScore` và `AskProductAIAssistant` dùng chung **một** `ThreadPoolExecutor`, phát
theo **FIFO** — nên read RPC nhanh phải xếp hàng sau các lệnh AI chậm và vỡ deadline 500ms. Đó chính là
`DEADLINE_EXCEEDED` trong postmortem 0016.

**Cái đang có chỉ giảm nhẹ.** Semaphore trên `main` chạy **bên trong handler**, tức là **sau khi** task đã
ra khỏi hàng đợi FIFO và được cấp worker — nó **không sắp xếp lại hàng đợi chung**. Số đo trong postmortem:

| Burst | Độ trễ read RPC |
|---|---|
| N=10 | ~34ms |
| N=30 | ~178ms |
| N=100 | **~758ms** — vượt deadline 500ms |

**Bản S6 của AIO không đạt mục đích:** `future.result(timeout=15.0)` khiến thread handler **vẫn đứng chờ**,
gRPC worker không được giải phóng; hàng đợi **không giới hạn** nên không shed được; chờ **15 giây** trong
khi client đã bỏ đi từ giây 0.5; timeout **không cancel** future. Nó thay một cơ chế có tác dụng bằng một
cơ chế không có tác dụng.

**Vì sao chưa gấp:** sau khi có cache Redis + circuit breaker, đo lại kịch bản 500 user thì Bedrock throttle
**không còn tái hiện**. Nhưng đó là cache đang **che** vấn đề — rủi ro kiến trúc vẫn nguyên, và sẽ lộ ra khi
cache miss hàng loạt (review đổi → `review_version` đổi → invalidate) hoặc Redis chết.

**Đề xuất:** xếp vào backlog có ưu tiên, làm theo P3 của postmortem — **tách `AskProductAIAssistant` thành
Deployment/Service riêng**, bulkhead ở mức tiến trình. Khi làm **bắt buộc** load test đúng hai kịch bản
cache miss và Redis down, vì đó mới là lúc vấn đề thật sự xuất hiện.

---

## 14. Kết luận

Tier-2 PostgreSQL fallback đã live production, **không downtime** (45/45 request `200`, replica không tụt
dưới 2), migration chạy qua ArgoCD **không apply tay**, và toàn bộ safeguard reliability của `main` còn
nguyên — có test khoá lại để lần port sau không gỡ mất.

Hai lỗi nghiệp vụ trong code AIO đã được vá **kèm test chứng minh test có tác dụng**, chứ không chỉ port
nguyên trạng.

Phần chưa xong được ghi rõ chứ không gộp vào kết luận: **đường đọc Tier-2 chưa verify end-to-end**, và
**Release B chưa làm**.

---

*Ký: CDO01 — 29/07/2026*
*PR: #590 (code) · #591 + #598 (migration) · #593 (image bump) · #600 / #601 / #603 (dọn dẹp) · #605 (CLAUDE.md)*
*Liên quan: postmortem 0016 · PM-101 (supply-chain gate) · REL-02 · REL-05 · Mandate #13 (ARM)*
