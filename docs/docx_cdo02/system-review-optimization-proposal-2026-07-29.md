# Rà soát toàn hệ thống — Đề xuất tối ưu ngoài phạm vi mandate

**Ngày:** 2026-07-29
**Người thực hiện:** CDO-02 (trụ Reliability + Cost Optimization)
**Bối cảnh:** Tuần cuối không có mandate mới cho nhóm CDO. Mentor yêu cầu hoàn tất mandate cũ, sau đó **rà soát lại toàn hệ thống xem còn tối ưu được gì ngoài những mandate đã giao**. Leader giao CDO-02 tìm hiểu.
**Phương pháp:** verify **read-only trên môi trường thật** (AWS API + `kubectl` qua SSM tunnel), đối chiếu ADR/postmortem sẵn có. Cluster `techx-corp-tf3`, account `197826770971`, region `ap-southeast-1`.

> **Nguyên tắc của bản này:** chỉ ghi những gì **đo được và thật sự cần**. Mục §4 liệt kê rõ các thứ **đã kiểm và KHÔNG phải vấn đề** — để nhóm không tốn công vào chỗ đã tối ưu sẵn, và để bản đề xuất không bị "vẽ việc".

---

## 0. Tóm tắt điều hành

Hệ thống đã khá lành mạnh sau 18 mandate: storage toàn gp3, không có tài nguyên mồ côi kiểu EBS/EIP, MSK đã ở mức rẻ nhất hợp lệ, khoản OpenSearch Serverless mồ côi $80.6/tuần **đã được dọn**.

Rà soát tìm được **2 vấn đề nghiêm trọng chưa mandate nào chạm tới** và **5 khoản lãng phí đo được**:

| # | Phát hiện | Loại | Mức |
|---|---|---|---|
| **R1** | **AZ 1a là điểm chết đơn của cả hệ mạng** — 1 NAT Gateway + toàn bộ SSM endpoint đều nằm ở 1a, không có ECR endpoint | Reliability | 🔴 **CAO** |
| **R2** | **OOMKill tái phát** trên ArgoCD controller (8 restart) và `accounting` — service ghi đơn hàng duy nhất | Reliability | 🔴 **CAO** |
| **C1** | **CPU request chỉ dùng 35%** — đặt chỗ 4.125m, dùng thật 1.431m → trả tiền cho node không cần | Cost | 🟠 |
| **C2** | Node chaos `ip-10-0-4-166` gần rỗng, on-demand, chạy từ 14/07 | Cost | 🟠 |
| **C3** | `load-generator` chạy 24/7, là pod ngốn CPU nhất cụm | Cost | 🟡 |
| **C4** | RDS diễn tập DR còn sống sau bài test hôm nay | Cost | 🟡 |
| **C5** | ECR phình ~1.100 image / ~44 GB; 2 ArgoCD app trôi cấu hình | Cost / Ops | 🟡 |

**Điểm mấu chốt:** R1 **phá vỡ chính mandate 17 req#2** mà nhóm vừa nghiệm thu — pod sống sót ở AZ khác, nhưng khách vẫn không vào được. Và **tiền tiết kiệm từ C1–C4 đủ để tài trợ cho việc sửa R1**, nên đề xuất này không làm ngân sách xấu đi (TF đang $426/tuần so với trần $300).

---

## 1. R1 — AZ 1a là điểm chết đơn của toàn hệ mạng 🔴

### 1.1. Bằng chứng (verify 2 lần, 29/07)

```
NAT Gateway:  nat-0b963ceaf95a7817f  →  subnet-0a56de94943c45499  (public, ap-southeast-1a)

Route table:  rtb-0f1d2c89309e1b398  (techx-corp-tf3-vpc-private)  →  NAT ở trên
   dùng chung cho CẢ 3 private subnet:
     subnet-0b43a804b2263cacb  →  ap-southeast-1a
     subnet-045de0d768b5c49f1  →  ap-southeast-1b
     subnet-0fdf5cd134c155b94  →  ap-southeast-1c

VPC Endpoint:
   s3               Gateway     ✅ (layer blob của ECR đi lối này)
   sts              Interface   ✅ 3 subnet
   bedrock-runtime  Interface   ✅ 3 subnet
   ssm              Interface   ⚠️ CHỈ subnet-0b43a804b2263cacb = AZ 1a
   ec2messages      Interface   ⚠️ CHỈ AZ 1a
   ssmmessages      Interface   ⚠️ CHỈ AZ 1a
   ecr.api          ❌ KHÔNG CÓ
   ecr.dkr          ❌ KHÔNG CÓ
```

