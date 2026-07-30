# ADR-M9-07d: Online Schema Migration — `products.categories` & `orderitem.created_at`

**Status:** DRAFT — Awaiting mentor sign-off (M9-15a)  
**Date:** 2026-07-30  
**Owner:** Đức  
**Reviewer:** Hải  
**Mentor sign-off required:** YES — Compliance #1 là CONDITIONAL cho đến khi mentor ký

---

## 0. Context & Decision Required

Mandate #9 compliance item #1 yêu cầu chứng minh **online schema migration không downtime** dưới tải production.

Hệ thống không có bảng **vừa lớn (>100k) vừa customer-facing** trong cùng một bảng.

**Quyết định cần mentor chốt (2 lựa chọn):**

| Option | Mô tả | Trade-off |
|--------|-------|-----------|
| **Option A (đề xuất)** | 2 bảng riêng: `products` (customer read) + `orderitem` (large table) | Mỗi bảng chứng minh 1 khía cạnh khác nhau |
| **Option B** | Chạy trọn chu kỳ trên 1 bảng (mentor chọn bảng) | Cần tạo thêm dữ liệu demo lớn hoặc chọn bảng ít phù hợp |

**→ Team đề xuất Option A.** Mentor xác nhận tại M9-15a.

---

## 1. Table Mapping

### 1.1 `catalog.products` — TEXT → text[]

**Migration type:** Type change (backward-compatible)

```
products.categories TEXT "telescopes,travel"
    ↓ EXPAND: ADD COLUMN categories_arr text[]
    ↓ Deploy Revision A: COALESCE(categories_arr, string_to_array(categories,','))
    ↓ BACKFILL: UPDATE products SET categories_arr = ...
    ↓ VERIFY: browse xanh, categories count khớp
    ↓ Deploy Revision B: đọc CHỈ categories_arr
    ↓ GATE: 100% revision B + bake ≥24h
    ↓ W2-CONTRACT: DROP COLUMN categories (M9-14)
```

**App revision:**
- **Revision A:** `COALESCE(categories_arr, string_to_array(categories, ','))` — tương thích với cả 2 column
- **Revision B:** đọc trực tiếp `categories_arr` — không reference `categories` cũ

### 1.2 `accounting.orderitem` — ADD created_at

**Migration type:** Add nullable column → backfill → NOT NULL contract

```
orderitem (NO created_at)
    ↓ EXPAND: ADD COLUMN created_at timestamptz (nullable)
    ↓ Deploy accounting với ORDERITEM_WRITE_CREATED_AT=true
    ↓ DUAL-WRITE: insert mới ghi created_at = NOW()
    ↓ VERIFY: rows sau watermark không còn NULL
    ↓ BACKFILL: UPDATE ... SET created_at = <watermark> WHERE IS NULL (lô 5-10k)
    ↓ ADD CHECK NOT VALID: (created_at IS NOT NULL)
    ↓ VALIDATE CHECK: (SHARE UPDATE EXCLUSIVE, không block writes)
    ↓ CREATE INDEX CONCURRENTLY: ngoài transaction block
    ↓ W2-CONTRACT: SET NOT NULL + drop CHECK (M9-14)
```

---

## 2. Production Windows

### W1 — M9-13 (Pre-contract, reversible)

**Scope:** expand + dual-write + backfill + validate + index → KHÔNG contract

| Step | SQL / Action | Reversible? |
|------|-------------|-------------|
| `products`: ADD categories_arr | DDL expand | ✅ DROP COLUMN |
| Deploy Revision A | Rolling deployment | ✅ Rollback revision |
| Backfill products | UPDATE 10 rows | ✅ UPDATE lại |
| Deploy accounting dual-write | Rolling + env flag | ✅ Disable flag |
| `orderitem`: ADD created_at | DDL expand | ✅ DROP COLUMN |
| Backfill orderitem | UPDATE batch | ✅ Không destructive |
| ADD CHECK NOT VALID | DDL | ✅ DROP CONSTRAINT |
| VALIDATE CONSTRAINT | DDL (SHARE UPDATE) | ✅ DROP CONSTRAINT |
| CREATE INDEX CONCURRENTLY | DDL | ✅ DROP INDEX |
| Deploy Revision B (products) | Rolling deployment | ✅ Rollback revision |

