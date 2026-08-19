# TF3 — Phase 3: TechX Corp Service Takeover

Đây là repo vận hành chung của **TF3** (AIO02, CDO01, CDO02) cho Phase 3 của chương trình.
File này được Claude Code tự động đọc ở đầu mỗi phiên làm việc trong thư mục này — mục đích
là để **không phải giải thích lại bối cảnh dự án từ đầu mỗi lần mở chat mới**. Giữ file này
cập nhật; nó có giá trị bằng đúng mức nó phản ánh đúng thực tế hiện tại.

> **Cập nhật gần nhất: 30/07/2026** — **Mandate #19 đóng hồ sơ ở 3/4 YC**: trần thật là
> **1000 user / 202,4 RPS** (~3× con số cũ đã bị loại), tuned3 đạt **442,3 RPS @2400u (+29%) trên cùng
> 9 node**, xuống mềm ở 3× trần giữ luồng tiền 99,95%. Trần cuối cùng **là hạ tầng chứ không phải phần
> mềm** — 4 node `t3.large` thiếu label nên vĩnh viễn không nhận pod hot-path. Kèm **postmortem 0017**
> (`product-catalog` về 0 replica, HPA không cứu được, 42 phút 500) và cảnh báo **`~/.kube/config`
> hardcode profile readonly**. Xem mục "Mandates".
>
> (29/07/2026: product-reviews Sprint 3 Release A (Tier-2 PostgreSQL fallback) đã deploy production,
> zero downtime; xem mục "AI trong sản phẩm". ⚠️ Mục "Truy cập cluster" đã sửa:
> **`AWS_PROFILE=techx-new` không còn tồn tại**.)
>
> (23/07/2026: Mandate #2 + #3 demo PASS; AI Bedrock live cho product-reviews;
> **Mandate #8 HOÀN TẤT + §8 XONG — 3/3 store lên managed, đã TẮT 3 component tự host (PR #324):
> Valkey→ElastiCache ✅, Postgres→RDS ✅, Kafka→MSK ✅**; Cloudflare Access thêm mail mentor; PM-101.
> **⚠️ Sự cố 20/07: batch NetworkPolicy Mandate #5 của CDO01 gây outage ~30ph — rollback, postmortem 0012.**)
>
> **🔴 NGÂN SÁCH ĐANG VƯỢT TRẦN (đo 21/07, `RECORD_TYPE=Usage`): $426/tuần / trần $300/TF.**
> Phân rã: CDO $306,5 (MSK $129,4) · AI $96,7 ($80,6 là 2 OCU OpenSearch Serverless mồ côi của AIO02)
> · ngoài Phase 3 $23,2 (stack `thermal-power-plant-*` Tokyo). Kế hoạch 5 việc về **$269,7/tuần** KHÔNG
> đụng Mandate #8 — xem [`docs/cost-breakdown-2026-07-22.md`](docs/cost-breakdown-2026-07-22.md).
>
> **⚠️ HỒ SƠ MANDATE #8 CHƯA COMMIT** (git status `??`): `docs/mandate-08-nghiem-thu.md` (báo cáo
> nghiệm thu, 769 dòng, 15 ảnh), `docs/evidence/mandate-08/`, `docs/cost-breakdown-2026-07-22.md`,
> `docs/docx_cdo02/mandate11-review-feedback.md`, 15 ảnh ở `docs/`, + ADR 0009 (modified). **Việc kế
> tiếp = gom vào 1 PR để nộp.** Trước khi sửa `nghiem-thu.md` phải xác nhận user đã đóng file (editor
> đè mất sửa đổi 1 lần rồi).

## Bối cảnh (không đổi trong suốt 3 tuần)

Phase 3 không phát brief. TF3 tiếp quản một storefront thương mại điện tử microservice
đang "sống" (TechX Corp), phải tự đánh giá, tự ưu tiên, vận hành dưới ràng buộc thật
(ngân sách, SLO, sự cố do BTC bơm vào), và bảo vệ mọi quyết định bằng ADR/postmortem ký tên.
Chi tiết đầy đủ: [`phase3 - information/RULES.md`](phase3%20-%20information/RULES.md).

**Đọc trước khi làm bất cứ việc gì kỹ thuật trong repo này:**
- [`phase3 - information/RULES.md`](phase3%20-%20information/RULES.md) — luật chơi, đặc biệt mục Luật chơi (điều khoản disqualify)
- [`phase3 - information/onboarding/ARCHITECTURE.md`](phase3%20-%20information/onboarding/ARCHITECTURE.md)
- [`phase3 - information/onboarding/SLO.md`](phase3%20-%20information/onboarding/SLO.md)
- [`phase3 - information/onboarding/BUDGET.md`](phase3%20-%20information/onboarding/BUDGET.md)
- [`phase3 - information/onboarding/INCIDENT_HISTORY.md`](phase3%20-%20information/onboarding/INCIDENT_HISTORY.md)

## Luật cấm tuyệt đối — disqualify nếu vi phạm

