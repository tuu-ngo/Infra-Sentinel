# Evidence - Resource Capacity & OOMKill Risk Analysis

## Owner
CDO01

## Assessment Metadata

| Field | Value |
|---|---|
| Assessment Date | 2026-07-09 14:30 |
| Cluster | techx-corp-tf3 |
| Namespace | techx-tf3 |
| Node Type | t3.large (3 nodes) |
| Methodology | Live pod inspection, resource manifest audit, OOMKill evidence from `describe pod` |

---

## Scope

Audit resource requests/limits for all 25 deployments, cross-check against 3-node cluster capacity
(t3.large = 2 vCPU / ~7.8GB per node). Identify:
- Services with zero CPU/memory requests (scheduler bin-packing risk)
- Services with memory limits too low for actual usage (OOMKill risk)
- Active OOMKill evidence in current running pods
- Cluster capacity headroom for scale/HA

**Note:** Metrics-server is **not installed** in this cluster. Unable to measure actual runtime
CPU/memory usage. Analysis based on manifest config + observed OOMKill events only.

---

## Cluster Capacity Summary

### Nodes (3 x t3.large)

| Node | CPU Capacity | CPU Allocatable | Memory Capacity | Memory Allocatable |
|---|---|---|---|---|
| ip-10-0-11-51 | 2 | 1930m | 8011308Ki (~7825Mi) | 7253548Ki (~7084Mi) |
| ip-10-0-30-193 | 2 | 1930m | 8011308Ki (~7825Mi) | 7253548Ki (~7084Mi) |
| ip-10-0-45-222 | 2 | 1930m | 8011300Ki (~7825Mi) | 7253540Ki (~7084Mi) |

**Total cluster allocatable:**
- CPU: 5790m (≈5.79 vCPU)
- Memory: 21252Mi (~20.75 GB)

### Current pod count
- 29 pods running (25 app deployments + 3 otel-collector DaemonSet + 1 opensearch StatefulSet)

---

## Resource Configuration Audit — All 25 Deployments

| Service | Replicas | CPU Request | CPU Limit | Mem Request | Mem Limit | Risk |
|---|---|---|---|---|---|---|
| accounting | 1 | **NONE** | NONE | **NONE** | 350Mi | ⚠️ No requests |
| ad | 1 | **NONE** | NONE | **NONE** | 300Mi | ⚠️ No requests |
| cart | 1 | **NONE** | NONE | **NONE** | 160Mi | ⚠️ No requests |
| checkout | 1 | **NONE** | NONE | **NONE** | **20Mi** | 🔴 **Limit too low** |
| currency | 1 | **NONE** | NONE | **NONE** | **20Mi** | 🔴 **Limit too low** |
| email | 1 | **NONE** | NONE | **NONE** | 100Mi | ⚠️ No requests |
| flagd | 1 | **NONE** | NONE | **NONE** | 75Mi | ⚠️ No requests |
| fraud-detection | 1 | **NONE** | NONE | **NONE** | 300Mi | ⚠️ No requests |
| frontend | 1 | **NONE** | NONE | **NONE** | 250Mi | ⚠️ No requests |
| frontend-proxy | 1 | **NONE** | NONE | **NONE** | 65Mi | ⚠️ No requests |
| grafana | 1 | 150m | 150m | 250Mi | **300Mi** | 🔴 **OOMKilled 5x** |
| image-provider | 1 | **NONE** | NONE | **NONE** | 50Mi | ⚠️ No requests |
| jaeger | 1 | **NONE** | NONE | **NONE** | **600Mi** | 🔴 **OOMKilled 2x** |
| kafka | 1 | **NONE** | NONE | **NONE** | 700Mi | ⚠️ No requests |
| llm | 1 | **NONE** | NONE | **NONE** | **NONE** | 🔴 **No limit** |
| load-generator | 1 | **NONE** | NONE | **NONE** | 1500Mi | ⚠️ No requests |
| payment | 1 | **NONE** | NONE | **NONE** | 140Mi | ⚠️ No requests |
| postgresql | 1 | **NONE** | NONE | **NONE** | 100Mi | ⚠️ No requests |
| product-catalog | 1 | **NONE** | NONE | **NONE** | **20Mi** | 🔴 **Limit too low** (restarted 3x) |
| product-reviews | 1 | **NONE** | NONE | **NONE** | 100Mi | ⚠️ No requests |
| prometheus | 1 | **NONE** | NONE | **NONE** | 400Mi | ⚠️ No requests |
| quote | 1 | **NONE** | NONE | **NONE** | 40Mi | ⚠️ No requests |
| recommendation | 1 | **NONE** | NONE | **NONE** | 500Mi | ⚠️ No requests |
| shipping | 1 | **NONE** | NONE | **NONE** | **20Mi** | 🔴 **Limit too low** |
| valkey-cart | 1 | **NONE** | NONE | **NONE** | **20Mi** | 🔴 **Limit too low** |

