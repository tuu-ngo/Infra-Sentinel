# ADR 0017 — Mandate #21: Chịu mất một Availability Zone không mất dữ liệu (CDO02)

**Ngày:** 2026-07-30
**Người quyết định (ký):** Huu Tai Ngo — CDO02 (Reliability + Cost Optimization)
**Directive:** `MANDATE-21-dr-failover.md` — mất 1 AZ đột ngột dưới tải, khách gần như không hay biết
**Tiên quyết:** Mandate #20 (backup + PITR restore drill) — ĐÃ ĐẠT (ADR 0016, evidence 2026-07-29)
**Trạng thái:** Thiết kế chốt; GAP 1 + REL-17-07 đã sửa & deploy; **drill FIS 1c ĐÃ CHẠY 31/07 dưới tải** — RTO/RPO đo được ở mục "Kết quả drill" (RPO=0; RTO browse/cart ≤60s, đường DB ≤3ph; RDS cần runbook failover cho network-partition)
**Tham chiếu:** runbook [`docs/runbooks/mandate-21-az-failover-drill.md`](../runbooks/mandate-21-az-failover-drill.md) · [`mandate-17-fis-az-drill.md`](../runbooks/mandate-17-fis-az-drill.md) · script `scripts/ops/az-spread-check.py`, `scripts/ops/az-drill-measure.py`

## Bối cảnh

Mandate #20 cho khả năng **lấy lại dữ liệu sau khi mất**. Mandate #21 khó hơn: **mất trọn một AZ đột
ngột, giữa lúc có tải**, hệ phải tự đứng vững hoặc phục hồi nhanh mà khách gần như không thấy — không ngồi
chờ restore tay. Khác Directive #3 (bảo trì có kế hoạch, chủ động drain, biết trước): đây là **chết bất
ngờ**. Mentor sẽ **chủ động gây mất một AZ bất kỳ, lúc bất kỳ** — nên phải xây để chịu **mọi AZ, mọi lúc**.

**Bar bắt buộc:** mất 1 AZ → **0 mất dữ liệu (RPO=0)** + luồng browse → cart → checkout phục hồi trong
**RTO cam kết**, đơn đang checkout không mất. Chứng minh bằng số trên dashboard, dưới tải.

## Trạng thái nền tảng (đo live 2026-07-30)

| Hạng mục | Trạng thái |
|---|---|
| RDS PostgreSQL | Multi-AZ ✓ — primary **1c**, secondary **1b**, replicate đồng bộ |
| ElastiCache Valkey | MultiAZ + AutomaticFailover **enabled** ✓ — primary `001`@**1b**, replica `002`@**1c** |
| MSK Kafka | 3 broker / **3 AZ** (1a+1b+1c) ✓ — RF=3, producer acks=all (REL-09) |
| Node EKS | 8 node / **3 AZ** (1a/1b/1c) ✓ |
| Money-path replica | mọi service (frontend, frontend-proxy, cart, checkout, payment, product-catalog, quote, shipping, currency) **≥2 replica trải 2 AZ**, có PDB `minAvailable=1` + topologySpread zone `maxSkew=1 DoNotSchedule` ✓ |

## Quyết định

**1. Kiến trúc DR = active-active đa AZ ở tầng compute + managed Multi-AZ với auto-failover ở tầng store.**
Không dựng standby lạnh/đắt: mọi đồng chi phí đi kèm khả năng drill được (ràng buộc directive).

