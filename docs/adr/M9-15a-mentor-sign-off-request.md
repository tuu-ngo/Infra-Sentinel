# M9-15a: Mentor Sign-Off Request — Schema Migration Design + Deadline Extension

**Request Type:** Design Approval + Deadline Extension  
**Submitted:** 2026-07-30 (Đức)  
**Due:** 2026-07-31 AM (earliest-safe assumption)  
**Original Deadline:** 2026-07-19 (已逾期 11 days)

---

## 1. Executive Summary

**Request:** Approve schema migration design (ADR-M9-07d) for Mandate #9 compliance item #1 and grant deadline extension.

**Core Decision Needed:**
- **Option A (team proposal):** Use 2 tables (`products` for customer read safety + `orderitem` for large-table contract)
- **Option B:** Run full cycle on 1 table (mentor selects which table)

**Current status:** Compliance #1 is **CONDITIONAL** until mentor confirms:
1. Table mapping approach (A or B)
2. Contract execution model: mentor observe W2 live (M9-14) OR approve evidence protocol

---

## 2. Artifacts Provided

### 2.1 Analysis Document
**Location:** `docs/adr/M9-07d-schema-analysis.md`

**Content:**
- Measurement of 2 tables (products: 10 rows, customer READ; orderitem: 395k rows, WRITE path)
- Traffic assessment (RPS, FK dependencies, lock scope)
- Size/index/constraints verification queries

**Key Finding:** System does NOT have single table that is both LARGE (>100k) AND customer-facing.

### 2.2 Migration ADR
**Location:** `docs/adr/M9-07d-schema-migration-adr.md` (595 lines)

**Includes:**
- ✅ Table mapping: `products.categories` TEXT→text[], `orderitem` ADD created_at
- ✅ 2 production windows: W1 (expand+backfill+validate, reversible) + W2 (contract, destructive)
- ✅ SQL skeleton: idempotent DDL với `lock_timeout='1s'` + `statement_timeout`
- ✅ Watermark semantics: backfill sentinel = migration timestamp
- ✅ SET NOT NULL technique: validated CHECK → skip full-table scan
- ✅ Risk register: 7 risks với mitigation
- ✅ Evidence protocol: pre-W1, during-W1, pre-W2, post-W2 queries
- ✅ Rollback plan: W1 reversible, W2 PITR-only
- ✅ Sequence diagram

---

## 3. Key Technical Decisions Requiring Mentor Confirmation

### 3.1 Two-Table Approach (Critical)

**Team Proposal:** Deploy migration on 2 separate tables to demonstrate different aspects:

| Table | Aspect Demonstrated | Justification |
|-------|---------------------|---------------|
| `products` (10 rows) | **Customer read safety**: COALESCE backward-compat + rolling A/B deployment | ListProducts/GetProduct on hot path — proves 0 downtime for customer traffic |
| `orderitem` (395k rows) | **Large-table contract**: backfill + validated CHECK + SET NOT NULL | Proves bounded-lock DDL on production-scale data |

**Alternative (if mentor rejects):** Run full expand→contract on single table.
- If **products**: need to generate synthetic data (current 10 rows insufficient)
- If **orderitem**: need to prove customer impact (current table is write-only, not customer-facing)

**Decision required:** Approve Option A or select Option B table.

---

### 3.2 Watermark Semantics for `orderitem.created_at`

**Context:** Historical rows (pre-migration) don't have real creation timestamp.

**Team Proposal:**
- Backfill `created_at` with **migration watermark sentinel** (fixed timestamp = backfill job start)
- Semantic: *"Value ≤ watermark means 'item created before migration, exact time unknown'"*
- Column name `created_at` remains appropriate (post-dual-write rows have accurate value)

**Alternative (if mentor prefers explicit naming):**
- Rename column to `ingested_at` → semantic = "DB write time, not order creation time"

**Decision required:** Approve `created_at` + sentinel OR require rename to `ingested_at`.

---

### 3.3 W2 Contract Observation Model

**Team Proposal:** Mentor observes W2 (M9-14) **live during execution** OR approves evidence protocol beforehand and reviews evidence afterward.

**Context:** W2 executes:
- `orderitem`: `ALTER COLUMN created_at SET NOT NULL` (bounded-lock, <1s)
- `products`: `DROP COLUMN categories` (irreversible)

Both run **under load** before mentor (fulfills mandate wording "dưới tải").

**Decision required:** 
- [ ] Mentor attends M9-14 live (schedule required)
- [ ] Mentor pre-approves evidence protocol, reviews evidence post-execution

---

### 3.4 VALIDATE CONSTRAINT Timeout

**Context:** `VALIDATE CONSTRAINT` on 395k rows may take 10-60s (depends on IOPS).

**Team Proposal:** Set `statement_timeout = '0'` for VALIDATE step only.
- **Risk:** Long-running statement, but SHARE UPDATE EXCLUSIVE doesn't block writes
- **Mitigation:** Monitor `pg_stat_activity`; abort manually if exceeds SLO

**Alternative:** Set bounded timeout (vd 120s) và retry nếu fail.

**Decision required:** Approve timeout='0' OR specify max duration.

---