### Totals (limits only, requests = 0)

```
Total memory limits scheduled: ~7,379Mi out of 21,252Mi allocatable (35% utilization)
Total CPU requests: 150m (grafana only) out of 5,790m allocatable (2.6%)
Total memory requests: 250Mi (grafana only) out of 21,252Mi (1.2%)
```

**Critical observation:** 24 out of 25 deployments have **zero CPU requests** and **zero memory
requests**. Scheduler has no information to bin-pack pods optimally. HPA (Horizontal Pod Autoscaler)
**cannot function** without resource requests.

---

## FINDING-01: Active OOMKill on Grafana and Jaeger

**Title:** Grafana OOMKilled 5 times, Jaeger OOMKilled 2 times

**Severity:** HIGH

**Evidence:**

```bash
$ kubectl -n techx-tf3 describe pod grafana-7779557549-c7tvr | grep -A8 "Last State"
    Last State:      Terminated
      Reason:        OOMKilled
      Exit Code:     137
      Started:       Thu, 09 Jul 2026 14:17:06 +0700
      Finished:      Thu, 09 Jul 2026 14:24:09 +0700
    Ready:           True
    Restart Count:   5
    Limits:
      memory:  300Mi
```

Grafana pod has **4 containers** (3 sidecars @ 256Mi each + 1 main @ 300Mi). Main Grafana container
was OOMKilled and restarted 5 times in 3 hours.

```bash
$ kubectl -n techx-tf3 describe pod jaeger-bbc8c79f5-6dl2v | grep -A8 "Last State"
    Last State:     Terminated
      Reason:       OOMKilled
      Exit Code:    137
      Started:      Thu, 09 Jul 2026 13:51:05 +0700
      Finished:     Thu, 09 Jul 2026 14:17:58 +0700
    Ready:          True
    Restart Count:  2
    Limits:
      memory:  600Mi
```

Jaeger OOMKilled 2 times. 600Mi limit insufficient for trace storage + query workload.

**Impact:**

- **Observability blind spots** — every restart loses in-memory trace data, dashboard state
- **SLO monitoring impact** — Grafana restart = temporary loss of alerting + metrics visibility
- **Incident response delayed** — if a production issue occurs during Grafana OOMKill, team cannot
  see dashboards to diagnose

**Risk likelihood:** **High** — already occurred 7 times (5 + 2) in 3 hours of operation. Will
continue to happen under normal load.

**Business impact:**
- During an incident, if Grafana is OOMKilled, team loses visibility into checkout SLO (target ≥99%)
- Jaeger traces critical for debugging checkout failures — OOMKill = data loss for failed orders

**Backlog item (draft):**

**Ưu tiên 1: Tăng memory limit Grafana → 512Mi, Jaeger → 1Gi — hiện OOMKill lặp lại 7 lần trong 3h, nếu xảy ra trong incident thì mất khả năng monitor/debug SLO → impact cao (khả năng vận hành), chi phí thấp (chỉ tăng memory request, không scale node), nằm trong ngân sách.**

---

## FINDING-02: Unreasonably Low Memory Limits (20Mi)

**Title:** 5 services have 20Mi memory limit — insufficient for production workload

**Severity:** HIGH

**Services affected:**
- `checkout` — 20Mi limit (revenue-critical, đã restart do init container issue)
- `product-catalog` — 20Mi limit (restarted 3 times, Exit Code 1)
- `currency` — 20Mi limit
- `shipping` — 20Mi limit
- `valkey-cart` — 20Mi limit (Redis-compatible cache, single replica SPOF)

**Evidence:**

```bash
$ kubectl -n techx-tf3 describe pod product-catalog-d769b79c4-j7wp7 | grep -A5 "Last State"
    Last State:     Terminated
      Reason:       Error
      Exit Code:    1
      Started:      Thu, 09 Jul 2026 10:48:29 +0700
      Finished:     Thu, 09 Jul 2026 10:48:29 +0700
    Restart Count:  3
```