**Rollback point W1:** Bất cứ bước nào trên đều reversible.

### W2 — M9-14 (Contract, destructive — mentor quan sát)

**Pre-conditions (PHẢI đủ trước khi mở W2):**
- [ ] Revision B products = 100% (no pod running Revision A)
- [ ] Bake ≥24h sau Revision B deploy
- [ ] 0 code/query/migration reference `categories` column cũ
- [ ] `orderitem.created_at IS NULL` count = 0 (backfill converged)
- [ ] M9-15c approval received

| Step | SQL | Impact |
|------|-----|--------|
| `orderitem`: SET NOT NULL | `ALTER TABLE ... ALTER COLUMN created_at SET NOT NULL` | Tận dụng validated CHECK — không full scan |
| Commit | Verify data/traffic | — |
| Drop CHECK | `ALTER TABLE ... DROP CONSTRAINT ...` (riêng txn) | Cleanup, negligible |
| `products`: DROP COLUMN | `ALTER TABLE ... DROP COLUMN categories` | **IRREVERSIBLE** |

**Rollback post-W2:** KHÔNG CÓ. Chỉ restore từ snapshot/PITR.

---

## 3. SQL Skeleton (Idempotent, Bounded-Lock)

### 3.1 `catalog.products` — EXPAND (W1, Step 1)

```sql
-- Step 1a: EXPAND (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'catalog'
          AND table_name   = 'products'
          AND column_name  = 'categories_arr'
    ) THEN
        SET LOCAL lock_timeout      = '1s';
        SET LOCAL statement_timeout = '30s';
        ALTER TABLE catalog.products
            ADD COLUMN categories_arr text[];
        RAISE NOTICE 'Added categories_arr column';
    ELSE
        RAISE NOTICE 'categories_arr already exists, skipping';
    END IF;
END $$;

-- Step 1b: BACKFILL (idempotent — chỉ rows chưa migrate)
UPDATE catalog.products
SET categories_arr = string_to_array(categories, ',')
WHERE categories IS NOT NULL
  AND categories_arr IS NULL;

-- Step 1c: VERIFY
SELECT
    id,
    categories            AS old_csv,
    categories_arr        AS new_array,
    array_length(categories_arr, 1) AS count
FROM catalog.products
ORDER BY id;
-- Expected: categories_arr cho tất cả 10 rows, count khớp với CSV
```

### 3.2 `accounting.orderitem` — EXPAND (W1)

```sql
-- Step 2a: EXPAND (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'accounting'
          AND table_name   = 'orderitem'
          AND column_name  = 'created_at'
    ) THEN
        -- SET LOCAL áp dụng trong transaction hiện tại của DO block
        SET LOCAL lock_timeout      = '1s';
        SET LOCAL statement_timeout = '30s';
        ALTER TABLE accounting.orderitem
            ADD COLUMN created_at timestamptz;
        RAISE NOTICE 'Added created_at column (nullable)';
    ELSE
        RAISE NOTICE 'created_at already exists, skipping';
    END IF;
END $$;
```

### 3.3 `accounting.orderitem` — BACKFILL (W1)

```sql
-- Step 3: BACKFILL theo lô dùng PK (order_id, product_id) — KHÔNG dùng ctid
-- ctid không ổn định sau autovacuum, có thể update sai row.
-- Chạy từ application script hoặc migration job với pause giữa batch.

DO $$
DECLARE
    rows_updated INT;
    batch_limit  INT := 5000;
    -- M9-07d: Backfill watermark = timestamp W1 window bắt đầu.
    -- Tất cả row cũ được gán giá trị này (xem §4 semantics)
    backfill_watermark TIMESTAMPTZ := '2026-08-11 03:00:00+00'; -- W1 date, chốt trước
BEGIN
    LOOP
        -- Dùng PK (order_id, product_id) để identify batch — ổn định qua vacuum
        UPDATE accounting.orderitem
        SET created_at = backfill_watermark
        WHERE (order_id, product_id) IN (
            SELECT order_id, product_id
            FROM accounting.orderitem
            WHERE created_at IS NULL
            LIMIT batch_limit
            FOR UPDATE SKIP LOCKED
        );

        GET DIAGNOSTICS rows_updated = ROW_COUNT;

        EXIT WHEN rows_updated = 0;

        RAISE NOTICE 'Backfilled % rows, sleeping 100ms', rows_updated;
        PERFORM pg_sleep(0.1); -- 100ms pause giữa batch
    END LOOP;

    RAISE NOTICE 'Backfill complete';
END $$;

-- VERIFY CONVERGENCE: Phải = 0 trước khi ADD CONSTRAINT
SELECT COUNT(*) AS null_count
FROM accounting.orderitem
WHERE created_at IS NULL;
-- Expected: 0
```