### 3.5 Backfill Batch Parameters

**Team Proposal:**
- Batch size: 5,000 rows
- Inter-batch sleep: 100ms
- Total estimate: 395k / 5k × 100ms ≈ **8 seconds** + UPDATE time ≈ 1-2 minutes

**Concern:** FK lock contention on `accounting.order` during UPDATE.

**Mitigation:** `FOR UPDATE SKIP LOCKED` + monitor `pg_locks`.

**Decision required:** Approve batch=5k, sleep=100ms OR adjust parameters.

---

## 4. Risks Disclosed

All 7 risks documented in ADR Section 6, highlight:

| Risk | Impact | Mitigation Status |
|------|--------|-------------------|
| R6: DROP COLUMN khi còn Revision A pods | CRITICAL (parse error) | ✅ Pre-W2 gate: Revision B=100% + bake ≥24h |
| R4: Dual-write không converge | HIGH (backfill vô hạn) | ✅ Verify ORDERITEM_WRITE_CREATED_AT env + null_count |
| R2: CREATE INDEX fail → invalid index | MEDIUM (retry blocked) | ✅ Idempotent cleanup script detects + DROP invalid |

**All risks have documented mitigations.**

---

## 5. Deadline Extension Request

**Original Deadline:** 2026-07-19  
**Current Date:** 2026-07-30 (11 days overdue)  

**Reason for Extension:**
- M9-03 (accounting idempotency) required 1.5d implementation before schema work could start
- Work breakdown (M9-07d → M9-07i → M9-05a) sequential dependency discovered in v3.1
- Earliest-safe schedule depends on mentor response time for M9-15a

**Proposed Extension:**
- **New Final Deadline:** 2026-08-13 (M9-14 completion)
- **Critical Milestone:** M9-15a sign-off by 2026-07-31 AM (enables M9-07i to start 03/08)

**Impact of Late Approval:**
- Each 1-day delay in M9-15a → 1-day slip in M9-14
- Rehearsal (M9-12) cannot start until M9-07i implementation complete
- W2 (M9-14) requires ≥24h bake after W1 (non-negotiable safety)

**Commitment:** If approved by 31/07 AM, team commits to 13/08 final delivery.

---

## 6. Approval Checklist for Mentor

Please confirm in writing (email/comment/document):

- [ ] **Bảng mapping:** Approve Option A (2 tables) OR specify Option B single table
- [ ] **Watermark semantics:** Approve `created_at` + sentinel OR require `ingested_at` rename
- [ ] **W2 observation:** Will attend M9-14 live OR pre-approve evidence protocol
- [ ] **VALIDATE timeout:** Approve `statement_timeout='0'` OR specify max duration (e.g., 120s)
- [ ] **Backfill batch:** Approve batch=5k, sleep=100ms OR adjust parameters
- [ ] **Deadline extension:** Approve new deadline 13/08 OR specify alternative date

---

## 7. Next Steps (Conditional on Approval)

```
[Mentor signs M9-15a] → [M9-07i starts 03/08] → [M9-05a 04/08] → [M9-06 staging 05/08]
                                                                          ↓
                                                             [M9-12 rehearsal 10/08 AM]
                                                                          ↓
                                                             [M9-15b approval 10/08 PM]
                                                                          ↓
                                                             [M9-13 PROD W1 11/08 AM]
                                                                          ↓
                                                             [bake ≥24h, deploy Revision B]
                                                                          ↓
                                                             [M9-15c approval 12/08 PM]
                                                                          ↓
                                                             [M9-14 PROD W2 13/08] ← FINAL
```

**Blocking:** M9-15a delay → entire chain slips.

---

## 8. Contact for Questions

**Primary:** Đức (schema design + SQL implementation)  
**Secondary:** Hải (reviewer, integration lead)  
**Availability:** Daily during work hours, respond within 4h

**Artifacts Ready for Review:**
- Analysis: `docs/adr/M9-07d-schema-analysis.md`
- ADR: `docs/adr/M9-07d-schema-migration-adr.md`
- Summary (this doc): `docs/adr/M9-15a-mentor-sign-off-request.md`

---

## Appendix: Compliance Mapping

Mandate #9 compliance #1 requires:

> **"Online schema migration trên bảng LỚN và ĐƯỜNG ĐỌC KHÁCH không downtime."**

**Our 2-table approach maps to:**

| Requirement Aspect | Mapped Table | Evidence |
|--------------------|--------------|----------|
| **"Bảng LỚN"** (>100k) | `orderitem` (395k rows) | ✅ Section 3 ADR: backfill + contract under load |
| **"ĐƯỜNG ĐỌC KHÁCH"** | `products` (browse/search/get) | ✅ Section 1 ADR: COALESCE + rolling A/B |
| **"Không downtime"** | Both tables | ✅ Evidence protocol + M9-00 7 conditions gate |
| **"Dưới tải"** | W1 + W2 production | ✅ RPS floor matrix + route-level traffic |

**Mentor confirmation needed:** Is 2-table approach acceptable for mandate compliance?

---

**Submitted:** 2026-07-30  
**Signature:** Đức (on behalf of team)  
**Awaiting:** Mentor written approval