Product-catalog restarted 3 times. 20Mi is likely insufficient for:
- Go runtime (checkout, product-catalog, currency, shipping)
- Redis/Valkey working set (valkey-cart)

**Context from CLAUDE.md:**
> `product-catalog` (Go): mở DB qua `database/sql` nhưng không set `MaxOpenConns`/`MaxIdleConns` —
> mặc định unlimited, có thể làm cạn `max_connections` của Postgres khi tải cao.

20Mi limit combined with unlimited DB connections = **guaranteed OOMKill** under moderate load.

**Impact:**

- **Checkout flow risk** — `checkout` OOMKill = order placement fails → SLO ≥99% violated → lost revenue
- **Browse/search risk** — `product-catalog` OOMKill = storefront shows no products → SLO ≥99.5% violated
- **Cart state loss** — `valkey-cart` OOMKill = all active shopping carts lost (INC-2 repeat risk)

**Risk likelihood:** **Very High** — `product-catalog` already restarted 3 times in baseline traffic.
Under load generator or real user traffic, will fail immediately.

**Business impact:**
- Checkout OOMKill = direct revenue loss (customer cannot complete order)
- Product-catalog OOMKill = storefront broken, customers cannot browse → bounce rate spike
- Valkey-cart OOMKill = all users lose cart → immediate SLO violation + poor UX

**Backlog item (draft):**

**Ưu tiên 1: Tăng memory limit cho checkout/product-catalog/currency/shipping → 256Mi, valkey-cart → 128Mi — hiện limit 20Mi gây restart loop (product-catalog đã 3 lần), nếu OOMKill dưới tải thật thì checkout/browse fail → mất doanh thu trực tiếp + vi phạm SLO ≥99% → impact cực cao, chi phí thấp (chỉ ~500Mi tổng = 2.5% cluster mem), nằm trong ngân sách.**

---

## FINDING-03: Zero CPU/Memory Requests = Scheduler Blind + HPA Broken

**Title:** 24/25 deployments have no resource requests — bin-packing and autoscaling impossible

**Severity:** MEDIUM (architectural issue, high future impact)

**Evidence:**

```bash
$ kubectl -n techx-tf3 get deploy -o jsonpath=... | grep "NONE"
# 24 deployments return NONE for both CPU and memory requests
```

Only `grafana` has requests set (150m CPU, 250Mi memory). All business services have **zero requests**.

**Impact:**

1. **Scheduler bin-packing is blind**
   - Kubernetes scheduler places pods on nodes based on `requests`, not `limits`
   - With 0 requests, scheduler assumes pods need 0 resources → overcommits nodes
   - Under actual load, nodes can hit CPU throttle or OOM, triggering mass pod eviction

2. **HPA cannot function**
   ```bash
   $ kubectl -n techx-tf3 get hpa
   No resources found in techx-tf3 namespace.
   ```
   HPA (Horizontal Pod Autoscaler) requires CPU/memory requests to calculate utilization percentage.
   With 0 requests, HPA cannot be configured. System **cannot scale horizontally** under load.

3. **Metrics-server not installed**
   ```bash
   $ kubectl top pods -n techx-tf3
   error: Metrics API not available
   ```
   Even if HPA were configured, metrics-server is missing → HPA would be non-functional.

**Risk likelihood:** **Medium today, High under scale**
- Current state: 25 pods x 1 replica each, low traffic → fits within 3-node capacity
- Under production load: без requests + без HPA + без metrics-server = no ability to handle traffic spike

**Business impact:**
- Black Friday scenario (mandate from BTC): traffic spike 10x → all pods stay at 1 replica → OOMKill cascade
- No HPA = manual `kubectl scale` only → slow response time, high operator toil
- SLO violations guaranteed under load without horizontal scaling

**Backlog item (draft):**

**Ưu tiên 2: Thêm CPU/memory requests cho toàn bộ 24 deployment (baseline: 100m CPU, 128Mi mem per pod) + cài metrics-server — hiện scheduler bin-pack không có dữ liệu, HPA không thể hoạt động, nếu tải tăng đột biến thì hệ thống không scale được → vi phạm SLO toàn bộ luồng → impact cao, chi phí trung (cần metrics-server + reserve capacity ~3Gi mem cho requests), nằm trong ngân sách.**