### 3.4 `accounting.orderitem` — ADD CHECK NOT VALID (W1)

```sql
-- Step 4: ADD CHECK NOT VALID (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'accounting.orderitem'::regclass
          AND conname  = 'orderitem_created_at_not_null_check'
    ) THEN
        SET LOCAL lock_timeout      = '1s';
        SET LOCAL statement_timeout = '30s';
        ALTER TABLE accounting.orderitem
            ADD CONSTRAINT orderitem_created_at_not_null_check
            CHECK (created_at IS NOT NULL) NOT VALID;
        RAISE NOTICE 'Added CHECK NOT VALID';
    ELSE
        RAISE NOTICE 'CHECK constraint already exists, skipping';
    END IF;
END $$;
```

### 3.5 `accounting.orderitem` — VALIDATE CONSTRAINT (W1)

```sql
-- Step 5: VALIDATE (SHARE UPDATE EXCLUSIVE — không block reads/writes)
-- Không cần idempotency guard: VALIDATE trên constraint đã valid = no-op
SET statement_timeout = '0'; -- VALIDATE có thể chạy lâu trên 395k rows, không timeout
ALTER TABLE accounting.orderitem
    VALIDATE CONSTRAINT orderitem_created_at_not_null_check;

-- VERIFY
SELECT
    conname,
    convalidated
FROM pg_constraint
WHERE conrelid = 'accounting.orderitem'::regclass
  AND conname  = 'orderitem_created_at_not_null_check';
-- Expected: convalidated = true
```

### 3.6 `accounting.orderitem` — CREATE INDEX CONCURRENTLY (W1)

```sql
-- Step 6: INDEX CONCURRENTLY — PHẢI ngoài transaction block
-- Chạy trong psql interactive session hoặc migration job, KHÔNG trong DO $$ block

-- Check invalid index trước (idempotent cleanup):
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'accounting'
          AND tablename  = 'orderitem'
          AND indexname  = 'orderitem_created_at_idx'
    ) AND EXISTS (
        SELECT 1 FROM pg_index
        JOIN pg_class ON pg_class.oid = pg_index.indexrelid
        WHERE pg_class.relname = 'orderitem_created_at_idx'
          AND NOT pg_index.indisvalid
    ) THEN
        -- Drop invalid index trước khi retry
        DROP INDEX CONCURRENTLY IF EXISTS accounting.orderitem_created_at_idx;
        RAISE NOTICE 'Dropped invalid index, will retry';
    END IF;
END $$;

-- Tạo index (NGOÀI transaction block):
CREATE INDEX CONCURRENTLY IF NOT EXISTS orderitem_created_at_idx
    ON accounting.orderitem (created_at);

-- VERIFY
SELECT
    i.relname                                         AS index_name,
    pg_size_pretty(pg_relation_size(idx.indexrelid))  AS index_size,
    idx.indisvalid                                    AS is_valid
FROM pg_index idx
JOIN pg_class i ON i.oid = idx.indexrelid
JOIN pg_class t ON t.oid = idx.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'accounting'
  AND t.relname = 'orderitem'
  AND i.relname = 'orderitem_created_at_idx';
-- Expected: is_valid = true
```

### 3.7 `accounting.orderitem` — SET NOT NULL + DROP CHECK (W2, M9-14)