### 1.2. Chuyện gì xảy ra khi mất AZ 1a

| Hệ quả | Cơ chế | Mức |
|---|---|---|
| **Khách không vào được storefront** | `cloudflared` phải mở kết nối **ra ngoài** tới Cloudflare edge. Pod nằm trên node ở private subnet (`associatePublicIPAddress: false`) → đi qua NAT ở 1a. NAT chết → tunnel đứt → **storefront mất truy cập dù pod ở 1b/1c vẫn khoẻ** | 🔴 |
| **Cluster không tự chữa được** | Pod mất ở 1a cần tạo lại ở 1b/1c → phải **pull image từ ECR** → khâu xác thực/manifest (`ecr.api`/`ecr.dkr`) không có endpoint → đi qua NAT → **không pod nào khởi động được ở bất kỳ AZ nào** | 🔴 |
| **Mất quyền vận hành đúng lúc sự cố** | Cả 3 endpoint SSM chỉ ở AZ 1a → đứt đường bastion → **team không `kubectl` vào cluster để xử lý** | 🟠 |

**Không bị ảnh hưởng** (nhờ endpoint đã trải 3 AZ): Bedrock (AI review) ✅, STS ✅, tải layer từ S3 ✅, RDS/MSK/ElastiCache (nội bộ VPC, đã đa AZ) ✅.

### 1.3. Vì sao đây là phát hiện đáng giá

Mandate 17 req#2 hỏi *"mất trọn một AZ mà luồng ra tiền vẫn giữ SLO"*. Nhóm đã chứng minh **ở tầng pod**: 10/10 service cốt lõi có 2 replica trải 2 AZ, PDB đủ, datastore đa AZ. Nhưng **không ai kiểm tầng mạng**. Kết quả: một `route table` vô hiệu hoá toàn bộ công multi-AZ đó — với đúng AZ 1a.

Đây là loại lỗ hổng chỉ lộ ra khi nhìn hệ thống **như một khối**, không lộ ra khi làm từng mandate.

### 1.4. Phương án (kèm chi phí thật, để leader/mentor chọn)

| Phương án | Nội dung | Chi phí ước tính | Gỡ được gì |
|---|---|---|---|
| **A. Endpoint ECR 3 AZ** | Thêm interface endpoint `ecr.api` + `ecr.dkr` ở cả 3 AZ | ~+$10/tuần, **nhưng giảm phí data-processing qua NAT** → gần như hoà | Cluster tự chữa được khi mất AZ |
| **B. Trải SSM endpoint ra 3 AZ** | Thêm subnet 1b/1c cho 3 endpoint SSM sẵn có | ~+$5/tuần | Giữ được đường vận hành khi sự cố |
| **C. NAT Gateway đa AZ** | Thêm NAT ở 1b + 1c, tách route table theo AZ | **~+$15/tuần** | Gỡ triệt để, gồm cả đường cloudflared |
| **D. Không làm, ghi nhận rủi ro** | Ghi vào sổ rủi ro + nói rõ khi demo | $0 | Không gỡ, nhưng **trung thực** |

**Khuyến nghị:** làm **A + B ngay** (rẻ, gần như hoà vốn, gỡ được 2 trong 3 hệ quả, có tiền lệ — mandate 18 đã thêm endpoint STS/Bedrock 3 AZ). Phương án **C nêu ra để leader/mentor quyết**, vì nó là đánh đổi tiền thật trong lúc đang vượt ngân sách — CDO-02 **không tự quyết**.

---

## 2. R2 — OOMKill tái phát trên thành phần trọng yếu 🔴

### 2.1. Bằng chứng (29/07)

