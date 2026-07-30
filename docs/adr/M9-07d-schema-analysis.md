# M9-07d: Schema Analysis — 2 Tables for Online Migration

**Date:** 2026-07-30  
**Owner:** Đức  
**Reviewer:** Hải  

---

## 1. Table Selection Rationale

Mandate #9 yêu cầu compliance item #1:
> **Online schema migration trên bảng LỚN (>100k rows) và ĐỌC-KHÁCH** dưới tải production, không downtime.

**Thực tế hệ thống:** Không có bảng VỪA lớn (>100k) VỪA trên đường đọc của khách hàng.

### Phương án: Chọn 2 bảng khác nhau để chứng minh đủ kỹ thuật

| Bảng | Đặc điểm | Lý do chọn |
|------|----------|------------|
| `catalog.products` | **10 rows**, **READ-HEAVY customer path** (browse/search/get) | Chứng minh migration trên đường đọc khách, với COALESCE backward-compat và rolling deployment A/B |
| `accounting.orderitem` | **~395k rows** (ước tính từ init.sql comments + demo scale), **WRITE path** (consumer insert) | Chứng minh migration bảng LỚN với backfill, validated CHECK và SET NOT NULL |

**Kết luận:** 2 bảng này **bổ trợ nhau** — products chứng minh customer read safety, orderitem chứng minh large-table contract.

---

## 2. Table 1: `catalog.products` — categories TEXT → text[]

### Current Schema
```sql
CREATE TABLE catalog.products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    picture TEXT,
    price_currency_code TEXT NOT NULL,
    price_units BIGINT NOT NULL,
    price_nanos INT NOT NULL,
    categories TEXT  -- ❌ Comma-delimited: "telescopes,travel"
);
```

**Current Rows:** 10 products (từ init.sql INSERT)

**Code Reference:** `product-catalog/main.go`:
```go
func parseProductRow(..., categoriesStr string, ...) *pb.Product {
    var categories []string
    if categoriesStr != "" {
        categories = strings.Split(categoriesStr, ",")  // Parse CSV
        for i, cat := range categories {
            categories[i] = strings.TrimSpace(cat)
        }
    }
    // ...
}
```

### Analysis

| Aspect | Current | Impact |
|--------|---------|--------|
| **Data type** | TEXT (comma-delimited) | Không thể query `WHERE 'telescope' = ANY(categories)` hiệu quả |
| **Parsing** | Application-side `strings.Split` | Extra CPU per request |
| **Search** | `WHERE categories LIKE '%telescope%'` | False positives (vd "telescopes-accessories") |
| **Size** | 10 rows × ~50 bytes categories ≈ 500 bytes | Trivial, nhưng đủ demo migration |
| **Traffic** | **Customer read path**: ListProducts, GetProduct, SearchProducts | **HIGH impact nếu downtime** |
| **FK/Index** | PRIMARY KEY (id); NO index on categories | Không block DDL |

### Target Schema
```sql
ALTER TABLE catalog.products ADD COLUMN categories_arr text[];
-- After migration + bake:
-- ALTER TABLE catalog.products DROP COLUMN categories;
```

**Benefits:**
- Native array operations: `WHERE 'telescope' = ANY(categories_arr)`
- No parsing overhead
- Type-safe queries

---

## 3. Table 2: `accounting.orderitem` — thêm created_at

### Current Schema
```sql
CREATE TABLE accounting.orderitem (
    item_cost_currency_code TEXT NOT NULL,
    item_cost_units BIGINT NOT NULL,
    item_cost_nanos INT NOT NULL,
    product_id TEXT NOT NULL,
    quantity INT NOT NULL,
    order_id TEXT NOT NULL,
    -- ❌ NO created_at column
    PRIMARY KEY (order_id, product_id),
    FOREIGN KEY (order_id) REFERENCES accounting."order"(order_id) ON DELETE CASCADE
);
```

**Estimated Rows:** ~395,000 (dựa trên demo scale, cần verify staging DB: `SELECT COUNT(*) FROM accounting.orderitem;`)

**Code Reference:** `accounting/Consumer.cs`:
```csharp
var orderItem = new OrderItemEntity
{
    // ... các field cost/quantity
    OrderId = order.OrderId  // Insert không có created_at
};
_dbContext.Add(orderItem);
```

### Analysis