```sql
-- W2 Step 1: SET NOT NULL (tận dụng validated CHECK — không full-table scan)
-- Đây là bounded-lock: ACCESS EXCLUSIVE giữ rất ngắn vì CHECK đã validate
BEGIN;
    SET lock_timeout      = '1s';
    SET statement_timeout = '30s';
    
    ALTER TABLE accounting.orderitem
        ALTER COLUMN created_at SET NOT NULL;
COMMIT;

-- VERIFY sau commit:
SELECT column_name, is_nullable
FROM information_schema.columns
WHERE table_schema = 'accounting'
  AND table_name   = 'orderitem'
  AND column_name  = 'created_at';
-- Expected: is_nullable = 'NO'

-- W2 Step 2: DROP CHECK (transaction RIÊNG — không trong cùng command)
BEGIN;
    SET lock_timeout      = '1s';
    SET statement_timeout = '30s';
    
    ALTER TABLE accounting.orderitem
        DROP CONSTRAINT IF EXISTS orderitem_created_at_not_null_check;
COMMIT;

-- VERIFY:
SELECT COUNT(*) FROM pg_constraint
WHERE conrelid = 'accounting.orderitem'::regclass
  AND conname  = 'orderitem_created_at_not_null_check';
-- Expected: 0
```

### 3.8 `catalog.products` — DROP COLUMN (W2, M9-14)

```sql
-- W2 Step 3: DROP COLUMN categories (IRREVERSIBLE)
-- Pre-condition: 100% revision B pods + bake ≥24h + 0 reference cột cũ

BEGIN;
    SET lock_timeout      = '1s';
    SET statement_timeout = '30s';
    
    ALTER TABLE catalog.products
        DROP COLUMN IF EXISTS categories;
COMMIT;

-- VERIFY:
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'catalog'
  AND table_name   = 'products'
  AND column_name  = 'categories';
-- Expected: 0 rows
```

---

## 4. Watermark Semantics (Chốt cho ADR)

### 4.1 `products.categories_arr` — Không cần watermark
10 rows, backfill tức thì, không có concurrent writes.

### 4.2 `orderitem.created_at` — Cần watermark

**Vấn đề:** Row cũ (trước migration) không có `created_at` thật. Backfill cần gán giá trị gì?

**Quyết định (chốt tại M9-07d):**

> Backfill `created_at` bằng **migration watermark cố định** = timestamp bắt đầu backfill job.
> 
> Semantic: **"Giá trị ≤ watermark nghĩa là 'order item tạo trước migration, thời điểm chính xác không xác định'"**
> 
> Tên cột `created_at` vẫn phù hợp vì: sau dual-write, mọi row MỚI có giá trị chính xác. Row cũ có watermark = sentinel rõ ràng để phân biệt.

**Verify dual-write coverage:**
```sql
-- Sau khi deploy dual-write accounting, verify rows SAU watermark không NULL:
SELECT
    COUNT(*) FILTER (WHERE created_at IS NULL)    AS null_rows,
    COUNT(*) FILTER (WHERE created_at IS NOT NULL) AS filled_rows,
    MAX(created_at)                               AS latest_write
FROM accounting.orderitem
WHERE order_id > :watermark_order_id; -- Chỉ rows sau khi dual-write active
-- Expected: null_rows = 0 cho rows sau watermark
```

**Alternative option (nếu mentor không chấp nhận sentinel):**
- Đặt tên cột là `ingested_at` thay vì `created_at`
- Semantic rõ hơn: "Thời điểm được ghi vào DB, không phải thời điểm tạo order"

**→ Cần mentor chốt tên cột và semantic.**

---

## 5. SET NOT NULL tận dụng validated CHECK

**Kỹ thuật PostgreSQL:**

```
Normal SET NOT NULL:     ACCESS EXCLUSIVE + full-table scan (chậm trên 395k rows)
SET NOT NULL với CHECK:  ACCESS EXCLUSIVE + skip scan (PostgreSQL đọc pg_constraint)
```

PostgreSQL 14+ tối ưu: nếu tồn tại **validated** `CHECK (col IS NOT NULL)`, `ALTER COLUMN SET NOT NULL` nhận ra và **bỏ qua full-table scan**. Lock vẫn là ACCESS EXCLUSIVE nhưng giữ rất ngắn (ms thay vì giây).