| Thành phần | Limit / Request | Dùng thật | Restart | OOMKilled lúc |
|---|---|---|---|---|
| `argocd-application-controller-0` | 1Gi / **256Mi** | **624Mi** | **8** | 29/07 09:25 UTC |
| `accounting` | **350Mi** / 150Mi | 259Mi (74% limit) | 1 | 29/07 13:58 UTC |
| `grafana` | 1Gi / 512Mi | 426Mi | 1 | 28/07 14:56 UTC |

### 2.2. Vì sao nghiêm trọng

- **ArgoCD application-controller là bộ não GitOps.** Nó chết → **mọi sync dừng**: không deploy được, `selfHeal` không chạy, drift không được sửa. 8 lần restart nghĩa là **đang lặp lại**, không phải sự cố đơn lẻ. Request 256Mi trong khi dùng 624Mi còn khiến scheduler xếp pod này vào node không đủ chỗ thật.
- **`accounting` là service ghi đơn hàng DUY NHẤT** (theo ADR mandate 8). Nó OOM → dừng tiêu thụ Kafka → đơn hàng đọng lại. Và đây là **tái phát**: `postmortem 0001` chính là sự cố *accounting OOMKill*. Limit 350Mi với ứng dụng .NET tiêu thụ Kafka theo lô là quá sát (đang dùng 74%).

### 2.3. Đề xuất

| Thành phần | Hiện tại | Đề xuất | Lý do |
|---|---|---|---|
| `argocd-application-controller` | limit 1Gi, req 256Mi | limit **2Gi**, req **768Mi** | Đỉnh vượt 1Gi lúc sync; request phải bám mức dùng thật 624Mi |
| `accounting` | limit 350Mi, req 150Mi | limit **512Mi**, req **256Mi** | Đang 74% limit; là đường ghi dữ liệu tài chính, không được phép đứt |
| `grafana` | limit 1Gi | theo dõi thêm | Mới 1 lần, chưa đủ cơ sở đổi |

**Lưu ý nghịch lý cần nói rõ với mentor:** hệ **thừa CPU** (chỉ dùng 35% chỗ đã đặt) nhưng **thiếu RAM** ở vài chỗ trọng yếu. Nên hướng xử lý là **cắt CPU request thừa** và **nới memory limit ở nơi đang OOM** — không phải cắt đều hay tăng đều.

---

## 3. Nhóm lãng phí đo được

### 3.1. C1 — CPU request chỉ dùng 35% 🟠

```
Namespace techx-tf3:  request 4.125m CPU   |   dùng thật 1.431m   →  35%
Namespace kyverno:    request   610m CPU   |   dùng thật    43m   →   7%
```

Request là con số **scheduler dùng để quyết định cần bao nhiêu node** — đặt chỗ thừa nghĩa là trả tiền cho node không cần. Node thực tế chỉ chạy **1–37% CPU**.

| Workload | Request | Dùng thật | Thừa | Chủ |
|---|---|---|---|---|
| `shopping-copilot` ×2 | 250m mỗi pod | **2m** | ~496m | **AIO02** |
| `kyverno` (7 pod) | 610m | 43m | ~567m | CDO-01 |
| `opensearch-0` | 250m | 42m | 208m | chung |
| `aiops-engine` | 200m | **3m** | 197m | **AIO02** |
| `product-reviews` ×2 | 150m mỗi pod | ~28m | ~244m | CDO-02 |
| `flagd` / `grafana` / `prometheus` | 125–150m | 12–32m | ~340m | chung |

**Đề xuất:** cắt request về **mức dùng thật + biên an toàn** (không cắt limit), theo đợt nhỏ có đo trước/sau. Đủ để Karpenter gộp bớt **1 node on-demand t3.large** (~$17/tuần).
⚠️ `shopping-copilot` và `aiops-engine` là **của AIO02** — cần báo họ, **không tự sửa**.

### 3.2. C2 — Node chaos gần rỗng 🟠

`ip-10-0-4-166` — **t3.medium on-demand**, chạy từ **14/07**, chỉ có DaemonSet (`aws-node`, `kube-proxy`, `ebs-csi`, `otel-node-agent`) + `chaos-daemon`. **1% CPU, 29% RAM.**

