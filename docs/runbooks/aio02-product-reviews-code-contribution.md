# Runbook — AIO02 sửa code `product-reviews` và đưa lên production

**Đối tượng:** AIO02 (người viết code AI) · **Người viết:** CDO01 · **Ngày:** 29/07/2026
**Bối cảnh:** đợt port bản AIO02 ngày 28/07 (PR #554 → #559) mất trọn 1 ngày vì code được viết ở repo
khác rồi phải diff tay từng file, và 4 bug phải chặn thủ công trước khi lên production. Runbook này để
lần sau **AIO02 sửa thẳng trong repo này** và **không lặp lại 4 bug đó**.

**Tài liệu liên quan:** [báo cáo 28/07](../pm-0016-bao-cao-cong-viec-28-07.md) ·
[postmortem PM-0016](../postmortem/0016-product-reviews-deadline-exceeded-under-synthetic-load.md) ·
[runbook Bedrock rollout](aio-bedrock-rollout.md) ·
[README service](../../phase3%20-%20information/techx-corp-platform/src/product-reviews/README.md)

---

## 0. TL;DR

1. **Sửa code trực tiếp trong repo này**, không sửa ở `DangThao195/AIO02_TF3_Phase3` rồi gửi bản copy.
2. Đường dẫn: `phase3 - information/techx-corp-platform/src/product-reviews/`.
3. Test local trước (mục 2), rồi nhánh từ `origin/main` → PR base `main`. **Không push thẳng `main`.**
4. PR merge → CI tự build image, quét Trivy, ký Cosign, **tự mở PR bump `imageOverride`**.
5. Merge PR bump → ArgoCD tự sync → LIVE. Không ai `helm upgrade` tay nữa.
6. Có **7 vùng cấm đè** (mục 5) + **luật flagd** (mục 6) — đè vào là Kyverno/Trivy chặn thẳng, mất fix
   production, hoặc **disqualify cả TF**.

> **Vì sao bắt buộc:** nguồn deploy thật của production là **nhánh `main` của repo này**, account
> `197826770971`, qua ArgoCD. Code nằm ở repo khác thì **không có đường nào vào cluster** — không phải
> "chưa ai deploy", mà là **không tồn tại cơ chế để deploy**.

---

## 1. Bản đồ code — sửa ở đâu

| Thứ cần sửa | Đường dẫn (`.../src/product-reviews/`) |
|---|---|
| 3 RPC + luồng RAG + semaphore + health check | `product_reviews_server.py` (1967 dòng) |
| Lọc đầu vào (injection, base64/hex/leetspeak, bỏ dấu tiếng Việt) | `guardrails/input_filter.py` |
| Lọc đầu ra (PII, leak system prompt) | `guardrails/output_filter.py` |
| Judge / chấm fidelity | `guardrails/evaluator.py` |
| Cache LLM trên Redis | `guardrails/cache.py` |
| Circuit breaker | `guardrails/circuit_breaker.py` |
| Fallback / off-topic routing / tool validator | `guardrails/fallback.py`, `routing.py`, `tool_validator.py` |
| Trace LLM + HTTP endpoint 8086 | `guardrails/llm_trace.py` |
| Inject lỗi để test chống chịu | `guardrails/error_injection.py` |
| Truy cập DB + connection pool | `database.py` (212 dòng) |
| Counter OTel | `metrics.py` |
| Dependency Python | `requirements.txt` |
| Schema DB | `migration.sql`, `db_migration_worker.py` |

**Cấu hình runtime (không phải code):**

| Thứ | File |
|---|---|
| Env AI: model, Bedrock, Redis, IRSA, DB conn | `phase3 - information/deploy/values-aio-llm.yaml` |
| Replica / resource / probe / scheduling / imageOverride | `phase3 - information/deploy/values-prod.yaml` (block `product-reviews`, dòng ~848) |
| Port, env mặc định của chart | `phase3 - information/techx-corp-chart/values.yaml` |

**Không commit:** `__pycache__/` (đã gitignore), `.env`, và **tuyệt đối không** commit giá trị thật của
API key / token / password vào bất kỳ file tracked nào — vi phạm là **disqualify cả TF**.

---

## 2. Dev loop — chạy & test local TRƯỚC khi mở PR

Chạy từ thư mục gốc platform (`phase3 - information/techx-corp-platform/`):

```sh
make docker-generate-protobuf          # chỉ khi .proto đổi
docker compose build product-reviews
docker compose up product-reviews      # hoặc docker-compose.minimal.yml cho stack nhỏ
```

**Smoke test 1 RPC AI** (có sẵn trong repo):

```sh
cd "phase3 - information/techx-corp-platform/src/product-reviews"
python test_client.py 3551 L9ECAV7KIM "Can you summarize the product reviews?"
python aiops_replay_sim.py             # replay closed-loop AIOps
```

**Test đường lỗi mà KHÔNG cần flagd:** service đọc feature flag qua `check_feature_flag()`
(`product_reviews_server.py:1554`), có sẵn env override `FORCE_FLAG_<TÊN_FLAG_VIẾT_HOA>`:

```sh
FORCE_FLAG_LLMRATELIMITERROR=true python product_reviews_server.py     # ép nhánh rate-limit
FORCE_FLAG_LLMINACCURATERESPONSE=true python product_reviews_server.py # ép nhánh trả lời sai
```

Dùng override này **chỉ ở local**. Trên production **không set** — flag phải đọc từ flagd (mục 6).

**Lưu ý port:** `.env.example` để `PRODUCT_REVIEWS_PORT=8085` cho local, nhưng **production là `3551`**
(chart values + probe + `frontend` gọi `product-reviews:3551`). Đừng đổi port trong chart.

**Bedrock ở local:** `.env.example` có sẵn `LLM_PROVIDER=bedrock` + `AWS_ACCESS_KEY_ID/SECRET`. Trên
cluster **không dùng key** — dùng IRSA (`techx-corp-tf3-product-reviews-bedrock`), quyền Bedrock chỉ gắn
vào ServiceAccount này. Nếu code cần gọi **service AWS mới** (Guardrails, S3, DynamoDB…) → phải sửa IAM
role bằng Terraform → **báo CDO01 trước**, code sẽ `AccessDenied` nếu chỉ sửa Python.

**`BEDROCK_GUARDRAIL_ID`:** bản upstream ship sẵn 1 ID thuộc **AWS account khác** → vô dụng ở đây.
Production hiện **không bật** lớp này. Muốn bật phải tạo Guardrail trong account `197826770971` trước.

---

## 3. Quy trình đưa lên production

```sh
# B1. Luôn nhánh từ origin/main mới nhất (nhánh từ ref local cũ đã 2 lần gây conflict)
git fetch origin
git switch -c feat/aio-<mô-tả-ngắn> origin/main

# B2. Sửa code trong .../src/product-reviews/

# B3. Kiểm tra chart vẫn render được (BẮT BUỘC nếu có đụng file values-*)
helm dependency build "phase3 - information/techx-corp-chart"
helm template techx-corp "phase3 - information/techx-corp-chart" \
  --namespace techx-tf3 \
  -f "phase3 - information/techx-corp-chart/values.yaml" \
  -f "phase3 - information/deploy/values-flagd-sync.yaml" \
  -f "phase3 - information/deploy/values-prod.yaml" \
  -f "phase3 - information/deploy/values-aio-llm.yaml" > /dev/null

# B4. PR, base là main
git push -u origin HEAD
gh pr create --base main --title "feat(aio): ..." --body "..."
```

**B5. Sau khi PR merge vào `main`:** workflow `build-push-ecr.yml` tự chạy (trigger `push: main` trên path
`phase3 - information/techx-corp-platform/**`). Nó build đa kiến trúc, **quét Trivy HIGH/CRITICAL trước khi
push**, ký Cosign keyless, rồi **tự mở PR nhánh `ci/bump-images-<run_id>`** cập nhật `imageOverride.digest`
+ `tag` trong `values-prod.yaml`.

**B6.** Nếu thay đổi có đụng schema DB → **chạy Job migration TRƯỚC** khi merge PR bump (mục 8).
Nếu không → merge thẳng PR bump.

**B7.** ArgoCD auto-sync + selfHeal → rollout `maxUnavailable: 0`, `maxSurge: 1`. Verify ở mục 9.

> ⚠️ **Không tự sửa tay `imageOverride`.** CI sinh digest đã ký; sửa tay dễ lệch digest/tag và rơi vào
> supply-chain gate PM-101. `default.image.tag` **không** tự nối tên service — nếu buộc phải ghi tay thì
> `tag` phải FULL dạng `<sha>-<runid>-product-reviews`.
>
> ⚠️ **CVE chặn build:** Trivy gate chặn **trước khi push**, nên thêm dependency có CVE HIGH/CRITICAL là
> build fail (đợt 28/07 đã phải vá `brace-expansion` + `postcss`). Bump dependency thì chạy thử build sớm.

---

## 4. Đổi env thì **không cần** build lại image

Phần lớn việc tinh chỉnh chỉ cần sửa `values-aio-llm.yaml` → PR → ArgoCD sync (~1 phút), **không** phải
qua vòng build/bump image.

| Env | Mặc định | Ý nghĩa |
|---|---|---|
| `LLM_PROVIDER` / `JUDGE_PROVIDER` | `bedrock` | provider (`bedrock` hoặc `openai`) |
| `LLM_MODEL` / `JUDGE_MODEL` | `amazon.nova-lite-v1:0` / `amazon.nova-micro-v1:0` | model chính / model judge |
| `LLM_TIMEOUT_SECONDS` / `JUDGE_TIMEOUT_SECONDS` | `10.0` | timeout gọi Bedrock |
| `JUDGE_ALL_GROUNDED_ANSWERS` | `true` | judge mọi câu trả lời đã grounding |
| `AI_ASSISTANT_MAX_CONCURRENCY` | `4` | trần số call AI đồng thời (fix PM-0016) |
| `AI_ASSISTANT_ADMISSION_TIMEOUT_SECONDS` | `0.05` | chờ tối đa trước khi shed — **giữ ngắn**, xem mục 5 |
| `LLM_CACHE_TTL_SECONDS` | `86400` | TTL cache LLM trên Redis |
| `CACHE_TYPE` | `redis` | `redis` hoặc `none` |
| `REDIS_HOST/PORT/USE_TLS/AUTH_TOKEN` | ElastiCache Mandate #8 | cache + state circuit breaker |
| `GRPC_MAX_WORKERS` | `12` | số worker gRPC — **phải khớp pool DB**, xem mục 5 |
| `DB_POOL_MIN_CONN` / `DB_POOL_MAX_CONN` | `1` / `10` | pool Postgres — **đọc mục 5 trước khi tăng** |
| `BEDROCK_GUARDRAIL_ID` / `_VERSION` / `_REGION` | rỗng (tắt) | Bedrock Guardrail |
| `PRODUCT_REVIEWS_TRACE_HTTP_PORT` / `_TOKEN` | `8086` / rỗng | endpoint trace — xem mục 7 |

---

## 5. 7 vùng CẤM ĐÈ

Đây là những chỗ bản upstream AIO02 **khác** repo này **có chủ đích**. Dán đè nguyên xi = hỏng production.
Nếu thấy cần đổi, **ping CDO01 trước**, đừng đổi lặng lẽ.

| # | Vùng | Vì sao repo này khác | Hậu quả nếu đè |
|---|---|---|---|
| 1 | **`Dockerfile`** | Pin digest base image, `apk upgrade libcrypto3/libssl3`, `PYTHONDONTWRITEBYTECODE`, **user non-root 65532** | Upstream chạy **root** → **Kyverno chặn admission**, **Trivy gate PM-101 chặn build**. Pod không lên được. |
| 2 | **Semaphore `AI_ASSISTANT_MAX_CONCURRENCY`** (`product_reviews_server.py:253-255`) | Fix PM-0016, upstream **không có** | Mất fix. **Circuit breaker KHÔNG thay thế được**: breaker trip khi Bedrock *lỗi*; semaphore chặn *số call đồng thời* ngay cả khi Bedrock vẫn trả lời (chỉ chậm). |
| 3 | **`Check()` health REL-02** (`product_reviews_server.py:940-962`) | Health phụ thuộc DB + `NOT_SERVING` khi shutdown | Upstream trả `SERVING` vô điều kiện → K8s **không rút pod mất DB** khỏi Service → traffic vào pod hỏng. (Graceful shutdown mới của upstream thì repo **đã giữ**.) |
| 4 | **Kích thước pool DB** (`database.py:49-50`, `GRPC_MAX_WORKERS`) | `maxconn=10`, worker `12` | RDS `techx-tf3-postgres` là **`db.t4g.micro`, `max_connections ≈ 112` dùng chung cả cụm**. `product-catalog` đã chiếm 20/pod × 8 pod = 160. Upstream hardcode `maxconn=30` × 6 pod = **180 riêng product-reviews** → cạn connection, **kéo sập `product-catalog` + `accounting`** (đúng kịch bản REL-05). |
| 5 | **Xử lý `PoolError`** (`database.py:80-112`) | Pool cạn → fail đúng request đó; chỉ dựng lại pool khi pool **thật sự hỏng**, và `closeall()` pool cũ trước | Bản upstream dựng pool mới **mà không đóng pool cũ** → **rò `maxconn` connection mỗi lần**, lặp liên tục dưới tải. |
| 6 | **`migration.sql`** | `CREATE INDEX CONCURRENTLY` + `GRANT` trên SEQUENCE | Upstream dùng `CREATE INDEX` thường → **khoá ghi bảng dùng chung** với `product-catalog`/`accounting`. Thiếu `GRANT` → INSERT lỗi permission. |
| 7 | **2 RPC đọc KHÔNG được chạm Redis/LLM** | `GetProductReviews` + `GetAverageProductReviewScore` chỉ đọc Postgres | Đây là điều kiện để **Valkey/Bedrock hỏng không kéo theo 2 RPC** đang gánh deadline 500ms của frontend. Thêm 1 lời gọi Redis vào đường đọc = biến sự cố cache thành sự cố storefront. |

**Ràng buộc kèm theo:**

- **Redis dùng chung với `cart`** (ElastiCache của Mandate #8, không phải instance riêng). Key phải giữ
  namespace `product_reviews:*`. Mọi lời gọi Redis phải bọc try/except + socket timeout 1s như hiện tại —
  **Redis lỗi không được làm chết request**.
- **`AI_ASSISTANT_ADMISSION_TIMEOUT_SECONDS`:** request không giành được slot vẫn **giữ 1 worker gRPC**
  suốt thời gian chờ. Đo thật (`grpc.server` với `max_workers=10`, cap=4, timeout=0.05s): burst 100
  request AI → 1 read RPC xen giữa mất **~758ms**, **vượt deadline 500ms**. Tăng giá trị này = tự tạo lại
  PM-0016.
- **`demo_pb2.py` / `demo_pb2_grpc.py`** hiện **giống hệt** upstream → gRPC contract không đổi →
  `frontend` không phải sửa. Nếu đợt tới **có đổi contract**, phải báo trước: phải sửa `frontend`
  (`gateways/rpc/ProductReview.gateway.ts`) và deploy theo thứ tự, vì lúc rollout pod cũ/mới cùng tồn tại.
- **Body lỗi trả về client phải là plain text, không JSON.** Bundle frontend cũ sẽ `JSON.parse` body lỗi
  thành "thành công" trong lúc rolling rollout → tái diễn đúng lỗi PM-0016 cần chặn.

---

## 6. flagd — cơ chế BTC bơm sự cố, CẤM GỠ

Service đọc 2 flag từ flagd: **`llmInaccurateResponse`** và **`llmRateLimitError`**
(`product_reviews_server.py:1249, 1323, 1450`).

- **Không** gỡ, đổi hướng, hay refactor để service ngừng đọc flag từ flagd. Đây là kênh BTC bơm sự cố.
  Xử lý sự cố bằng fallback/retry/containment, **không phải tắt cơ chế**.
- **Không** đổi TOKEN/URI trong `values-flagd-sync.yaml`, không bỏ file này khỏi lệnh deploy.
- Muốn test 2 nhánh lỗi này ở local → dùng `FORCE_FLAG_*` (mục 2), **không** sửa code đọc flag.

**Vi phạm 2 gạch đầu dòng trên = disqualify cả TF3.** Nếu thấy logic flag cản việc gì, ping CDO01 —
luôn có cách làm khác không đụng cơ chế.

---

## 7. Quan sát — dùng gì để biết code chạy đúng

**Metrics OTel** (`metrics.py`) → Prometheus → Grafana:
`app_product_review_counter` · `app_ai_assistant_counter` · `app_ai_fallback_total`.
Thêm counter mới thì khai báo trong `metrics.py`, đừng tạo meter rời rạc trong module con.

**gRPC trailing metadata `cache: hit|miss`** — cách nhanh nhất để biết cache có ăn không.

**Trace HTTP endpoint (port 8086)** — `GET /trace/<trace_id>`, `POST /replay`, `POST /inject`.
Mặc định **tự tắt** nếu `PRODUCT_REVIEWS_TRACE_HTTP_TOKEN` rỗng (`product_reviews_server.py:1780-1791`).

> ⚠️ **Đừng bật ở production bằng `PRODUCT_REVIEWS_TRACE_HTTP_ALLOW_UNAUTHENTICATED=true`.** `POST /inject`
> là đường tiêm lỗi, `POST /replay` chạy được kịch bản. Cần bật thì đặt token qua **secret**
> (`secretKeyRef`, không phải giá trị plaintext trong values), và không expose port ra ngoài — Mandate #1
> yêu cầu least exposure ở biên.

**UI:** Grafana `grafana.arthur-ngo.org`, Jaeger `jaeger.arthur-ngo.org/jaeger/ui/` — vào qua Cloudflare
Access bằng SSO, **không cần kubectl/IAM**.

---

## 8. Nếu thay đổi có đụng schema DB

**Thứ tự bắt buộc: migration TRƯỚC, bump image SAU.** Nếu merge PR bump trước, pod mới query cột chưa tồn
tại → **mọi request đọc review lỗi ngay lập tức**.

```sh
export AWS_PROFILE=techx-new        # BẮT BUỘC — profile default trỏ account cũ

# 1. Sửa image digest trong Job cho khớp digest ở PR bump (digest-pinned, không dùng tag trôi)
#    file: gitops/jobs/product-reviews-schema-migration.yaml
kubectl apply -f gitops/jobs/product-reviews-schema-migration.yaml
kubectl -n techx-tf3 wait --for=condition=complete job/product-reviews-schema-migration --timeout=600s
kubectl -n techx-tf3 logs job/product-reviews-schema-migration

# 2. Đọc log tự-verify (cột/index/table phải present, index phải indisvalid)
# 3. Dọn Job rồi mới merge PR bump image
kubectl -n techx-tf3 delete job product-reviews-schema-migration
```

Job này **cố ý không** nằm dưới ArgoCD (one-off, không phải desired-state) và **chỉ đọc `migration.sql` từ
image** — chạy Job **không** deploy code mới.

**Viết `migration.sql` phải theo 3 luật đã trả giá:**
1. `CREATE INDEX CONCURRENTLY`, không bao giờ `CREATE INDEX` thường — bảng `reviews.productreviews` dùng
   chung với `product-catalog`/`accounting`. Nếu fail giữa chừng có thể để lại index `INVALID`; kiểm tra
   `pg_index.indisvalid` rồi `DROP INDEX CONCURRENTLY` trước khi thử lại.
2. Mỗi câu lệnh chạy **riêng** — nhiều statement trong 1 `execute()` bị PostgreSQL bọc thành implicit
   transaction, `CONCURRENTLY` sẽ fail (`cannot run inside a transaction block`). Tách câu lệnh phải
   **strip comment trước** vì `migration.sql` có dấu `;` nằm trong comment.
3. Cột mới phải có **DEFAULT an toàn** (`is_safe BOOLEAN DEFAULT TRUE`) để pod cũ vẫn chạy được trong lúc
   rollout, và bảng mới phải có `GRANT ... TO otelu` + `GRANT USAGE, SELECT ON SEQUENCE` nếu dùng `SERIAL`.

**Back-fill dữ liệu:** luôn **dry-run trước** (mẫu:
`gitops/jobs/product-reviews-is-safe-backfill-dryrun.yaml`). Lần trước dry-run cho thấy 50 review / 0 bị
đánh dấu → hoá ra là no-op, khỏi chạy. Chạy mù có thể đánh nhầm review hợp lệ thành unsafe → mọi query đều
lọc `is_safe = TRUE` nên review sẽ **biến mất khỏi storefront** mà không ai biết.

---

## 9. Verify sau khi LIVE + rollback

```sh
export AWS_PROFILE=techx-new
kubectl -n techx-tf3 get pods -l opentelemetry.io/name=product-reviews -o wide   # RESTARTS phải = 0
kubectl -n techx-tf3 logs -l opentelemetry.io/name=product-reviews --tail=100 | grep -i "error\|throttl"
kubectl -n argocd get app techx-corp -o jsonpath='{.status.sync.status} {.status.health.status}'
```

Storefront: `https://d2tn71186d7ilz.cloudfront.net` → mở 1 trang sản phẩm, kiểm tra review hiển thị + hỏi
AI assistant. Không có review hiện ra = nghi ngay `is_safe` / schema.

**Rollback:** revert PR bump image (`git revert` → PR → merge). ArgoCD tự đưa về digest cũ. Rollback code
**không** rollback schema DB — migration phải viết theo hướng tương thích ngược (mục 8, luật 3).

---

## 10. Checklist trước khi mở PR

- [ ] Đã chạy `docker compose build product-reviews` + `test_client.py` ở local, không crash
- [ ] Nhánh tạo từ `origin/main` sau `git fetch`, PR base `main`
- [ ] Không đụng 7 vùng ở mục 5 (hoặc đã thống nhất với CDO01)
- [ ] Không đụng cơ chế đọc flagd (mục 6)
- [ ] Không có secret/API key/token trong diff
- [ ] Không commit `__pycache__/`, `.env`, file build tạm
- [ ] Dependency mới không có CVE HIGH/CRITICAL (Trivy sẽ chặn build)
- [ ] `helm template` chạy sạch nếu có sửa `values-*.yaml`
- [ ] Nếu thêm field mới vào values → **đã cập nhật `values.schema.json`** (schema là
      `additionalProperties: false`; quên là ArgoCD `ComparisonError`, chết cả pipeline)
- [ ] Có đụng schema DB → đã nêu rõ trong PR body + có kế hoạch chạy Job migration trước
- [ ] Có đổi `demo_pb2*` / contract gRPC, hoặc cần quyền AWS mới → **đã báo CDO01 trước**
- [ ] PR body ghi: đổi gì, vì sao, verify thế nào, cần migration không

---

## 11. Việc PM-0016 còn mở, liên quan AIO02

| Việc | Ai | Ghi chú |
|---|---|---|
| **P3 đầy đủ** — tách luồng AI ra deployment/service riêng | CDO01/CDO02 chốt, AIO02 review phần code | Cache mới chỉ **che** ở mức tải hiện tại, chưa phải cô lập thật |
| Theo dõi quota Bedrock khi cache miss cao | **AIO02** | Không còn gấp sau khi có cache, nhưng cache chỉ hiệu quả khi câu hỏi **lặp lại**. Locust dùng vài câu cố định nên hit rate cao giả tạo — user thật hỏi đa dạng, hoặc TTL 24h hết, hoặc Redis lỗi → **Bedrock bị gọi thật trở lại và throttle có thể quay lại** |
| Xem lại deadline 500ms theo p95/p99 thật | CDO02 | Deadline nằm ở `frontend/gateways/rpc/ProductReview.gateway.ts:12`, override được bằng env `PRODUCT_REVIEWS_DEADLINE_MS` |

---

**Câu hỏi/nghi ngờ về vùng cấm đè:** ping CDO01 trước khi sửa. Sửa rồi mới hỏi thì tốn thêm 1 vòng
build + review, và rủi ro cao nhất là **mất fix production mà không ai nhận ra cho tới lần load test sau**.