**Chuỗi bắt buộc:**
1. `ADD CONSTRAINT ... CHECK (created_at IS NOT NULL) NOT VALID` — không block, không scan
2. `VALIDATE CONSTRAINT` — SHARE UPDATE EXCLUSIVE (đọc toàn bảng nhưng không block writes)
3. `ALTER COLUMN SET NOT NULL` — ACCESS EXCLUSIVE **ngắn** (bỏ qua scan vì có CHECK)
4. `DROP CONSTRAINT` — riêng transaction

**Bounded-lock guarantee:**
- `lock_timeout = '1s'`: Nếu không lấy được lock trong 1s → raise error, không xếp hàng
- `statement_timeout = '30s'`: Giới hạn tổng thời gian DDL
- Retry: nếu lock_timeout → sleep + retry (tối đa 3 lần)

---

## 6. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | `VALIDATE CONSTRAINT` chạy quá lâu trên 395k rows | MEDIUM | LOW (SHARE UPDATE, không block writes) | Set `statement_timeout = '0'` cho VALIDATE; monitor lag |
| R2 | `CREATE INDEX CONCURRENTLY` fail → invalid index | LOW | MEDIUM (retry blocked until cleanup) | Detect + DROP invalid index trước retry (script idempotent) |
| R3 | Revision A/B rolling conflict (old pod đọc categories cũ, new pod cần arr) | LOW | HIGH (404 hoặc empty categories) | COALESCE trong Revision A đọc cả 2; không deploy B trước backfill |
| R4 | Dual-write không converge (accounting env flag sai) | MEDIUM | HIGH (NULL rows còn lại, backfill vô hạn) | Verify ORDERITEM_WRITE_CREATED_AT active trước backfill; check null_count |
| R5 | Lock contention trên backfill (FK check lock accounting.order) | LOW | MEDIUM (slow backfill) | Batch nhỏ (5k) + 100ms sleep; SKIP LOCKED |
| R6 | DROP COLUMN categories khi còn pod Revision A | HIGH nếu không check | CRITICAL (parse error) | Gate: Revision B = 100% + bake ≥24h; check rolling status trước W2 |
| R7 | Replication lag spike trong backfill | MEDIUM | LOW (replica delay, không customer impact) | Monitor `pg_stat_replication`; giảm batch hoặc tăng sleep |

---

## 7. Evidence Protocol

### 7.1 Pre-W1 Evidence (trước khi mở cửa sổ)
```bash
# 1. NULL count baseline
psql -c "SELECT COUNT(*) FROM accounting.orderitem WHERE created_at IS NULL;"

# 2. Categories baseline
psql -c "SELECT id, categories FROM catalog.products ORDER BY id;"

# 3. pg_locks monitoring query (run trong window)
psql -c "
SELECT pid, wait_event_type, wait_event, query_start, state, query
FROM pg_stat_activity
WHERE wait_event_type = 'Lock'
  AND query NOT LIKE '%pg_stat_activity%'
ORDER BY query_start;
"
```

### 7.2 During-W1 Evidence
```bash
# Dual-write verify (run sau khi accounting deployed)
psql -c "
SELECT 
    COUNT(*) FILTER (WHERE created_at IS NULL) AS still_null,
    COUNT(*) FILTER (WHERE created_at IS NOT NULL) AS written,
    MAX(created_at) AS latest
FROM accounting.orderitem;
"

# INDEX creation progress
psql -c "
SELECT phase, blocks_done, blocks_total,
       ROUND(100.0 * blocks_done / NULLIF(blocks_total,0), 1) AS pct_done
FROM pg_stat_progress_create_index
WHERE relid = 'accounting.orderitem'::regclass;
"
```

### 7.3 Pre-W2 Evidence (gating criteria)
```bash
# BẮT BUỘC pass tất cả trước khi mở W2:
psql -c "SELECT COUNT(*) AS must_be_zero FROM accounting.orderitem WHERE created_at IS NULL;"
psql -c "SELECT convalidated AS must_be_true FROM pg_constraint WHERE conname='orderitem_created_at_not_null_check';"
psql -c "SELECT indisvalid AS must_be_true FROM pg_indexes JOIN pg_index ... WHERE indexname='orderitem_created_at_idx';"
# Check: 0 pods running Revision A
kubectl get pods -l app=product-catalog -o jsonpath='{.items[*].metadata.annotations.revision}' | tr ' ' '\n' | sort | uniq -c
```