Chính báo cáo mandate 13 đã ghi node ngoại lệ này *"cần cleanup sau khi xong cửa sổ test chaos"*. Nếu chaos-mesh vẫn cần chỗ chạy, nên cho nó ở chung node khác thay vì giữ một node riêng.
**Ước tính:** ~$7/tuần.

### 3.3. C3 — `load-generator` chạy 24/7 🟡

`LOCUST_AUTOSTART=true`, request 200m/1Gi, và **đang là pod ngốn CPU nhất cụm (338m)** — công cụ test tiêu tốn nhiều hơn mọi service thật.
**Đề xuất:** để `replicas: 0` (hoặc tắt autostart) ngoài cửa sổ đo, bật khi cần chạy bài. **Ước tính:** ~$5/tuần + giảm nhiễu số liệu SLO.

### 3.4. C4 — RDS diễn tập DR còn sống 🟡

`techx-tf3-postgres-drill-20260729-181943` — `db.t4g.micro`, Single-AZ, tạo **29/07 12:43 UTC** (bài diễn tập DR hôm nay), vẫn `available`.
**Đề xuất:** xác nhận với người chạy diễn tập (mandate 20/21) rồi xoá; hoặc đặt quy ước **tự xoá sau khi thu bằng chứng**. **Ước tính:** ~$4/tuần.

### 3.5. C5 — ECR phình + cấu hình trôi 🟡

- ECR repo `techx-corp`: **~1.100 image, ~44 GB**. Cũng chính là thứ gây `postmortem 0001` (lifecycle xoá nhầm tag đang dùng). Nên rà lại lifecycle policy **theo `tagPrefixList` từng service** thay vì gộp cả repo.
- **2 ArgoCD app `OutOfSync`** (đều `Healthy`): `kyverno` (11 CRD) và `flagd-secret-sync` (2 ExternalSecret: `postgres-connection`, `shopping-copilot-valkey-url`). Drift lâu ngày làm mất ý nghĩa "git là nguồn sự thật" — nên đóng cho sạch trước khi nghiệm thu cuối.

---

## 4. Đã kiểm — KHÔNG phải vấn đề (đừng tốn công)

Phần này quan trọng ngang phần trên: giữ cho đề xuất không bị "vẽ việc".

| Hạng mục | Kết luận |
|---|---|
| **MSK** (khoản đắt nhất, ~$558/tháng) | **Đã ở mức rẻ nhất hợp lệ.** `kafka.t3.small` bị AWS từ chối với MSK 3.9.x (`Unsupported InstanceType`), `m7g.large` là nhỏ nhất hợp lệ và đã là Graviton. 3 broker/RF=3 là **bắt buộc** cho `acks=all` của checkout. Disk chỉ dùng 1.8% nhưng 10 GB đã là mức tối thiểu. → **Không đụng.** |
| **Kyverno** (nghi là rác sau mandate 5) | **KHÔNG phải rác.** Đang chạy 2 `ClusterPolicy` còn hiệu lực: `verify-first-party-signatures` và `allow-approved-external-image-digests` — tức **xác thực chữ ký Cosign ở admission**, thứ native VAP **không làm được** (liên quan mandate 10). 3 pod admission đã trải **đủ 3 AZ**. → Chỉ cần **rightsize request** (§3.1), giữ nguyên chức năng. |
| **EBS** | 8 volume, **100% gp3** rồi, không còn gp2 để chuyển. **0 volume mồ côi**, **0 snapshot** tồn đọng. |
| **RDS chính** | Retention 7 ngày, gp3, autoscale tới 40 GB, Multi-AZ. Hợp lý. |
| **OpenSearch Serverless mồ côi $80.6/tuần** | **ĐÃ ĐƯỢC DỌN.** Cả 2 collection (`trr490g18kpnofbpupe3`, `qs4tp08mw4mnymmaypzf`) trả `NOT_FOUND`. |
| **PDB cho workload 1 replica** | **KHÔNG nên thêm.** `PDB minAvailable:1` trên deployment 1 replica sẽ **khoá cứng việc drain node** — đúng cảnh báo đã ghi trong repo. Cấu hình hiện tại là đúng. |
| **CloudWatch Logs / Elastic IP / Load Balancer** | Sạch. Chỉ 1 log group rác nhỏ của TF2 (`/aws/lambda/tf2-finops-ai-test`, 0 MB), không thuộc TF3. |
| **OpenSearch domain `techx-products-search`** (us-east-1) | `t3.small.search` ×1, 10 GB — **đang phục vụ** KB `techx-products-kb-v2` của shopping-copilot, **không phải rác**. Điểm đáng lưu ý là nó **khác region** với ứng dụng → có độ trễ + phí truyền liên vùng. Thuộc **AIO02** quyết định. |