**2. Cơ chế drill = AWS FIS `aws:network:disrupt-connectivity`** (không phải cordon/drain — đó là Mandate #3).
FIS blackhole NACL của subnet AZ mục tiêu → cắt traffic vào/ra đúng như sự cố AZ thật, tự rollback sau PT5M,
có stop-condition alarm (ALB 5xx) tự abort. Template AZ-tham-số-hoá (`fis_target_az`), tái dùng cho mọi AZ.
Drill **1c trước** vì là AZ tệ nhất (giữ RDS primary + 2 frontend + ElastiCache replica + 1 broker + 1 gateway).

**3. Sửa SPOF theo AZ đã phát hiện (GAP 1):** frontend từng có **2/2 replica dồn 1c** (topologySpread đúng
nhưng K8s không rebalance sau node churn) → `rollout restart` đưa về **1a+1c**; audit `az-spread-check.py`
xác nhận **0 money-path single-AZ**. Đây là điều kiện cần để mất 1c không sập storefront.

## RTO / RPO cam kết (ở mức mất 1 AZ)

| Chỉ tiêu | Cam kết | Cơ sở |
|---|---|---|
| **RPO (mất dữ liệu)** | **0** | RDS Multi-AZ replicate **đồng bộ** (đơn đã commit sống sót failover); MSK RF=3 + acks=all không mất message; ElastiCache cart tái dựng được, không phải nguồn sự thật đơn hàng |
| **RTO — checkout SLO về ngưỡng** | **≤ 3 phút** | Bao trọn cửa sổ RDS Multi-AZ failover (60–120s) + gỡ endpoint AZ chết + reschedule pod. Nếu AZ mất **không** chứa primary của store đang ghi → kỳ vọng **ride-through không dip** |
| **RTO — browse/cart** | **≤ 60s** | Không phụ thuộc failover ghi; chỉ cần gỡ endpoint AZ chết + traffic dồn AZ lành |

> Số cam kết là **target thiết kế**; drill FIS 1c dưới tải sẽ đo **RTO/RPO thực** và ADR này cập nhật số đo
> vào mục "Kết quả drill" sau khi chạy. Đo bằng: vòng curl ngoài (RTO góc khách hàng), `az-drill-measure.py`
> (SLO/Prometheus), RDS console (primary đổi AZ), Grafana (traffic/node).

## Tự động vs cần runbook

| Việc | Tự động? |
|---|---|
| Gỡ endpoint pod AZ chết khỏi Service | ✅ tự động (readiness + kube-proxy/endpoints) |
| Reschedule pod sang AZ lành | ✅ tự động (scheduler + topologySpread; HPA scale theo tải) |
| RDS failover primary → secondary | 🟡 **tự động khi AWS phát hiện AZ hỏng thật** (mất điện/hardware); 🔶 **cần runbook trigger** khi chỉ là network-partition (NACL/FIS) — xem "Kết quả drill" + quyết định posture dưới |
| ElastiCache failover | ✅ tự động (AutomaticFailover enabled) |
| Traffic khách dồn sang AZ lành | ✅ tự động (CloudFront → ALB → Envoy; cloudflared có replica đa AZ) |
| **Failback** RDS primary về AZ gốc sau khi AZ hồi | 🔶 runbook — có chủ đích làm ngoài giờ, không bắt buộc để giữ SLO |
| Bổ sung node elastic ở AZ lành nếu HPA cần thêm capacity | 🔶 phụ thuộc Karpenter/fallback + GAP 2 (xem dưới) |

## Đánh đổi đã chấp nhận (nói thẳng, không giấu)

1. **NAT gateway đơn ở 1a.** Cả 3 private subnet chung 1 route table trỏ NAT ở public-1a. **Mất 1a → cụm
   mất egress** (ECR pull, API ngoài không có VPC endpoint). Luồng ra tiền vẫn sống (mỗi service còn replica
   @1c) và khách vẫn vào qua Cloudflare ZT (cloudflared @1c), nhưng self-heal cần pull image sẽ nghẽn. Đánh
   đổi cost có chủ đích (NAT đa AZ tốn thêm ~$X/tháng); ghi nhận, xử lý riêng nếu nâng bar lên "chịu 1a như 1b/1c".
2. **VPC endpoint SSM (`ssm`/`ssmmessages`/`ec2messages`) chỉ ở private-1a** (hệ quả Directive #18 A1, tiết
   kiệm ~$26/tuần). Mất 1a → mất đường SSM bastion; đường vào còn Cloudflare ZT. Bedrock/AI **sống** nhờ VPC
   endpoint `sts`+`bedrock-runtime` trải **3 AZ**.
3. **Elastic pool (node stateless arm64) chỉ có node ở 1a + 1c, KHÔNG ở 1b (GAP 2).** Khả năng chịu AZ thực
   ở tầng compute stateless = **2 AZ**, dù cụm có node 3 AZ. Mất 1 trong 2 AZ elastic → HPA chỉ còn 1 AZ
   elastic để scale; nếu chật chỗ, pod Pending → capacity giảm ~50% trong lúc phục hồi. Đây là đánh đổi cost
   (Mandate #13 spot/Graviton). **CDO01 sở hữu elastic capacity**; đề xuất thêm node elastic ở 1b để lên 3-AZ —
   phối hợp, không tự sửa nodepool. Drill đo RTO thực **ở mức capacity hiện có**, không bơm tài nguyên cho đẹp.

## Ma trận mất AZ (để trả lời mentor)

| Mất | Luồng ra tiền | Ops / hạ tầng |
|---|---|---|
| **1a** | sống (mỗi svc còn replica @1c); store không đụng | 🔴 mất NAT/egress + SSM + bastion → vào bằng Cloudflare ZT; Bedrock sống (endpoint 3 AZ) |
| **1b** | không có workload money ở 1b → không đụng pod | ElastiCache primary→failover 1c (auto); RDS mất secondary (tự dựng lại) |
| **1c** ⭐ | frontend còn 1 replica @1a + HPA; các svc khác còn @1a | RDS primary→failover 1b (auto); ElastiCache mất replica; mất 1 broker; mất 1 otel-gateway |

**⇒ 1c là AZ nặng nhất → drill 1c trước.**

## Hệ quả

- Storefront công khai giữ nguyên, cổng vận hành vẫn riêng tư (Directive #1); **không đụng flagd** (Luật chơi).
- Trong ngân sách ~$300/tuần/TF: chi phí DR đến từ Multi-AZ store + node đa AZ (đã có), **không** dựng standby dư.
- Việc mở: (a) drill FIS 1c dưới tải → điền số RTO/RPO đo được; (b) cân nhắc drill 1b (kiểm ElastiCache
  failover) + trình bày phân tích 1a; (c) phối hợp CDO01 đóng GAP 2 (node elastic ở 1b) nếu muốn 3-AZ compute;
  (d) (dài hạn) NAT + SSM endpoint đa AZ nếu nâng bar chịu 1a ngang 1b/1c.

## Kết quả drill (31/07/2026, dưới tải ~2,7 checkout/s, FIS 1c)

Hai lần bắn FIS `disrupt-connectivity` vào private-1c, đo bằng vòng curl ngoài cluster (3 path độc lập)
+ `az-drill-measure.py`. Evidence thô: `docs/evidence/mandate-21/run1/`, `run2/`.

**Run 1 — chỉ FIS NACL (T0 01:54:05Z):**
- **Cart hồi ~52s** (503→200). ElastiCache **tự failover** primary 1c→1b; cart reconnect nhanh nhờ
  **REL-17-07** (KeepAlive 5s thay 180s) — trước bản vá là 70s+. ✅
- **RDS KHÔNG tự failover** dưới NACL partition → product-catalog/checkout (đọc/ghi RDS-1c) 5xx suốt fault.
- Stop-alarm ALB 5xx **tự abort** (~T+4ph) — phanh an toàn hoạt động đúng.

**Run 2 — FIS NACL + `reboot-db-instance --force-failover` (T0 02:07:16Z, trigger failover 02:08:17Z):**
- **RDS primary ĐỔI 1c→1b** — event "Multi-AZ failover completed" 02:09:13Z (~56s), verify
  `describe-db-instances`: primary `ap-southeast-1b`, secondary 1c. Đây là bằng chứng directive đòi.
- **RTO đo được (từ lúc fault ăn vào 02:07:32Z):** browse `/` **~37s**; `/api/cart` **~0** (EC primary
  đã ở 1b từ run1); `/api/products` + checkout (đường RDS) **~2–3 phút**, chặn bởi failover RDS (56s) +
  app reconnect. **Money path hồi hoàn toàn LÚC 1c VẪN đang blackhole** → chứng minh mọi phụ thuộc đã
  rời 1c (frontend@1a + ElastiCache@1b + RDS@1b).
- **RPO = 0**: RDS Multi-AZ replicate đồng bộ → không đơn đã commit nào mất qua failover.
- Sau fault: NACL trả nguyên trạng, 8/8 node Ready, money-path AZ-spread `0 single-AZ`, store `available`.

**Finding chốt (cập nhật cam kết RTO ở trên):**
- **ElastiCache tự failover** trên network partition ✅. **RDS Multi-AZ (instance) KHÔNG tự failover khi
  chỉ mất kết nối do NACL** — AWS health-check nội bộ không coi NACL của khách là AZ failure. **AZ chết
  thật (mất điện/hardware) thì AWS tự trigger failover**; còn network-partition-thuần cần **runbook trigger
  tay** (`reboot-db-instance --force-failover`). ⇒ RTO đường DB khi mất 1 AZ:
  **tự động ~2–3 phút** (AWS phát hiện + failover) cho AZ chết thật; **cần thao tác runbook** cho partition.
- Cam kết cuối: **RPO=0**; **RTO browse/cart ≤ 60s**, **RTO đường DB (checkout/products) ≤ 3 phút**
  (failover-bound). Khớp target thiết kế.
- **Cảnh báo vận hành**: stop-alarm ALB 5xx (ngưỡng 5/60s) **abort cả hai lần** trong cửa sổ RDS-failover —
  đúng thiết kế an toàn, nhưng khi drill có chủ đích cần nới ngưỡng/thời lượng để chạy trọn PT5M, hoặc
  trigger RDS failover **sớm** (ngay khi fault ăn vào) để rút cửa sổ 5xx.

Runbook cập nhật bước force-failover: [`mandate-21-az-failover-drill.md`](../runbooks/mandate-21-az-failover-drill.md).

**Quyết định posture cho ca RDS network-partition (đã cân nhắc, chọn có chủ đích):**
Chấp nhận ranh giới AWS — **RDS Multi-AZ instance chỉ tự failover khi AWS phát hiện AZ hỏng thật**. Với
network-partition thuần (RDS còn "healthy" dưới mắt AWS), **thao tác người theo runbook** trigger failover
(`reboot-db-instance --force-failover`), đo được trong RTO cam kết (~2–3 phút gồm cả thời gian phát hiện).
Không chọn watchdog tự-failover (rủi ro flap, độ phức tạp không tương xứng) hay migrate Aurora (việc lớn)
ở phạm vi mandate này. Đánh đổi minh bạch: **ca AZ chết thật đạt full tự động; ca partition thuần phụ
thuộc trực vận hành + runbook** — chấp nhận vì partition-thuần-mà-AWS-không-thấy là hiếm và đã có đường xử
đo được. Xem lại nếu nâng bar hoặc chuyển Aurora.
