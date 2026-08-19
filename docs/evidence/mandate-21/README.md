# Mandate #21 — Evidence drill mất AZ 1c (31/07/2026)

Hai lần bắn AWS FIS `aws:network:disrupt-connectivity` vào subnet **private-1c**
(`subnet-0fdf5cd134c155b94`), dưới tải ~2,7 checkout/s, đo bằng **vòng curl ngoài cluster**
(3 path độc lập: `/`, `/api/products`, `/api/cart`) — nguồn sống sót kể cả khi Prometheus rớt.

Bối cảnh store lúc drill: **RDS primary 1c** + **Valkey primary 1c** → 1c là AZ tệ nhất (cả 2 store).

## Run 1 — chỉ FIS NACL (`docs/evidence/mandate-21/run1/`)

- **T0** = 2026-07-31T01:54:05Z · experiment `EXP3eBP7bCoCeEGt4a` · state cuối: **stopped (stop condition)**.
- **Cart hồi ~52s** (503→200): ElastiCache **tự failover** primary 1c→1b, cart reconnect nhanh nhờ
  **REL-17-07** (KeepAlive 180→5s). Trước bản vá: 70s+.
- **RDS KHÔNG tự failover** dưới NACL partition → `/api/products` + checkout 5xx suốt fault.
- Stop-alarm ALB 5xx **tự abort ~T+4ph** (phanh an toàn đúng thiết kế).

## Run 2 — FIS NACL + force RDS failover (`docs/evidence/mandate-21/run2/`)

- **T0** = 2026-07-31T02:07:16Z · experiment `EXPyyNcxXiiuPzQ3L6`.
- Fault ăn vào 02:07:32Z → **trigger `reboot-db-instance --force-failover` lúc 02:08:17Z**.
- **RDS failover 1c→1b**: started 02:08:24Z, completed **02:09:13Z** (~56s). Sau đó
  `describe-db-instances` → primary **ap-southeast-1b**, secondary 1c (bằng chứng directive đòi).
- **RTO đo được** (từ fault 02:07:32Z): `/` browse **~37s**; `/api/cart` **~0** (EC primary đã ở 1b từ
  run1); `/api/products` + checkout (đường RDS) **~2–3 phút** (failover 56s + app reconnect). Money path
  hồi **khi 1c vẫn blackhole** → chứng minh mọi phụ thuộc đã rời 1c (frontend@1a + EC@1b + RDS@1b).
- **RPO = 0**: RDS Multi-AZ đồng bộ, không đơn đã commit nào mất.
- Sau fault: NACL trả nguyên trạng, 8/8 node Ready, money-path AZ-spread 0 single-AZ.

## Kết luận

| Chỉ tiêu | Kết quả |
|---|---|
| RPO | **0** (RDS đồng bộ) |
| RTO browse/cart | **≤ 60s** (frontend@1a + EC auto-failover + REL-17-07) |
| RTO đường DB (checkout/products) | **~2–3 phút** (RDS failover-bound) |
| RDS primary đổi AZ | ✅ 1c→1b |

**Finding vận hành:** ElastiCache tự failover trên network partition; **RDS Multi-AZ (instance) chỉ tự
failover khi AWS phát hiện AZ hỏng thật** (mất điện/hardware), KHÔNG khi chỉ mất kết nối do NACL của khách.
⇒ AZ chết thật: RDS tự failover (~2–3ph tự động). Partition thuần: cần **runbook trigger tay**
(`aws rds reboot-db-instance --db-instance-identifier techx-tf3-postgres --force-failover`).

Đường đo: `external-probe.log` mỗi run (cột: `<utc> <code_/>/<ms> <code_products> <code_cart>`).
Chi tiết thiết kế + cam kết: [ADR 0017](../../adr/0017-mandate-21-az-failover-dr-cdo02.md).
Runbook: [mandate-21-az-failover-drill.md](../../runbooks/mandate-21-az-failover-drill.md).