---

## 5. Kế hoạch đề xuất cho tuần cuối

| Ưu tiên | Việc | Chủ | Ước tính tác động |
|---|---|---|---|
| **1** | Thêm VPC endpoint `ecr.api` + `ecr.dkr` (3 AZ) | CDO-02 + hạ tầng | Gỡ rủi ro "cluster không tự chữa"; chi phí ~hoà |
| **2** | Nới memory limit `argocd-application-controller` + `accounting` | CDO-02 | Dừng OOMKill tái phát trên GitOps + đường ghi đơn |
| **3** | Trải SSM endpoint ra 3 AZ | CDO-02 + hạ tầng | Giữ đường vận hành khi sự cố (~+$5/tuần) |
| **4** | Rightsize CPU request theo số đo (đợt nhỏ, có đo trước/sau) | CDO-02, **báo AIO02** phần của họ | Gộp bớt ~1 node (~$17/tuần) |
| **5** | Dọn node chaos, RDS drill, `load-generator` về 0 | CDO-02 + chủ chaos/DR | ~$16/tuần |
| **6** | Rà ECR lifecycle theo `tagPrefixList`; đóng 2 app OutOfSync | CDO-02 / CDO-01 | Giảm rủi ro lặp lại postmortem 0001 |
| **—** | **Quyết định NAT đa AZ** (~+$15/tuần) | **Leader + mentor** | Gỡ triệt để R1 (gồm đường cloudflared) |

**Cân đối ngân sách:** nhóm việc 4–5 tiết kiệm ước tính **~$33/tuần**; nhóm 1–3 tốn thêm **~$5–15/tuần**. → **Ròng vẫn giảm chi**, đồng thời gỡ được 2 rủi ro CAO. Nếu chọn cả phương án NAT đa AZ thì gần như hoà vốn mà đóng hẳn R1.

---

## 6. Phụ lục — lệnh tái lập (read-only)

```bash
export AWS_PROFILE=techx-new           # tunnel: scripts/kube-tunnel.sh

# R1 — SPOF mạng
aws ec2 describe-nat-gateways --region ap-southeast-1 --filter Name=state,Values=available
aws ec2 describe-route-tables --region ap-southeast-1 \
  --query 'RouteTables[?Tags[?Value==`techx-corp-tf3-vpc-private`]]'
aws ec2 describe-vpc-endpoints --region ap-southeast-1 \
  --query 'VpcEndpoints[].{Svc:ServiceName,Subnets:SubnetIds}'

# R2 — OOMKill
kubectl get pods -A -o json | jq -r '.items[] | select(
  .status.containerStatuses[]?.lastState.terminated.reason=="OOMKilled")
  | "\(.metadata.namespace)/\(.metadata.name)"'

# C1 — request vs usage
kubectl top pods -n techx-tf3
kubectl get pods -n techx-tf3 -o json    # so với .spec.containers[].resources.requests

# §4 — các mục đã loại trừ
aws ec2 describe-volumes --region ap-southeast-1 --query 'Volumes[].VolumeType'
aws opensearchserverless batch-get-collection --region us-east-1 \
  --ids trr490g18kpnofbpupe3 qs4tp08mw4mnymmaypzf
kubectl get clusterpolicies.kyverno.io
```

> Số liệu node/pod trong bản này chụp ngày **29/07**; vị trí pod trôi theo mỗi rollout/consolidation — **verify lại trước khi trình bày**.