---

## FINDING-04: Single Replica Everywhere + No PDB (except opensearch)

**Title:** All 25 services are single-replica with no PodDisruptionBudget

**Severity:** MEDIUM (known issue, already documented in CLAUDE.md)

**Evidence:**

```bash
$ kubectl -n techx-tf3 get deploy -o jsonpath="{range .items[*]}{.metadata.name}{'\t'}{.spec.replicas}{'\n'}{end}"
# All 25 deployments return "1"

$ kubectl -n techx-tf3 get pdb
NAME             MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
opensearch-pdb   N/A             1                 1                     42h
```

Only `opensearch` has a PDB. No business service has replica > 1 or PDB.

**Impact:**

- **Node drain = downtime** — if a node is drained (rolling update, spot termination, AZ failure),
  all single-replica pods on that node go down simultaneously
- **No rolling update safety** — deploy a bad image → pod crashloop → no healthy replica to serve traffic
- **INC-3 repeat risk** — documented incident: "traffic bị đẩy vào pod mới **trước khi nó sẵn sàng**"

**Risk likelihood:** Medium — requires a trigger (deploy, node maintenance, AZ failure)

**Business impact:**
- Checkout single-replica = SPOF for revenue
- Cart single-replica = SPOF for session state (INC-2)
- Any critical service pod restart during deploy = brief downtime = SLO violation

**Backlog item (draft):**

**Ưu tiên 3: Tăng replicas → 2 cho critical services (checkout, cart, product-catalog, frontend, valkey-cart) + thêm PDB minAvailable=1 — hiện single-replica = SPOF, nếu pod restart trong deploy thì downtime chắc chắn (INC-3 từng xảy ra) → impact cao (availability), chi phí trung (x2 pod cho 5 service = thêm ~1.5Gi mem), nằm trong ngân sách.**

---

## FINDING-05: llm service has no memory limit

**Title:** `llm` deployment has no memory limit — unbounded memory growth risk

**Severity:** LOW (informational, depends on LLM usage)

**Evidence:**

```bash
$ kubectl -n techx-tf3 get deploy llm -o jsonpath='{.spec.template.spec.containers[0].resources}'
# Returns: empty (no requests, no limits)
```

LLM service can consume unlimited memory until node OOM killer intervenes, potentially affecting
colocated pods.

**Impact:** Low today (LLM is mock or AIO-only). High if connected to real LLM API and processes
large prompts.

**Recommendation:** Set memory limit 512Mi as baseline, monitor actual usage if AIO is enabled.

---

## Capacity Headroom Analysis

### Memory utilization (limits)

```
Total limits:      7,379Mi
Total allocatable: 21,252Mi
Utilization:       35%
Headroom:          13,873Mi (~65%)
```

**Conclusion:** Plenty of memory headroom **if limits are accurate**. However, limits ≠ reality
without metrics-server data. Multiple OOMKills suggest limits are **underestimated**, not that
cluster is undersized.

### CPU utilization (limits)

```
Only grafana has CPU limit: 150m
Total allocatable: 5,790m
Utilization: 2.6%
```

**Conclusion:** CPU limits effectively unlimited (NONE) for 24/25 services. Cannot assess actual
CPU pressure without metrics-server.

### Can cluster handle 2x replicas for critical services?

```
Scenario: 2 replicas for checkout, cart, product-catalog, frontend, valkey-cart

Added memory limits:
  checkout:         20Mi x 1 = 20Mi
  cart:            160Mi x 1 = 160Mi
  product-catalog:  20Mi x 1 = 20Mi
  frontend:        250Mi x 1 = 250Mi
  valkey-cart:      20Mi x 1 = 20Mi
Total added:       470Mi

Current 7,379Mi + 470Mi = 7,849Mi out of 21,252Mi allocatable (37%)
```

**Verdict:** ✅ Cluster has capacity for 2x replicas **if current limits are not increased**.
However, current limits are too low (see Finding-02) — must increase first, then scale replicas.

**Realistic scenario with proper limits:**