- **Không** gỡ, đổi hướng, hay refactor để service ngừng đọc flag từ `flagd` — đây là cách
  BTC bơm sự cố. Xử lý sự cố bằng fallback/retry/containment, không phải tắt cơ chế.
- **Không** đổi TOKEN/URI trong `values-flagd-sync.yaml` sang nguồn khác, không bỏ nó ra
  khỏi lệnh deploy (giờ đi qua GitOps/ArgoCD — xem dưới). `/flagservice` trong Envoy là kênh
  đọc flag runtime, **không được gỡ**; chỉ `/feature` (flagd-ui) là được gỡ (Mandate #1).
- flagd sync token/AWS creds/LLM API key/Cloudflare token: **không bao giờ** commit giá trị thật
  vào file tracked. Secret vào cluster qua ephemeral `kubectl create secret` hoặc external-secrets,
  không qua file. Xem [README.md](README.md).
- Filter `envoy.filters.http.fault` trong `frontend-proxy` (delay injection, `max_active_faults`)
  là hạ tầng BTC bơm sự cố — **không gỡ** khi tối ưu Envoy.

## Cấu trúc TF3

| Nhóm | Vai trò | Trụ |
|---|---|---|
| AIO02 | Tầng AI: AIOps + AIE (AI trong sản phẩm) | ngoài 4 trụ core |
| CDO01 | Platform/hạ tầng | **Performance Efficiency + Security** |
| CDO02 | Platform/hạ tầng | **Reliability + Cost Optimization** |

Auditability là trụ chung. Nếu người dùng nói "trụ của mình"/"team mình" → ngầm hiểu **CDO02**.

---

## Trạng thái hiện tại (16/07/2026)

### Hạ tầng & deploy — ĐÃ CHUYỂN SANG ACCOUNT MỚI + GITOPS
- **Account production giờ là `197826770971`** (không phải account BTC `012619468490` cũ — account
  cũ bị block, team chốt migrate). EKS `techx-corp-tf3`, `ap-southeast-1`, **version 1.35**. ECR
  `197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp`.
- **Deploy bằng GitOps/ArgoCD (App-of-Apps), KHÔNG còn `helm upgrade` tay.** Nguồn deploy thật giờ là
  **nhánh `main`** (đã cutover từ `deploy/account-migration-gitops` sang `main` ngày 15/07 — 7 ArgoCD app
  đều `targetRevision: main`, verify Synced/Healthy, zero downtime). `deploy/account-migration-gitops` giờ
  là **nhánh đóng băng làm rollback/audit** (giữ, không xoá, đã gỡ khỏi CI trigger). ArgoCD apps: `techx-corp` (chart chính), `techx-edge`,
  `techx-infrastructure-app` (`gitops/infrastructure/`), `karpenter`, `karpenter-nodepool`, `kyverno`,
  `kyverno-policies`, `external-secrets`, `flagd-secret-sync`, `argo-rollouts`. Auto-sync + selfHeal + prune.
- **Terraform** ở `infra/live/production/` (root duy nhất), state S3 `techx-tf3-197826770971-tfstate`,
  lock DynamoDB `techx-tf3-terraform-lock`. Module: `network`, `eks-platform`, `access` (SSM bastion),
  `edge` (CloudFront), `cloudflare-access` (REL-17). CI: `terraform-plan.yml` chạy trên push nhánh
  migration; `terraform-apply.yml` thủ công. **Luôn `terraform plan -out=tfplan` rồi `apply tfplan`**,
  không `apply -auto-approve`.
- **Edge**: CloudFront `https://d2tn71186d7ilz.cloudfront.net` (storefront public) → internal ALB
  (VPC Origin, `frontend-proxy-internal` ingress ở `gitops/edge/`) → `frontend-proxy` (Envoy).
- **Node**: managed node group thường (3 AZ) + **node group stateful riêng `stateful_1a`** (1 node,
  AZ 1a, taint `techx.io/workload=stateful`) cho postgres+valkey. Karpenter (`flash-sale-spot`) cho
  burst. metrics-server (EKS addon). Kyverno (baseline security context + require-resource-requests,
  đang audit).

### Truy cập cluster — 2 đường song song
- **⚠️ Profile `techx-new` KHÔNG CÒN TỒN TẠI** (xác minh 29/07 — `aws sts get-caller-identity` trả
  `The config profile (techx-new) could not be found`). Mục này trước đây bắt dùng nó; ai làm theo sẽ
  fail ngay lệnh đầu. Profile hiện có trong `~/.aws/`, **tất cả đều trỏ đúng account `197826770971`**:

  | Profile | Danh tính | Dùng khi |
  |---|---|---|
  | `default` / `nvtank-readonly` | role `tf3-production-readonly` | Mặc định. Đủ cho mọi thao tác đọc: node, pod, deploy, Application, ExternalSecret, log, describe. **Không** đọc được `secrets` |
  | `acc-moi` | user `cdo-admin-team` | Khi cần quyền ghi (apply, delete, đọc secret) |
  | `tf3-member-base` | user `tf3-members-readonly` | readonly, ít dùng |

  Preflight/verify nên chạy bằng `default` — tối thiểu quyền, và readonly không đọc được `secrets` là
  đúng thiết kế: verify trạng thái secret qua `ExternalSecret` (`READY=True`, `SecretSynced`) thay vì
  đọc giá trị.
- **SSM bastion** (mặc định): bastion ID **không cố định** (Terraform replace là đổi ID — 23/07 id cũ
  `i-02a8d3e39b87180ce` bị terminate, hiện là `i-0f5959afa0eb31e7c`; luôn tra động theo tag, xem lệnh
  dưới). Cluster endpoint `ADA05FFC84146C0AED730F78786EB320.gr7.ap-southeast-1.eks.amazonaws.com`. Mở tunnel:
  ```sh
  export AWS_PROFILE=acc-moi; export MSYS_NO_PATHCONV=1   # 'techx-new' đã chết, xem bảng trên
  # KHÔNG hardcode bastion ID — Terraform replace bastion là ID đổi (đã xảy ra 23/07: id cũ
  # i-02a8d3e39b87180ce bị terminate). Tra động theo tag + endpoint theo tên cluster:
  BASTION_ID=$(aws ec2 describe-instances --region ap-southeast-1 \
    --filters "Name=tag:Name,Values=techx-corp-tf3-bastion" "Name=instance-state-name,Values=running" \
    --query "Reservations[].Instances[].InstanceId" --output text)
  EKS_HOST=$(aws eks describe-cluster --name techx-corp-tf3 --region ap-southeast-1 \
    --query "cluster.endpoint" --output text | sed 's~^https://~~')
  aws ssm start-session --target "$BASTION_ID" --document-name AWS-StartPortForwardingSessionToRemoteHost \
    --parameters host="$EKS_HOST",portNumber="443",localPortNumber="8443" --region ap-southeast-1
  # terminal khác:
  kubectl config set-cluster arn:aws:eks:ap-southeast-1:197826770971:cluster/techx-corp-tf3 --server=https://localhost:8443 --insecure-skip-tls-verify=true
  ```
  EKS API private-only. **Tunnel hay tự đóng sau ~10-20 phút idle** — mở lại khi cần (chạy background).
- **Cloudflare Zero Trust (REL-17, phiên 14-15/07)**: domain `arthur-ngo.org` (cá nhân, tạm).
  `grafana.arthur-ngo.org` / `jaeger.arthur-ngo.org/jaeger/ui/` / `argocd.arthur-ngo.org` — vào thẳng
  UI qua SSO, **không cần kubectl/IAM**. `kubectl.arthur-ngo.org` cho kubectl (vẫn cần IAM). `cloudflared`
  Deployment chạy trong cluster. Xem [`docs/runbooks/cloudflare-zero-trust-access.md`](docs/runbooks/cloudflare-zero-trust-access.md).
- **Branch protection** giờ trên **`main`** (require PR + review + status check, chặn force-push/xoá).
  Làm nhánh + PR, base là **`main`**. CI (terraform-plan/apply, build-push-ecr) giờ nghe `main`.

### Mandates
- **Mandate #1 (network exposure)** — ✅ Đạt: route ops (`/grafana`,`/jaeger`,`/feature`,`/loadgen`) đã
  gỡ khỏi Envoy → CloudFront trả `403`; ops riêng tư qua SSM/Cloudflare; `/flagservice` giữ nguyên.
  ADR `docs/adr/0004-mandate-01-cdo01-envoy-least-exposure.md` (CDO01).
- **Mandate #2 (scale under budget / flash sale 200 user)** — ✅ **Đã chạy PASS (15/07)**: 200 user/17
  phút, checkout 99.98% / browse-cart 100% / p95 46-48ms, cost không phình (~$0.40/h, không thêm node).
  Co giãn ở tầng pod (frontend HPA 2→7→2). Báo cáo `docs/mandate-02-load-test-report.md`. **Post-cleanup
  đã làm** (PR #143): gỡ `karpenter.sh/do-not-disrupt` khỏi 7 component + `consolidateAfter` 3m→2m.
- **Mandate #3 (bảo trì không downtime)** — ✅ **Đã demo PASS (16/07)**: drain node app-tier
  `ip-10-0-43-83` giữa giờ, SLO giữ (checkout 99.94% / browse 100% / cart 99.95% / p95 68.6ms — đo
  Prometheus đúng cửa sổ drain). Cơ chế: topologySpread + `maxUnavailable:0` (PR #112), graceful
  shutdown preStop/grace (PR #114) + **checkout qua Argo Rollouts (PR #136)**, ALB graceful drain
  (PR #116), planned-failover datastore (PR #117). Báo cáo `docs/mandate-03-drain-node-report.md` (PR
  #152) + video. Runbook `docs/runbooks/mandate-03-drain-node-demo.md`. **Quan sát:** Grafana
  single-replica → blip 502 ~1 phút khi drain node chứa nó (monitoring plane, không phải sản phẩm);
  **cloudflared 2 replica đang chung 1 node** → cần anti-affinity (đề xuất). Service phụ trợ
  (ad/recommendation/llm/accounting/fraud/email/image-provider) **cố ý giữ 1 replica**.
- **Mandate #8 (migrate 3 datastore lên managed)** — 🟢🟢🟢 **HOÀN TẤT + §8 XONG (CDO02) — 3/3 store**.
  - **§8 (22/07, PR #324):** đã TẮT 3 component tự host (`postgresql`/`valkey-cart`/`kafka`, `enabled:false`)
    → ArgoCD prune → pod techx-tf3 45→38, cart+checkout 0 restart, MSK LAG=0, **không gián đoạn**. Trước
    đó gỡ mọi phụ thuộc (PR #307/#308: 3 initContainer `wait-for-kafka` + `wait-for-valkey-cart`, credential
    plaintext, receiver `kafkametrics`). **3 PVC (postgresql-data/kafka-data/valkey-cart) GIỮ CÓ CHỦ ĐÍCH** —
    cả 3 PV `reclaimPolicy:Delete`, xoá PVC là huỷ EBS vĩnh viễn; directive chỉ đòi "không còn POD" nên đã đạt.
    **Chỉ xoá 3 PVC + 3 EBS mồ côi (gp2, `available`) SAU khi mentor nghiệm thu.**
  - **Đường lui (Plan B) sau §8:** snapshot RDS `techx-tf3-postgres-pre-cleanup-20260721-2242` + ElastiCache
    `techx-tf3-valkey-pre-cleanup-20260721-2243` + PITR 7 ngày + MSK retention 168h + chart store cũ ở commit
    `6432e49`. Store cũ KHÔNG còn là đường lui thật (dữ liệu đã phân kỳ, rollback về = mất ~128k đơn).
  - **✅ Valkey → ElastiCache** (`master.techx-tf3-valkey.pkeslh.apse1.cache.amazonaws.com:6379`): cart
    đọc/ghi ElastiCache (TLS+auth). Cutover bằng dual-write + hội tụ TTL 60ph (827/827 giỏ khớp).
    Reverse dual-write đã GỠ (PR #307).
  - **✅ Postgres → RDS** (`techx-tf3-postgres.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com:5432`,
    Multi-AZ, managed master password): accounting (người ghi duy nhất) + product-catalog/product-reviews
    (đọc) đã trỏ RDS `sslmode=require`. Cutover bằng "đóng băng accounting → dump(root)+restore →
    parity khớp tuyệt đối → đổi conn → thả accounting replay backlog" (70478→70556 đơn, LAG=0, zero-loss).
  - **✅ Kafka → MSK** (`b-1/b-2/b-3.techxtf3kafka.4xa0zb.c6.kafka.ap-southeast-1.amazonaws.com:9096`,
    SASL/SCRAM-SHA-512 + TLS): **`kafka.m7g.large` × 3 broker** = **$558/tháng** (KHÔNG phải $130 như bản
    nháp — kiểm chứng 22/07 bằng `CreateCluster`: `t3.small` bị chặn bởi **KRaft mode** chứ không phải số
    version; `m7g.large` là instance rẻ nhất KRaft cho phép, $558 là giá sàn tuyệt đối — đừng điều tra lại).
    checkout (producer) + accounting/fraud-detection (consumer) đã trỏ MSK,
    LAG=0, zero-loss. Cutover: producer trước (PR #276, promote qua canary) → chờ Kafka cũ LAG=0 →
    consumer sau (PR #278, Earliest ăn sạch backlog). **Bug đã sửa (PR #269/#271):** checkout (Go/sarama)
    trước nhét cả CSV nhiều broker vào 1 phần tử `[]string{KAFKA_ADDR}` → "too many colons" (gây sự cố
    0010); nay `strings.Split` + fail-fast + stderr log. accounting(.NET/Confluent)/fraud(Java) nhận CSV
    bootstrap natively → không dính bug này.
  - Hạ tầng: module `infra/modules/datastores/` (RDS/ElastiCache/MSK + KMS + Secrets), bật bằng
    `enable_managed_datastores=true` trong tfvars. Secret qua ExternalSecret (`techx-tf3-postgres-conn`
    keys dotnet/go-dsn/libpq, `techx-tf3-valkey-auth`, `techx-tf3-kafka-scram`). SG datastore allow
    **NODE security group** (không phải cluster SG — pod egress qua node SG; đã fix). 3 store cũ
    (postgresql/valkey-cart/kafka) **VẪN CHẠY** làm đường lui, chỉ gỡ ở §8 sau nghiệm thu.
  - ADR `docs/adr/0009-mandate-08-managed-migration-cdo02.md`, runbook `docs/runbooks/mandate-08-managed-cutover.md`,
    tổng quan dễ hiểu `docs/mandate-08-tong-quan-va-qua-trinh.md`.
  - **⚠️ Bài học freeze dưới GitOps** (xem memory `freeze-replicas-under-argocd-gitops`): muốn
    `kubectl scale=0` GIỮ được cho 1 deployment, phải thêm nó vào `ignoreDifferences /spec/replicas`
    của Application `techx-corp` (`gitops/apps/techx-corp.yaml`) — không thì selfHeal + app-of-apps
    (`techx-corp-bootstrap`) revert. `replicas: 0` trong values KHÔNG dùng (template `default` coi 0 là rỗng).
- **Mandate #19 (biết trần & nâng trần bằng hiệu suất)** — 🟢🟢🟢🟡 **3/4 YC** (CDO01, đo 30/07).
  Báo cáo đầy đủ `docs/mandate-19-throughput-ceiling-report.md`, **bản tóm tắt có ảnh/video nhúng**
  `docs/mandate-19-nghiem-thu.md`, ADR `docs/adr/0011-mandate-19-throughput-ceiling-load-shedding.md`,
  evidence `docs/evidence/mandate-19/real-2026-07-30/`. PR #649/#651/#656/#658/#660/#664 (code+tuning),
  #662 (báo cáo+ADR), #671 (tóm tắt).
  - **Trần thật = 1000 user / 202,4 RPS** (~3× con số cũ 328u/174,75 RPS đã bị loại — bài đo cũ để node
    trôi 9→10→11 và dùng ngưỡng `checkout p99 ≤ 300ms` **không tồn tại trong `SLO.md`**). **Checkout gãy
    trước browse**, không phải ngược lại: 99,89% → 29,21% chỉ trong một nấc tải.
  - **⚠️ RPS tuyệt đối phải đọc từ CSV Locust, KHÔNG từ Prometheus/span metrics.** `otel-gateway`
    memory_limiter drop span dưới tải (`dropped_items=8645`) → throughput báo thấp giả. Tỉ lệ (%) đọc
    Prometheus vẫn đúng (tử/mẫu cùng co). Dùng `scripts/mandate-19/client_truth.py`.
  - **Ba nút thắt, hai không phải CPU:** (1) `email` nghẽn hàng đợi — client span 15000ms vs server span
    391ms; checkout gọi đồng bộ ở `src/checkout/main.go:473`; 82% tổng lỗi. (2) **gRPC ghim kết nối** —
    ClusterIP trả 1 VIP + `pick_first` mặc định ⇒ 11 replica mà chỉ 2 nhận tải (`353m·136m·11m·1m×8`).
    Sửa cần **CẢ HAI**: Service headless (`gitops/infrastructure/backend-headless-services.yaml`) **VÀ**
    `round_robin` trong `grpcChannel.ts`. (3) deadline 500ms quá nhạy (p95 thật 6,9ms) → 1200ms.
  - **YC#2 chưa qua**: tham số (minReplicas, HPA target 65%, deadline) vẫn hiệu chỉnh cho chế độ **cũ**;
    lỗi đến theo cụm ~8s **ngay trước** mỗi lần HPA scale-up ⇒ nợ hiệu chỉnh, không phải hết năng lực.
    Dù vậy tuned3 đạt **442,3 RPS @2400u (+29%)** trên **cùng 9 node**, checkout u1800 7,12%→99,18%.
  - **🔴 Trần cuối cùng là HẠ TẦNG, không phải phần mềm:** `values-mandate13.yaml` ghim 10 workload hot-path
    bằng `nodeSelector {techx.io/workload: elastic, techx.io/arch: arm64}`; **4 node `t3.large` không có
    label đó nên vĩnh viễn không nhận được pod hot-path** → 8 vCPU đã trả tiền nằm không trong khi node
    elastic chạy 99%. Tầng elastic arm64 có **trần cứng 4 node** (`flash-sale-spot-arm64` `limits.nodes:2`
    + `elastic-ondemand-fallback-arm64` `limits.nodes:2`) — CDO01 đặt cố ý để giữ chi phí.
    ⚠️ **Đừng đọc nhầm log Karpenter** (tôi đã nhầm một lần): `label "techx.io/arch" does not have known
    values` là lý do từ chối của pool **amd64**, KHÔNG phải pool arm64 — Karpenter in lý do của từng
    NodePool rồi gộp một khối. Hai pool arm64 **đã có** `techx.io/arch` ở `template.metadata.labels`
    (`spot-nodepool.yaml:88`, `ondemand-fallback-nodepool.yaml:92`) và Karpenter đưa static label đó vào
    requirements của node sẽ tạo, không cần lặp ở `requirements`. Lý do thật là `limits.nodes` đã cạn.
  - **YC#4 đạt tốt nhất:** 597 rps ≈ 3× trần qua CloudFront công khai, browse hy sinh 104k request
    (429), **cart+checkout 99,95%**. Envoy `browse_rate_limiter.rate_limited=19.539` vs
    `local_rate_limiter.rate_limited=0/148.919`. Demo 1 lệnh: `scripts/mandate-19/shed_demo.sh`.
    ⚠️ `local_ratelimit` là token bucket **mỗi replica** ⇒ ngân sách tổng = `tokens_per_fill × số replica`;
    nâng maxReplicas proxy 8→12 đã vô hiệu hoá shedding một lần (PR #649), phải hiệu chỉnh lại ở #658.
    ⚠️ Filter này **không** phát header `x-envoy-ratelimited` (chỉ global ratelimit mới có).
  - **⚠️ Khoảng trống quan sát đã phát hiện:** cAdvisor chết 7/8 node (`context deadline exceeded` port
    10250) ⇒ panel "Pod count" Grafana **vĩnh viễn `No data`** — không phải bằng chứng pod không scale.
    kube-state-metrics chưa cài. SLI checkout từng mù (8.875/8.877 đơn lỗi mà dashboard vẫn 100%) — fix ở #649.
  - **Postmortem 0017** (`docs/postmortem/0017-product-catalog-replicas-zero-hpa-cannot-recover.md`):
    `product-catalog` về 0 replica → `/api/products` 500 trong 42 phút. **HPA KHÔNG scale được từ 0**
    (coi 0 = "tắt autoscaling"), và chart bỏ hẳn field `replicas` khi `replicasManagedExternally: true`
    ⇒ **GitOps cũng không có đòn bẩy**. 10 service đang bật cờ này đều dính cùng lỗ hổng.
    **⚠️ `~/.kube/config` hardcode `AWS_PROFILE: nvtank-readonly` trong `exec.env`** — `export AWS_PROFILE=acc-moi`
    **KHÔNG thắng được**; thao tác ghi phải dùng:
    `kubectl ... --token="$(AWS_PROFILE=acc-moi aws eks get-token --cluster-name techx-corp-tf3 --region ap-southeast-1 --output json | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"]["token"])')"`

### AI trong sản phẩm (AIO02) — Bedrock đã LIVE
- **`product-reviews` giờ dùng AWS Bedrock thật** (không còn mock): `LLM_PROVIDER=bedrock`,
  `LLM_MODEL=amazon.nova-lite-v1:0`, judge/evaluator `amazon.nova-micro-v1:0`, `AWS_REGION=us-east-1`.
  IRSA `techx-corp-tf3-product-reviews-bedrock` (quyền Bedrock chỉ ở SA này, không cấp global). Bật qua
  `values-aio-llm.yaml` (đã có trong `gitops/apps/techx-corp.yaml`). Có guardrail: summary evaluator
  reject nội dung bịa, grounding "No information in reviews". Runbook `docs/runbooks/aio-bedrock-rollout.md`.
  (Việc AIO02, không phải CDO02.)
- **✅ Sprint 3 Release A — Tier-2 PostgreSQL fallback (deploy 29/07, digest `sha256:be5cd78a…`).**
  Khi Bedrock lỗi / circuit breaker OPEN / rate-limit / timeout, `AskProductAIAssistant` trả bản tóm tắt
  canonical đã duyệt gần nhất từ `reviews.product_summaries` (Tier-2) thay vì rơi thẳng xuống thông báo
  tĩnh (Tier-3). Rollout 45 giây, `readyReplicas` không tụt dưới 2, **45/45 request đo được trả 200**.
  - **Port CHỌN LỌC từ `feature/product-review`, KHÔNG merge nhánh.** Nhánh AIO thiếu 1.440 commit của
    `main` và commit `860c116` đã xoá phần lớn cây mã nguồn ngoài `product-reviews` — merge/copy nguyên
    nhánh sẽ mất readiness DB-aware (REL-02), semaphore PM-0016, fix pool REL-05 và Dockerfile hardened.
  - **Hai lỗi semantics của bản AIO đã vá khi port**, mỗi lỗi có test khoá + mutation-verified:
    (1) persist thêm gate `is_summary_request` — bản gốc để câu "có chống nước không?" ghi đè bản tóm tắt;
    (2) `resolve_fallback_summary` so `review_version`, lệch/NULL → Tier-3 (fail closed).
    Persist đi qua `db_write_executor`, không chặn đường request.
  - **⚠️ Mới kiểm chứng ĐƯỜNG GHI trên production.** Đường ĐỌC (fallback thật sự trả Tier-2) chưa test
    end-to-end vì phải bơm lỗi LLM thật (`llmRateLimitError` gây lỗi ~50% request). **Đừng báo cáo
    "Tier-2 hoạt động đầy đủ"** cho tới khi làm xong.
  - Schema qua ArgoCD Application riêng `product-reviews-schema-migration` (`gitops/jobs/product-reviews-sprint3/`),
    **không `kubectl apply` tay**. PR: #590 code · #591+#598 migration · #593 image bump.
    Evidence `docs/evidence/product-reviews-sprint3/`.
  - **Bài học values-prod vs values-mandate13**: `values-mandate13.yaml` là file #4, load **sau**
    `values-prod.yaml` (#3), và `tolerations` là **list** → Helm **THAY THẾ** cả list. Thêm toleration ở
    `values-prod.yaml` cho component đã có mặt trong `values-mandate13.yaml` là **no-op** (đã mất một PR
    vào đúng bẫy này — #594 rồi revert bằng #601).
  - **OPEN, không gộp vào kết luận Release A:** Release B/S6 isolation · thay đổi hành vi trả lời AI
    (2 deterministic router, prompt rewrite, ép output tiếng Anh — chờ eval set AIO-15) · Bedrock Guardrail ·
    CDO-06 (candidate Deployment) · CDO-11 (CI mới render 3/6 lớp values) · least privilege cho
    `product_summaries` + `fidelity_audit` (bảng do `otelu` sở hữu nên GRANT không thu hẹp được gì).

### Security / supply-chain (CDO01) — PM-101
- **Image supply-chain gate**: Trivy release gate (chặn image lỗ hổng **trước** push) + Cosign keyless
  signing (chứng minh digest đang chạy đến từ workflow TF3). ECR immutable + digest-pinned (PM-95).
  ADR `docs/adr/0008-pm-101-image-supply-chain-gate.md`. CI có auto-tag/digest cho imageOverride (PR #153/#158).
- **Network policy quan sát** đã vá: cho `cloudflared` vào Grafana/Jaeger UI ports (PR #155/#156).

### Rủi ro / việc còn mở
- **⚠️ 4 IAM user** (`arthur`, `CDO01`, `CDO02`, `AIO02`) + `mentor` đều `AdministratorAccess` — trái
  least-privilege. Chưa thu hẹp (trụ Security/CDO01).
- **🔑 Secret cần rotate sau bài tập**: flagd sync token (đã dùng trong `kubectl create secret`),
  **Cloudflare API token** (đã dùng nhiều phiên, file `~/Downloads/tokencloudflare.txt` cần xoá).
- **☁️ Cloudflare Access**: đã thêm 4 mail mentor (`nghia.huynh`/`toan.le`/`khanh.nguyen`/`namhong.ta`
  @techxcorp.com) + 2 gmail vào allowlist cả 4 app (kubectl/grafana/jaeger/argocd). **Cần bật One-Time
  PIN** ở Zero Trust → Settings → Authentication thì mail ngoài mới login được (đã bật tay).
- **Datastore không HA**: ~~postgres/valkey/kafka~~ — **CẢ 3 đã lên managed HA + §8 đã tắt store cũ
  (Mandate #8 XONG): ElastiCache Multi-AZ + RDS Multi-AZ + MSK 3-broker**. Hết SPOF datastore.
- **💰 Cost — 3 directive Cost/Reliability đang MỞ (16/17/18, đều quá hạn 21-22/07):** đo cluster 23/07:
  cụm 45% CPU request nhưng chỉ 6,7% dùng thật; ràng buộc t3.large là **RAM** (t3.large=t3.medium=2vCPU).
  Node `db-1a` (t3.medium on-demand, taint stateful) sau §8 **rỗng** (chỉ 4 DaemonSet) → gỡ = −$8,9/tuần
  + đóng rủi ro AZ 1a. Nodegroup `default` **4×t3.large min=4**; hạ 4→3 giữ 3-AZ (an toàn Mandate #17),
  hạ 4→2 PHÁ phủ 3 AZ (chỉ còn 2 AZ) → không nên. **VPC endpoint tốn $142/mo để né NAT chỉ $7/mo.**
  ⚠️ CDO01 đang chạy dở batch Karpenter elastic (PR #316→#330) — **đừng đụng nodegroup khi họ chưa xong**.
- **⚠️ 3 EBS mồ côi** (gp2, `available`): `vol-05d59d76…`(1G), `vol-0f4b0c53…`(2G), `vol-0a22f1049…`(3G)
  — là PVC store cũ sau §8. Xoá SAU nghiệm thu (Mandate #18 YC1 đòi "không EBS available").
- **⚠️ Network policy (Mandate #5 CDO01) — đã rollback sau sự cố 20/07**: batch 20 NetworkPolicy chặn egress
  ra managed datastore (dùng podSelector store cũ thay `ipBlock`) + lỗi podSelector-egress-ClusterIP trên
  VPC CNI → outage checkout+3 service ~30ph. Đã xoá cả batch (backup ở `docs/postmortem/artifacts/0012-...`).
  **CDO01 phải dựng lại đúng** (ipBlock RDS/ElastiCache/MSK, test trên VPC CNI, qua GitOps) trước khi apply
  lại — nếu apply nguyên trạng sẽ sập lại. Postmortem `docs/postmortem/0012-mandate5-networkpolicy-batch-outage.md`.

---

## Backlog CDO02 — trạng thái thật (verify 16/07 qua code + cluster)

Nguồn: [`docs/backlog/cdo02-reliability-cost-backlog.md`](docs/backlog/cdo02-reliability-cost-backlog.md).

**✅ ĐÃ LÀM + deployed:** REL-01 (replicas 2 + PDB), REL-02 (health dependency-aware cho
product-catalog/product-reviews/checkout qua gRPC readiness; service stateless giữ static SERVING là
đúng), REL-03 (probe toàn service), REL-04 (đảo ship-before-charge vì payment không có Refund RPC),
REL-05 (connection pool trong code — **KHÔNG dùng PgBouncer**, nhánh đó bị bỏ), REL-07 (CPU
requests/limits 0/53 thiếu), REL-09 (Kafka `WaitForAll` + accounting manual commit), REL-10 (PVC cho
cả postgres/valkey/kafka), REL-12 (quote throw khi thiếu field), REL-13 (Grafana OOM — mem 1Gi),
REL-16 (Kafka OOM — mem 1536Mi), REL-17 (Cloudflare access), **REL-11 (currency validate — fix PR #120,
trả `INVALID_ARGUMENT` cho code lạ), REL-12/REL-15 (PR #120)**. COST-01 (ECR lifecycle `tagPatternList`),
COST-02 (Karpenter thay cluster-autoscaler), COST-03 (Spot), COST-06 (ResourceQuota), COST-07 (NAT đơn).

**🟡 MỘT PHẦN / verify:** REL-06 (resource đã set, load test 200 user đã PASS — coi như đủ), REL-14 (đã có
`fix(rel-14) retry product-catalog DB init` — cần verify crash hết), COST-04 (right-size đang tiếp diễn),
COST-05 (load-gen OOM — config hardened, root cause chưa chốt).

**✅ ĐÃ LÀM:** REL-08 (datastore đơn lẻ) → **Mandate #8 migrate lên managed XONG 3/3**: Valkey→ElastiCache ✅ +
Postgres→RDS ✅ + Kafka→MSK ✅ (zero-loss, zero-downtime). ADR 0009, postmortem 0010 + 0012. Store cũ giữ tới §8.

---

## Phát hiện code — bản chất service (giữ để tham chiếu, đã cập nhật trạng thái fix)

- 3 service dùng chung 1 Postgres (`product-catalog`, `product-reviews`, `accounting`), 1 Valkey
  (`cart`), 1 Kafka broker (`checkout`→`accounting`/`fraud-detection`). **Mandate #8 XONG 3/3: Postgres→RDS ✅
  + Valkey→ElastiCache ✅ + Kafka→MSK ✅ (đã cutover cả 3).** Store cũ (có PVC, REL-10) vẫn giữ làm đường lui.
- `checkout` charge trước ship → **đã fix REL-04** (đảo thứ tự ship-before-charge).
- Health check giả → **đã fix REL-02** cho service có DB (còn currency/ad/payment stateless giữ static
  SERVING là đúng).
- `checkout` Kafka fire-and-forget + `accounting` auto-commit mất đơn → **đã fix REL-09**.
- `valkey-cart` không persistence → **đã fix** (PVC + AOF).
- `currency` không validate code → **đã fix REL-11** (PR #120, validate + `INVALID_ARGUMENT`).
- `quote` nuốt exception → **đã fix REL-12**.
- **`product-reviews` giờ dùng Bedrock thật** (nova-lite + judge nova-micro, IRSA riêng) — không còn
  đi qua mock `llm`. AIO02 rollout (PR #142, `values-aio-llm.yaml`). Service `llm` mock vẫn còn trong
  chart nhưng bị `LLM_PROVIDER=bedrock` bỏ qua. Xem mục "AI trong sản phẩm" ở trên.

---

## Quy ước làm việc

- **KHÔNG push thẳng `main`** — làm nhánh + PR, base là **`main`**. **Luôn branch từ `origin/main` sau khi
  `git fetch`** (branch từ local ref cũ đã 2 lần gây conflict). Branch protection chặn force-push.
- **Verify chart change bằng `helm template`** (đúng flags ArgoCD dùng) trước khi commit — schema
  `values.schema.json` là `additionalProperties:false`, thêm field mà quên update schema sẽ làm ArgoCD
  `ComparisonError` chết cả pipeline (đã xảy ra với `digest`).
- Đổi app-code cần **rebuild image** (CI `build-push-ecr.yml`, digest-pinned) rồi cập nhật
  `imageOverride` trong `values-prod.yaml`. `default.image.tag` **không** tự nối tên service cho
  `imageOverride.tag` (phải ghi FULL `<sha>-<service>`).
- ADR ký tên cho quyết định lớn (`docs/adr/`), postmortem sau sự cố (`docs/postmortem/`), runbook
  (`docs/runbooks/`). Đã có nhiều — đọc trước khi làm lại.
- Secret không bao giờ vào file tracked. Với thao tác hủy hoại/live (drain, delete pod datastore),
  xác nhận với user + làm trong giờ ít traffic.

## Hướng dẫn cho Claude Code ở các phiên sau

- Đọc file này trước, rồi mới đọc sâu `phase3 - information/` nếu cần.
- "Trụ của mình"/"team mình" = CDO02.
- Trước mọi thay đổi hạ tầng thật (GitOps/K8s/Terraform/CI), nhắc luật flagd/secret ở trên — vi phạm
  là disqualify cho cả TF.
- **Nguồn deploy thật = nhánh `main`, account `197826770971`** (đã cutover 15/07 từ nhánh migration).
  `deploy/account-migration-gitops` chỉ còn là rollback/audit đóng băng — không branch từ nó nữa.
- Cập nhật mục "Trạng thái hiện tại" + trạng thái backlog mỗi khi có tiến triển lớn — đừng để file lạc hậu.