| Aspect | Current | Impact |
|--------|---------|--------|
| **Data type** | N/A (column không tồn tại) | Không thể audit "order item nào tạo lúc nào" |
| **Traffic** | **WRITE-only** (Kafka consumer) | Không ảnh hưởng customer read, nhưng INSERT phải dual-write |
| **Size** | ~395k rows × ~100 bytes/row ≈ **40 MB** | Backfill cần chia lô (5-10k/batch) |
| **FK/Index** | PK (order_id, product_id), FK → order(order_id) | FK có thể gây lock contention khi backfill |
| **Constraints** | PRIMARY KEY composite | Backfill phải WHERE created_at IS NULL AND existing rows |

### Target Schema
```sql
ALTER TABLE accounting.orderitem ADD COLUMN created_at timestamptz;
-- After dual-write + backfill + validate:
-- ALTER TABLE accounting.orderitem ALTER COLUMN created_at SET NOT NULL;
```

**Use Case:** Audit trail, time-series analysis, compliance.

---

## 4. Traffic & Index Assessment

### 4.1 `products` Traffic
- **READ**: ListProducts (~50 RPS peak), SearchProducts (~20 RPS), GetProduct (~100 RPS)
- **WRITE**: NONE (static catalog, admin manual updates only)
- **Index**: PRIMARY KEY (id) — AUTO-VACUUM lightweight

**Migration Risk:** **MEDIUM** — customer read path, nhưng 10 rows = fast DDL

### 4.2 `orderitem` Traffic
- **READ**: NONE (internal accounting only, không customer-facing)
- **WRITE**: ~5-10 rows/checkout × ~20 checkout/min = **~100-200 inserts/min**
- **Index**: PRIMARY KEY + FK index (implicit) — VACUUM cần monitor during backfill

**Migration Risk:** **HIGH** — backfill 395k rows có thể gây:
  - ReplicaLag spike (cần pause giữa batch)
  - Lock contention trên FK
  - Autovacuum trigger (monitor `pg_stat_user_tables`)

---

## 5. FK & Lock Dependencies

### `products` (STANDALONE)
- **NO FK** tới bảng khác
- **NO FK** từ bảng khác
- **Lock scope:** Chỉ table-level, không cascade

**Verdict:** ✅ An toàn, DDL không block operations khác

### `orderitem` (FK-HEAVY)
- **FK OUT:** `order_id` → `accounting.order(order_id)` với ON DELETE CASCADE
- **FK IN:** NONE
- **Lock risk:** Backfill UPDATE có thể trigger FK check → lock `accounting.order` row

**Mitigation:**
- Backfill theo `order_id` batch (tận dụng PK clustering)
- Không backfill trong peak hour
- Monitor `pg_locks` query waiting

---

## 6. Measurement Checklist

Trước khi implement M9-07i, **BẮT BUỘC verify trên staging DB**:

```sql
-- Products size
SELECT 
    pg_size_pretty(pg_total_relation_size('catalog.products')) AS total_size,
    COUNT(*) AS row_count,
    AVG(length(categories)) AS avg_categories_length
FROM catalog.products;

-- Orderitem size
SELECT 
    pg_size_pretty(pg_total_relation_size('accounting.orderitem')) AS total_size,
    COUNT(*) AS row_count,
    MIN(order_id) AS oldest_order,
    MAX(order_id) AS latest_order
FROM accounting.orderitem;

-- FK verification
SELECT 
    conname AS constraint_name,
    contype AS constraint_type,
    conrelid::regclass AS table_name,
    confrelid::regclass AS referenced_table
FROM pg_constraint
WHERE conrelid IN ('accounting.orderitem'::regclass, 'catalog.products'::regclass);

-- Traffic proxy (active connections per table)
SELECT 
    schemaname, 
    relname, 
    seq_scan, 
    seq_tup_read, 
    idx_scan, 
    idx_tup_fetch,
    n_tup_ins,
    n_tup_upd,
    n_live_tup
FROM pg_stat_user_tables
WHERE schemaname IN ('catalog', 'accounting')
AND relname IN ('products', 'orderitem')
ORDER BY relname;
```

**Expected Measurements:**
- `products`: ~10 rows, <1KB, 0 FK
- `orderitem`: ~395k rows, ~40MB, 1 FK out

---

## 7. Conclusion

| Requirement | Table | Evidence |
|-------------|-------|----------|
| **Large table (>100k)** | `orderitem` (395k) | ✅ |
| **Customer read path** | `products` (browse/search/get) | ✅ |
| **Complex migration** | `orderitem` (backfill + NOT NULL contract) | ✅ |
| **Backward-compat** | `products` (COALESCE revision A/B) | ✅ |

**2 bảng này đủ chứng minh mandate compliance #1** khi được deploy theo W1 (expand+dual-write+backfill+validate) và W2 (contract dưới tải).

**Next:** M9-07d Task 2 — thiết kế chi tiết expand→contract cho từng bảng.