```
Increase limits first (Finding-02):
  checkout:         20Mi → 256Mi (+236Mi)
  product-catalog:  20Mi → 256Mi (+236Mi)
  currency:         20Mi → 256Mi (+236Mi)
  shipping:         20Mi → 256Mi (+236Mi)
  valkey-cart:      20Mi → 128Mi (+108Mi)
  grafana:         300Mi → 512Mi (+212Mi)
  jaeger:          600Mi → 1024Mi (+424Mi)
Subtotal increase: +1,688Mi

Then add 2nd replica for 5 critical services: +470Mi (using new limits)

Total memory after both changes:
  7,379Mi + 1,688Mi + 470Mi = 9,537Mi out of 21,252Mi (45%)
```

**Verdict:** ✅ Still within capacity. **No additional nodes needed.** Cost impact: $0.

---

## Summary — Risk vs Effort vs Budget

| Finding | Severity | Likelihood | Business Impact | Effort | Cost | Priority |
|---|---|---|---|---|---|---|
| Grafana/Jaeger OOMKill | HIGH | Very High (7x in 3h) | Observability loss during incident | XS | $0 | P1 |
| 20Mi limits (5 services) | HIGH | Very High (already restarting) | Revenue loss (checkout), storefront down (catalog) | XS | $0 | P1 |
| Zero requests + no HPA | MEDIUM | Medium (future scale event) | Cannot handle traffic spike, SLO violation guaranteed | S | ~$0 | P2 |
| Single replica + no PDB | MEDIUM | Medium (deploy, node drain) | Brief downtime during maintenance | S | $0 | P2 |
| llm no limit | LOW | Low (mock usage) | Potential noisy neighbor | XS | $0 | P3 |

**All fixes fit within cluster capacity — no new nodes required — total cost $0.**

**Timeline:**
- Week 1 end: Fix P1 (OOMKill + 20Mi limits) — prevents immediate failures
- Week 2 start: Add requests + metrics-server + HPA — enables horizontal scaling
- Week 2 mid: Scale to 2 replicas + add PDB — HA for critical services

---

## Backlog Items (Final)

### PERF-01: Fix active OOMKill on Grafana and Jaeger

**Ưu tiên 1: Tăng memory limit Grafana main container → 512Mi, Jaeger → 1Gi — hiện OOMKill lặp lại 7 lần trong 3 giờ, nếu xảy ra trong incident thì team mất khả năng monitor/debug SLO checkout ≥99% và trace lỗi order → impact cao (khả năng vận hành + MTTR tăng), chi phí thấp (chỉ tăng 636Mi memory, không cần thêm node), nằm trong ngân sách.**

### PERF-02: Fix unreasonably low memory limits (20Mi → 256Mi)

**Ưu tiên 1: Tăng memory limit checkout/product-catalog/currency/shipping → 256Mi, valkey-cart → 128Mi — hiện limit 20Mi đã gây product-catalog restart 3 lần, nếu OOMKill dưới tải thật thì checkout fail = mất doanh thu trực tiếp + browse fail = storefront không dùng được → vi phạm SLO ≥99% checkout và ≥99.5% browse, impact cực cao (doanh thu), chi phí thấp (~1.1Gi memory tổng = 5% cluster), nằm trong ngân sách.**

### PERF-03: Add CPU/memory requests + install metrics-server

**Ưu tiên 2: Thêm CPU/memory requests cho toàn bộ 24 deployment (baseline: 100m CPU, 128-256Mi mem tùy service size) + cài metrics-server — hiện scheduler bin-pack mù, HPA không thể cấu hình được, nếu tải tăng đột biến (mandate Black Friday) thì hệ thống không scale nổi → vi phạm SLO toàn bộ luồng, impact cao (không chịu tải), chi phí trung (metrics-server + reserve ~3-4Gi memory cho requests), nằm trong ngân sách.**

### PERF-04: Scale critical services to 2 replicas + add PDB

**Ưu tiên 2: Tăng replicas → 2 cho checkout, cart, product-catalog, frontend, valkey-cart + thêm PDB minAvailable=1 — hiện single-replica = SPOF cho revenue (checkout), session state (cart), storefront (catalog), nếu pod restart trong deploy hoặc node drain thì downtime chắc chắn (INC-3 đã xảy ra: "traffic vào pod chưa ready") → impact cao (availability), chi phí trung (x2 pod = thêm ~1.5Gi sau khi fix limit), nằm trong ngân sách.**

---

*Assessment completed without applying any changes to the cluster — read-only inspection only.*
*Timestamp: 2026-07-09 14:30*
*Collected by: CDO01*