### 7.4 Post-W2 Evidence (nghiệm thu)
```bash
# products: categories column đã drop
psql -c "SELECT column_name FROM information_schema.columns WHERE table_name='products' AND column_name='categories';"
# Expected: 0 rows

# orderitem: created_at NOT NULL
psql -c "SELECT is_nullable FROM information_schema.columns WHERE table_name='orderitem' AND column_name='created_at';"
# Expected: 'NO'

# Traffic matrix (từ M9-00 dashboard):
# list/get/search: failure delta = 0
# checkout→orderitem: row count tăng, created_at IS NOT NULL = 0
```

---

## 8. Rollback Plan

### W1 Rollback (bất cứ bước nào)
```sql
-- Rollback products expand:
ALTER TABLE catalog.products DROP COLUMN IF EXISTS categories_arr;

-- Rollback orderitem expand:
ALTER TABLE accounting.orderitem DROP COLUMN IF EXISTS created_at;

-- Rollback app: redeploy prev revision (rolling, maxUnavailable=0)
```

### W2 Rollback
**Không có rollback cho W2**. Sau `DROP COLUMN categories` → chỉ restore từ:
- RDS Point-in-Time Recovery (PITR)
- Manual snapshot restore

**→ Đây là lý do W2 cần bake ≥24h và M9-15c approval độc lập.**

---

## 9. Dependency Map

```
M9-03 (accounting idempotent) ──────────────────────────────────┐
                                                                 │
M9-07d (this ADR) ──→ M9-15a (mentor sign-off) ──→ M9-07i (SQL impl) ──→ M9-05a
                                                         │
                                          ┌──────────────┘
                                          ↓
M9-06 (integration) ──→ M9-12 (staging rehearsal) ──→ M9-15b ──→ M9-13 (PROD W1)
                                                                        │
                                                                        └──→ bake ≥24h ──→ M9-15c ──→ M9-14 (PROD W2)
```

---

## 10. Open Questions for Mentor (M9-15a)

1. **Bảng mapping:** Option A (2 bảng) hay Option B (1 bảng)? Team đề xuất A.

2. **Watermark semantics cho `created_at`:**
   - Dùng `created_at` với sentinel value = migration watermark?
   - Hay rename cột thành `ingested_at` cho rõ semantic?

3. **Contract observation:** Mentor quan sát trực tiếp W2 (M9-14) hay phê duyệt evidence protocol sau?

4. **Backfill batch size:** 5k rows/batch với 100ms sleep có đủ an toàn cho 395k rows (~40MB)?

5. **VALIDATE timeout:** Set `statement_timeout = '0'` cho VALIDATE có chấp nhận được không?

---

## Appendix A: Migration Sequence Diagram

```
TIME ──────────────────────────────────────────────────────────────────────→

             W1 (M9-13)                              W2 (M9-14)
             ──────────                              ──────────
             [products]                              [products]
             ADD categories_arr                      DROP COLUMN categories
             ↓                                       ↑
             Deploy Revision A ──── bake ──→ Deploy Revision B ──── bake ≥24h ──┘
             ↓
             BACKFILL products (tức thì, 10 rows)
             
             [orderitem]
             ADD created_at (nullable)
             ↓                                       [orderitem]
             Deploy accounting dual-write            SET NOT NULL (< 1s lock)
             ↓                                       ↑
             VERIFY NULL rows = 0 after watermark    VALIDATE CONSTRAINT
             ↓                                       ↑
             BACKFILL (batch, 395k rows)             ADD CHECK NOT VALID
             ↓                                       ↑
             CREATE INDEX CONCURRENTLY ──────────────┘

             Evidence gates at each step →→→→→→→→→→→→→→→→→→ M9-14 Final Evidence
```

---

**Prepared by:** Team (Đức author)  
**For review:** Hải  
**Mentor sign-off:** Required at M9-15a (due 31/07/2026 AM)
