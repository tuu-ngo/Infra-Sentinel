# MANDATE 21 / PM-163
# Tối ưu tốc độ phục hồi tầng ứng dụng khi mất Availability Zone

## Technical Specification, Failure Model, Execution Plan, Test Matrix, RTO Measurement và Evidence Contract

**Repository triển khai:** `tuu-ngo/Phase3-TF3-Infra-Sentinel`  
**Jira:** PM-163  
**Parent:** PM-159 — `[MANDATE 21] DR Failover — mất 1 AZ, khách không hay biết`  
**Task owner:** Lê Hoàng Việt  
**Mandate deadline:** hết ngày 31/07/2026  
**Namespace sản phẩm:** `techx-tf3`  
**Cluster:** `techx-corp-tf3`  
**Region:** `ap-southeast-1`  
**Baseline source:** phải ghi lại từ latest `main` tại thời điểm bắt đầu  
**Trạng thái tài liệu:** đặc tả triển khai; không phải bằng chứng production đã hoàn thành  
**Review bar:** Claude Opus / Fable / mentor phải có thể kiểm tra từng kết luận bằng source, command và raw evidence

---

# 0. Kết luận điều tra hiện trạng

## 0.1. Những gì project đã có

Project đã có phần lớn nền tảng từ Mandate 3 và Mandate 2:

1. Các service luồng ra tiền chủ yếu có ít nhất hai replica.
2. Production values đã khai báo `topologySpreadConstraints` theo:
   - `kubernetes.io/hostname`;
   - `topology.kubernetes.io/zone`.
3. Zone spread hiện dùng `DoNotSchedule` cho nhiều service hot path.
4. Rolling strategy chủ yếu dùng:
   - `maxUnavailable: 0`;
   - `maxSurge: 1`.
5. Các service hot path đã có:
   - readiness probe;
   - liveness probe;
   - `terminationGracePeriodSeconds: 30`;
   - `preStop` sleep khoảng 5 giây.
6. Checkout được quản lý bởi Argo Rollouts qua `workloadRef`.
7. HPA hiện có cho:
   - `frontend-proxy`;
   - `frontend`;
   - `product-catalog`;
   - `cart`;
   - `checkout-rollout`;
   - `currency`;
   - một số service ngoài money path.
8. HPA hiện dùng:
   - `minReplicas: 2` cho hot path;
   - CPU target khoảng 65%;
   - scale-up stabilization bằng 0;
   - scale-down stabilization khoảng 120 giây.
9. PDB hiện đã tồn tại cho:
   - `frontend-proxy`;
   - `frontend`;
   - `product-catalog`;
   - `cart`;
   - `checkout`;
   - `payment`;
   - `currency`;
   - `shipping`;
   - `quote`;
   - `product-reviews`.
10. Karpenter Spot NodePool có khả năng cấp thêm node khi Pod Pending.
11. Mandate 3 đã có evidence cho planned rollout/drain và graceful termination.

## 0.2. Những gap chính của PM-163

### Gap A — planned drain không chứng minh sudden AZ loss

`cordon + drain`:

- gửi eviction có kiểm soát;
- tôn trọng PDB;
- có thể chạy `preStop`;
- có thể nhận `SIGTERM`;
- cho scheduler thời gian phản ứng;
- không mô phỏng đầy đủ node biến mất giữa request.

Mandate 21 yêu cầu tình huống khó hơn:

- node mất kết nối không báo trước;
- request đang xử lý có thể đứt;
- `preStop` có thể không chạy;
- endpoint trên node chết phải bị loại;
- Pod thay thế phải được tạo ở AZ còn sống;
- capacity phải đủ trong thời gian HPA/Karpenter phản ứng.

Vì vậy task phải tách:

1. **Rehearsal:** cordon + drain toàn bộ node trong một AZ.
2. **Acceptance:** CDO02/mentor gây loss đột ngột, không graceful, và giữ AZ đó unavailable đủ lâu để đo.

Không được dùng rehearsal để tuyên bố đã PASS sudden failover.

### Gap B — probe không phát hiện AZ chết

Readiness/liveness probe chỉ chạy khi:

- kubelet còn hoạt động;
- node còn liên lạc;
- container còn tồn tại.

Khi AZ hoặc node mất hoàn toàn:

- probe không phải cơ chế phát hiện chính;
- node heartbeat, Node lifecycle controller, EndpointSlice và workload controller mới quyết định thời điểm endpoint/pod được xử lý.

Probe vẫn quan trọng cho:

- xác nhận Pod mới đã thực sự sẵn sàng;
- loại Pod còn sống nhưng ứng dụng bị lỗi;
- tránh gửi traffic vào process chưa phục vụ;
- tránh liveness quá nhạy gây restart storm trong lúc hệ đang phục hồi.

Task không được tuyên bố “giảm probe period sẽ làm Kubernetes phát hiện AZ chết nhanh hơn”.

### Gap C — HPA không reschedule Pod bị mất

HPA:

- không chịu trách nhiệm thay Pod bị mất;
- không trực tiếp gỡ endpoint;
- không tạo replacement cho replica đã mất.

Deployment/Rollout controller và scheduler duy trì replica count. HPA chỉ tăng desired replicas khi metrics cho thấy surviving pods bị quá tải.

Vì vậy phải đo riêng:

1. thời gian controller tạo replacement;
2. thời gian scheduler tìm capacity;
3. thời gian Karpenter tạo node nếu cần;
4. thời gian container start và readiness pass;
5. thời gian HPA tăng thêm capacity nếu surviving replicas bị tải cao.

### Gap D — HPA coverage chưa khép kín luồng thật

`gitops/infrastructure/hpa-hotpath.yaml` hiện chưa có HPA rõ ràng cho:

- `payment`;
- `shipping`;
- `quote`.

Jira nêu `payment` và `shipping`. Luồng checkout còn phụ thuộc `quote`, nên test scope phải bao gồm `quote` dù config-change scope ban đầu không ghi tên.

Không mặc định phải thêm HPA cho cả ba. Phải đo:

- CPU correlation với throughput;
- saturation point;
- surviving-capacity sau mất một AZ;
- startup time;
- bottleneck thực.

Nếu không có bằng chứng, thêm HPA chỉ là thay đổi cảm tính.

### Gap E — `minReplicas: 2` chưa chứng minh đủ capacity sau mất AZ

Hai replica spread qua hai AZ có thể tránh complete outage, nhưng khi mất một AZ:

- một replica có thể phải gánh toàn bộ traffic;
- capacity giảm 50%;
- HPA cần thời gian để đọc metrics và scale;
- Pod mới có thể Pending nếu node còn sống không đủ chỗ;
- Karpenter có thời gian provision node.

Do đó phải chứng minh một trong các chiến lược:

1. surviving baseline capacity đủ giữ SLO cho đến khi scale-up hoàn tất;
2. pre-warm/minReplica cao hơn cho service bottleneck;
3. node headroom đủ cho replacement Pod ngay lập tức;
4. kết hợp các biện pháp trên theo số liệu.

Không được “nhân đôi bừa cho chắc”.

### Gap F — Karpenter có giới hạn tổng capacity

NodePool hiện có giới hạn tổng khoảng:

```yaml
limits:
  cpu: "12"
  memory: 48Gi
```

Trong test mất AZ, phải xác minh:

- capacity đã sử dụng trước fault;
- capacity còn lại trong NodePool;
- EC2 quota;
- Spot capacity;
- subnet/IP capacity;
- node bootstrap time;
- Pod topology không khiến NodeClaim chọn AZ đã bị loại.

Nếu NodePool đã sát trần, HPA tăng desired replicas nhưng Pod vẫn Pending.

### Gap G — PDB không bảo vệ khỏi involuntary disruption

PDB:

- hữu ích khi drain có kế hoạch;
- không ngăn node/AZ chết;
- không tạo thêm capacity;
- không đảm bảo zero error khi request đang chạy;
- có thể làm rehearsal drain bị block nếu replica không đủ.

PDB phải được kiểm, nhưng không được dùng như bằng chứng duy nhất của AZ resilience.

---

# 1. Mục tiêu

Sau khi hoàn thành PM-163:

1. Mọi service bắt buộc trong money path có probe semantics được xác minh.
2. Probe phát hiện application failure đủ nhanh mà không tạo false restart.
3. Pod mới không nhận traffic trước khi thật sự ready.
4. Graceful shutdown từ Mandate 3 vẫn đúng cho planned termination.
5. Tài liệu ghi rõ graceful shutdown không được kỳ vọng khi AZ mất đột ngột.
6. HPA policy được đo và, nếu cần, chỉnh theo bằng chứng.
7. Capacity ở AZ còn sống đủ để duy trì hoặc nhanh chóng phục hồi SLO.
8. Replacement Pod không bị kẹt bởi topology, quota, thiếu IP hoặc thiếu node.
9. Rehearsal mất một AZ được chạy an toàn.
10. Sudden-AZ acceptance drill được phối hợp với CDO02/mentor.
11. Application recovery timeline được ghi bằng timestamp có thể đối chiếu.
12. Đóng góp app-layer vào RTO tổng được định lượng.
13. Browse → cart → checkout phục hồi trong RTO đã cam kết.
14. Không có order đã acknowledged bị mất.
15. Không có duplicate order ngoài behavior đã được chấp nhận.
16. Có evidence đủ để mentor chạy lại mà không dựa vào lời kể.

---

# 2. Phạm vi

## 2.1. Config scope chính

Bảy service Jira nêu:

```text
frontend
checkout
cart
product-catalog
payment
currency
shipping
```

## 2.2. Test scope bắt buộc theo dependency closure

Ngoài bảy service trên, test phải quan sát:

```text
frontend-proxy
quote
```

Lý do:

- `frontend-proxy` nằm trước storefront/application path.
- `quote` là dependency của shipping/checkout path.
- Một test bỏ qua dependency transitively required có thể PASS giả.

Các dependency data-plane cần phối hợp CDO02:

```text
RDS/PostgreSQL
ElastiCache/Valkey
MSK/Kafka
internal ALB / service networking
EKS node groups / Karpenter
```

## 2.3. In scope

- Audit probes hiện tại.
- Kiểm tra endpoint/protocol health thật của từng service.
- Điều chỉnh readiness/liveness/startup probes khi có bằng chứng.
- Xác minh lifecycle/preStop/grace period.
- Audit HPA coverage và behavior.
- Thêm hoặc chỉnh HPA khi benchmark chứng minh cần.
- Audit PDB selectors và health.
- Audit topology spread sau render.
- Kiểm tra node/AZ distribution.
- Kiểm tra surviving capacity/headroom.
- Kiểm tra Karpenter reaction và NodePool limits.
- Rehearsal planned AZ evacuation.
- Coordinated sudden-AZ drill.
- RTO timeline capture.
- Order reconciliation.
- Evidence và runbook.

## 2.4. Out of scope

- Thay đổi RDS/MSK/ElastiCache failover architecture.
- Backup/restore implementation của Mandate 20.
- Thay đổi business logic không liên quan đến recovery.
- Mở public operational endpoint.
- Vô hiệu hóa flagd.
- Thay HPA bằng hệ autoscaler mới.
- Thay CNI.
- Tự ý sửa control-plane controller flags.
- Tự ý thay subnet route/NACL để mô phỏng AZ.
- Tự ý terminate production node không có approved drill window.
- Tuyên bố toàn Mandate 21 hoàn tất chỉ bằng PM-163.
- Dùng planned drain làm bằng chứng final cho sudden AZ failure.

---

# 3. Invariant bắt buộc

## 3.1. Source-of-truth invariant

Mọi thay đổi production phải đi qua:

```text
Git
→ review
→ merge
→ Argo CD reconciliation
```

Không dùng imperative mutation làm implementation:

```bash
kubectl edit
kubectl patch
kubectl scale
```

Các lệnh imperative chỉ được phép trong drill/fault injection/runbook đã duyệt, và phải được ghi log.

## 3.2. RTO invariant

Không được đặt RTO tùy ý trong code review.

Trước final drill phải có ADR ghi:

```text
RTO_total_committed
RTO_application_budget
RTO_data_store_budget
RTO_network_budget
RPO_committed
```

PM-163 chịu trách nhiệm đo:

```text
fault-to-application-recovery
SLO-dip-to-SLO-recovery
endpoint-evacuation latency
replacement-ready latency
HPA reaction latency
Karpenter/node-ready latency
```

## 3.3. RPO/order invariant

`0 mất dữ liệu` phải được chứng minh bằng ID, không bằng cảm giác từ dashboard.

Phải đối chiếu:

```text
checkout attempts
HTTP/gRPC acknowledged successes
order IDs persisted
duplicate order IDs
missing acknowledged order IDs
```

Không coi request client timeout là order mất cho tới khi reconcile datastore.

Không coi response 200 là đủ nếu order không tồn tại trong source of truth.

## 3.4. Any-AZ invariant

Thiết kế phải chịu được mentor chọn bất kỳ AZ nào đang chứa workload.

Không được:

- chỉ test AZ có ít Pod nhất;
- pre-move Pod khỏi AZ trước final drill;
- pre-scale riêng ngay trước mentor test mà production bình thường không có;
- chọn thời điểm không tải;
- thay đổi fault target sau khi thấy AZ khó.

## 3.5. Automatic-recovery invariant

Trong acceptance drill:

- replacement Pod do controller/scheduler tạo;
- node replacement do autoscaling infrastructure tạo nếu cần;
- traffic tự chuyển;
- không manual scale từng service;
- không manual delete Pod để “giúp” controller;
- không manual edit endpoint;
- không manual restart deployment.

Human actions chỉ được phép nếu ADR ghi rõ và vẫn nằm trong RTO, nhưng PM-163 mục tiêu là app recovery tự động.

## 3.6. Availability invariant

Trong rollout config trước drill:

- Argo apps Synced/Healthy;
- all required Pods Ready;
- no active production incident;
- no unresolved PolicyReport block;
- storefront public;
- operations private;
- flagd unchanged;
- telemetry available;
- load generator can reconcile orders.

## 3.7. Probe invariant

- Readiness quyết định traffic eligibility.
- Liveness không kiểm dependency ngoài process nếu việc đó gây restart cascade.
- Startup probe được dùng nếu startup hợp lệ có thể vượt liveness window.
- TCP probe chỉ được chấp nhận khi port-open thực sự tương đương serving-ready, hoặc có ADR ghi hạn chế.
- Không giảm probe timeout/period chỉ để có con số RTO đẹp.
- Tuning phải có before/after false-positive evidence.

## 3.8. Graceful-shutdown invariant

`preStop` và termination grace phải:

- không giảm so với Mandate 3 nếu chưa có benchmark;
- không được mô tả là cơ chế bảo vệ khi AZ mất hoàn toàn;
- được test riêng trong planned drain;
- không làm Pod termination kéo dài vô hạn.

## 3.9. Capacity invariant

Sau khi mất AZ:

- surviving nodes còn đủ schedulable capacity, hoặc
- Karpenter tạo node mới trong remaining AZ trước khi hết app RTO budget.

Không được tính capacity từ requested replica count mà không xét:

- CPU/memory requests;
- DaemonSet overhead;
- max pods/IP;
- topology constraints;
- taints;
- architecture;
- Spot availability;
- NodePool limits;
- namespace quota.

---

# 4. Failure model

## 4.1. Planned disruption

Ví dụ:

```text
kubectl cordon
kubectl drain
rolling restart
managed node upgrade
```

Đặc điểm:

- API server biết trước.
- Eviction được tạo.
- PDB được áp dụng.
- Pod có thể nhận SIGTERM.
- preStop có thể chạy.
- scheduler có thể tạo replacement có trật tự.

Dùng để kiểm:

- graceful shutdown;
- PDB;
- rollout behavior;
- scheduler replacement;
- topology constraints.

Không đủ để chứng minh sudden AZ loss.

## 4.2. Sudden node/AZ loss

Đặc điểm:

- node mất heartbeat;
- process có thể biến mất không SIGTERM;
- request in-flight có thể đứt;
- endpoint removal phụ thuộc control plane;
- old Pod object có thể tồn tại ở Unknown/Terminating một khoảng;
- replacement scheduling phụ thuộc controller và capacity;
- managed stores có thể failover song song.

Dùng cho final Mandate 21 acceptance.

## 4.3. Required final fault semantics

Final test chỉ hợp lệ khi:

1. Mentor/CDO02 chọn AZ.
2. Toàn bộ application worker capacity trong AZ đó bị mất đột ngột.
3. Không chạy graceful drain trước.
4. Không cho scheduler/Karpenter tạo replacement trong failed AZ trong observation window.
5. Sustained load đang chạy trước fault.
6. Fault time được ghi bằng UTC timestamp.
7. Drill tiếp tục cho đến khi:
   - SLO recovered và ổn định;
   - hoặc stop condition buộc rollback.

Phương pháp làm AZ unavailable thuộc CDO02. PM-163 không tự thay route/NACL.

---

# 5. RTO decomposition

## 5.1. Timeline chuẩn

Ghi các timestamp sau:

```text
T-300s  load stable bắt đầu
T0      fault injection bắt đầu
T1      first node becomes unreachable / instance terminates
T2      first user-visible SLO breach
T3      endpoints from failed AZ removed
T4      replacement Pod objects created
T5      first replacement Pod Pending
T6      Karpenter NodeClaim created, nếu cần
T7      replacement node Ready, nếu cần
T8      replacement Pod Scheduled
T9      container image available / container Started
T10     readiness probe succeeds
T11     replacement endpoint Ready
T12     HPA desiredReplicas increases, nếu cần
T13     HPA requested replicas become Ready
T14     browse/cart/checkout return to SLO
T15     SLO remains healthy for acceptance window
T16     order reconciliation completes
```

## 5.2. Metrics derived

```text
fault_to_slo_dip       = T2 - T0
endpoint_evacuation    = T3 - T0
replacement_creation   = T4 - T0
pending_to_nodeclaim   = T6 - T5
node_provisioning      = T7 - T6
pod_startup            = T10 - T8
endpoint_publication   = T11 - T10
hpa_reaction           = T12 - T0
hpa_capacity_ready     = T13 - T12
application_rto        = T14 - T2
fault_to_recovery      = T14 - T0
stability_confirmation = T15 - T14
```

Official RTO reporting must include:

```text
RTO = SLO-dip-to-SLO-recovery
```

Báo cáo kỹ thuật cũng phải giữ `fault_to_recovery`, vì hệ có thể chưa rớt SLO ngay.

## 5.3. Acceptance window

SLO chỉ được coi là recovered khi:

- không phải một sample đơn lẻ;
- đạt threshold liên tục trong window đã định;
- không có pending/restart wave thứ hai;
- order reconciliation không phát hiện mất/duplicate bất thường.

Recommended evidence window:

```text
ít nhất 5 phút stable trước fault
fault xảy ra không báo trước
ít nhất 10 phút sau recovery
```

Con số cuối phải khớp ADR và load-test budget.

---

# 6. Baseline inventory bắt buộc

## 6.1. Git baseline

```bash
git switch main
git pull --ff-only
git status --short
git rev-parse HEAD
git log -1 --format='%H %cI %s'
```

Stop khi working tree dirty hoặc branch stale.

Output:

```text
docs/evidence/mandate-21/application-recovery/baseline/main-sha.txt
```

## 6.2. Cluster identity

```bash
aws sts get-caller-identity
aws eks describe-cluster \
  --name techx-corp-tf3 \
  --region ap-southeast-1
kubectl config current-context
kubectl cluster-info
```

Không commit credential, token hoặc kubeconfig.

## 6.3. Node/AZ inventory

```bash
kubectl get nodes \
  -L topology.kubernetes.io/zone,kubernetes.io/hostname,node.kubernetes.io/instance-type,karpenter.sh/capacity-type \
  -o wide

kubectl get nodes -o json \
  | jq '[
      .items[] |
      {
        name: .metadata.name,
        zone: .metadata.labels["topology.kubernetes.io/zone"],
        instanceType: .metadata.labels["node.kubernetes.io/instance-type"],
        capacityType: .metadata.labels["karpenter.sh/capacity-type"],
        unschedulable: (.spec.unschedulable // false),
        ready: (
          [.status.conditions[] |
           select(.type=="Ready") |
           .status][0]
        ),
        allocatable: .status.allocatable
      }
    ]'
```

Gate:

- ít nhất hai AZ usable;
- target design ideally ba AZ;
- không AZ nào là sole location cho critical service;
- operator access không phụ thuộc duy nhất AZ sắp test.

## 6.4. Pod/AZ distribution

```bash
kubectl -n techx-tf3 get pod -o json \
  | jq '[
      .items[] |
      {
        pod: .metadata.name,
        app: .metadata.labels["opentelemetry.io/name"],
        node: .spec.nodeName,
        ready: (
          [.status.conditions[] |
           select(.type=="Ready") |
           .status][0]
        )
      }
    ]'
```

Join với node zone trong script evidence.

Required output:

```json
{
  "frontend": {"az-a": 1, "az-b": 1, "az-c": 0},
  "checkout": {"az-a": 0, "az-b": 1, "az-c": 1}
}
```

Fail khi critical service có toàn bộ Ready Pod trong một AZ.

## 6.5. HPA baseline

```bash
kubectl -n techx-tf3 get hpa -o yaml
kubectl -n techx-tf3 describe hpa
kubectl get --raw /apis/metrics.k8s.io/v1beta1/namespaces/techx-tf3/pods \
  > /tmp/metrics-pods.json
```

Capture:

- currentReplicas;
- desiredReplicas;
- currentMetrics;
- conditions:
  - AbleToScale;
  - ScalingActive;
  - ScalingLimited;
- lastScaleTime;
- min/max;
- behavior;
- target kind.

## 6.6. PDB baseline

```bash
kubectl -n techx-tf3 get pdb -o wide
kubectl -n techx-tf3 get pdb -o json \
  | jq '[
      .items[] |
      {
        name: .metadata.name,
        disruptionsAllowed: .status.disruptionsAllowed,
        currentHealthy: .status.currentHealthy,
        desiredHealthy: .status.desiredHealthy,
        expectedPods: .status.expectedPods,
        selector: .spec.selector
      }
    ]'
```

Fail rehearsal khi required PDB:

- selector không match;
- `expectedPods` khác replica thực bất thường;
- `currentHealthy < desiredHealthy` trước drill.

## 6.7. Probe/lifecycle render baseline

Không audit trực tiếp values alone. Render đúng production source mà Argo dùng.

```bash
helm dependency build "phase3 - information/techx-corp-chart"

helm template techx-corp \
  "phase3 - information/techx-corp-chart" \
  --namespace techx-tf3 \
  -f "phase3 - information/techx-corp-chart/values.yaml" \
  -f "phase3 - information/deploy/values-flagd-sync.yaml" \
  -f "phase3 - information/deploy/values-prod.yaml" \
  <ALL_OTHER_VALUES_USED_BY_ARGO> \
  > /tmp/mandate21-rendered.yaml
```

`<ALL_OTHER_VALUES_USED_BY_ARGO>` phải lấy từ Application spec thực, không đoán.

Extract:

```bash
yq -o=json '
  select(
    .kind == "Deployment" or
    .kind == "StatefulSet"
  ) |
  {
    kind: .kind,
    name: .metadata.name,
    replicas: .spec.replicas,
    strategy: .spec.strategy,
    terminationGracePeriodSeconds: .spec.template.spec.terminationGracePeriodSeconds,
    topologySpreadConstraints: .spec.template.spec.topologySpreadConstraints,
    containers: [
      .spec.template.spec.containers[] |
      {
        name: .name,
        readinessProbe: .readinessProbe,
        livenessProbe: .livenessProbe,
        startupProbe: .startupProbe,
        lifecycle: .lifecycle,
        resources: .resources
      }
    ]
  }
' /tmp/mandate21-rendered.yaml
```

## 6.8. Scheduler/Karpenter baseline

```bash
kubectl get nodepool,ec2nodeclass,nodeclaim -o yaml
kubectl -n kube-system get deploy karpenter -o yaml
kubectl -n kube-system logs deploy/karpenter --since=30m
kubectl get events -A --sort-by=.lastTimestamp
```

Capture:

- NodePool limits;
- allowed zones/subnets;
- Spot-only restriction;
- instance families;
- CPU choices;
- current NodeClaims;
- provisioning latency from prior events if available.

## 6.9. Quota and IP baseline

```bash
kubectl -n techx-tf3 get resourcequota,limitrange -o yaml
kubectl describe node
aws ec2 describe-subnets \
  --filters Name=tag:karpenter.sh/discovery,Values=techx-corp-tf3 \
  --region ap-southeast-1
```

Record available IPs per subnet.

No final drill when remaining AZ subnet cannot host required replacement nodes/pods.

---

# 7. Current probe baseline to verify

The following is the observed source baseline and must be re-rendered from latest `main`:

| Service | Readiness baseline | Liveness baseline | Graceful baseline |
|---|---|---|---|
| frontend | TCP 8080, initial ~10s, period ~10s, failure 3 | TCP, initial ~20s, period ~20s, failure 3 | preStop ~5s, grace 30s |
| product-catalog | gRPC 8080, initial ~5s, period ~10s, failure 3 | TCP, initial ~15s, period ~20s, failure 3 | preStop ~5s, grace 30s |
| cart | TCP, initial ~15s, period ~10s, failure 3 | TCP, initial ~30s, period ~20s, failure 3 | preStop ~5s, grace 30s |
| checkout | gRPC, initial ~5s, period ~10s, failure 3 | TCP, initial ~15s, period ~20s, failure 3 | preStop ~5s, grace 30s |
| payment | TCP, initial ~10s, period ~10s, failure 3 | TCP, initial ~20s, period ~20s, failure 3 | preStop ~5s, grace 30s |
| currency | TCP, initial ~5s, period ~10s, failure 3 | TCP, initial ~15s, period ~20s, failure 3 | preStop ~5s, grace 30s |
| shipping | TCP, initial ~5s, period ~10s, failure 3 | TCP, initial ~15s, period ~20s, failure 3 | preStop ~5s, grace 30s |
| quote | phải render/audit | phải render/audit | phải render/audit |
| frontend-proxy | phải render/audit | phải render/audit | phải render/audit |

Không dùng bảng này thay cho render evidence.

---

# 8. Probe validation specification

## 8.1. Mục tiêu readiness

Readiness phải trả fail khi:

- process chưa bind hoặc chưa serving;
- service chưa hoàn thành startup bắt buộc;
- service không thể xử lý request local cơ bản;
- Pod đang graceful terminate và đã rút khỏi traffic.

Readiness không nên fail vì:

- telemetry backend chậm;
- non-critical AI/recommendation dependency lỗi;
- transient external dependency blip ngắn;
- một dependency không cần cho endpoint đang phục vụ, nếu app có degraded mode.

## 8.2. Mục tiêu liveness

Liveness chỉ nên restart khi process:

- deadlock;
- không còn serving nội bộ;
- không thể tự hồi phục;
- event loop/process health bị kẹt.

Không dùng liveness để kiểm:

- RDS availability;
- Valkey availability;
- Kafka availability;
- downstream gRPC service;
- external Internet;
- Bedrock.

Nếu liveness phụ thuộc downstream, AZ failure có thể tạo restart storm ở AZ lành.

## 8.3. Startup probe

Thêm startup probe khi:

```text
normal cold-start p99
+ image unpack variance
+ dependency initialization variance
> liveness initial delay/window
```

Startup probe phải ngăn liveness kill process hợp lệ đang khởi động.

Không thêm startup probe chỉ để che startup chậm bất thường; phải điều tra image pull, DNS, secret mount và connection init.

## 8.4. Protocol-level audit

Với mỗi TCP readiness:

1. Kiểm tra service có implement standard gRPC health không.
2. Kiểm tra có HTTP `/healthz` hoặc `/readyz` không.
3. Kiểm tra endpoint health có shallow/local semantics.
4. So sánh:
   - port-open time;
   - protocol-ready time;
   - first successful business request time.

Chỉ chuyển TCP → gRPC/HTTP khi endpoint đã tồn tại và semantics đúng.

Không thêm endpoint giả hoặc gọi business dependency sâu chỉ để “đẹp” probe.

## 8.5. Candidate tuning

Không hardcode candidate trước benchmark.

Một candidate hợp lý để test, không phải final mặc định:

```yaml
readinessProbe:
  periodSeconds: 5
  timeoutSeconds: 2
  failureThreshold: 2
  successThreshold: 1

livenessProbe:
  periodSeconds: 10
  timeoutSeconds: 2
  failureThreshold: 3
```

Acceptance chỉ khi:

- zero false readiness flaps trong soak;
- zero liveness restart do transient dependency;
- CPU/API overhead không đáng kể;
- new-pod ready time tốt hơn;
- business smoke pass.

## 8.6. Probe failure injection

Per service:

1. Start sustained low load.
2. Select one Pod.
3. Induce process-level non-serving state bằng approved method:
   - feature/fault mechanism hợp lệ;
   - process pause in non-production drill Pod;
   - blocked listener in isolated test.
4. Measure:
   - first failed probe;
   - Ready=False;
   - EndpointSlice removal;
   - request errors;
   - replacement/recovery.

Không kill node để test probe semantics.

## 8.7. False-positive soak

Sau tuning:

- minimum 30 phút normal load;
- một burst load;
- một downstream transient-failure test;
- no unexpected restart;
- no readiness oscillation;
- no endpoint churn burst.

---

# 9. Graceful shutdown validation

## 9.1. Planned termination path

For each hot-path service:

```text
DeletionTimestamp
→ preStop starts
→ readiness becomes false / endpoint removed
→ in-flight request completes or times out within budget
→ process receives/handles SIGTERM
→ container exits before grace deadline
```

Capture Kubernetes events and application logs.

## 9.2. Abrupt loss disclaimer

Trong sudden AZ loss:

- preStop may not execute;
- SIGTERM may not be delivered;
- process logs may stop abruptly;
- in-flight requests may fail.

Task output phải nói rõ:

```text
Graceful shutdown remains valid for planned disruption.
Sudden-AZ RTO is governed by endpoint evacuation,
surviving capacity, replacement scheduling and retry/idempotency.
```

## 9.3. Connection handling review

Audit client behavior trên money path:

- connect timeout;
- per-RPC timeout;
- total request deadline;
- retry count;
- retry backoff;
- retry only idempotent operations;
- stale connection eviction;
- DNS/service endpoint refresh;
- connection pool max lifetime/idle lifetime.

Do not solve stale connections by aggressive infinite retry.

For checkout/payment/order operations:

- define idempotency behavior;
- avoid duplicate charge/order on client retry;
- reconcile unknown outcomes after timeout.

## 9.4. Envoy/load-balancer behavior

Capture:

- upstream connect failure;
- reset reason;
- pending requests;
- endpoint count;
- retry behavior;
- outlier ejection, if configured.

Do not alter public/private boundary.

---

# 10. HPA and capacity specification

## 10.1. Current baseline

Current hot-path HPA characteristics:

```text
minReplicas: 2
CPU target: ~65%
scaleUp.stabilizationWindowSeconds: 0
scaleUp policy period: 60s
scaleDown.stabilizationWindowSeconds: 120s
```

Important:

`periodSeconds: 60` is a rate-limit window, not proof that HPA waits exactly 60 seconds.

Actual response also depends on:

- HPA controller sync period;
- metrics-server sample freshness;
- missing metrics behavior;
- Pod readiness;
- CPU request accuracy;
- desired/current replica calculation.

Must measure timestamps.

## 10.2. HPA coverage review

Required matrix:

| Service | Current HPA | CPU predicts saturation? | Surviving baseline capacity | Action |
|---|---:|---:|---:|---|
| frontend-proxy | yes | measure | measure | retain/tune |
| frontend | yes | measure | measure | retain/tune |
| product-catalog | yes | measure | measure | retain/tune |
| cart | yes | measure | measure | retain/tune |
| checkout | yes, Rollout target | measure | measure | retain/tune |
| payment | no observed | measure | measure | add only if justified |
| currency | yes | measure | measure | retain/tune |
| shipping | no observed | measure | measure | add only if justified |
| quote | no observed | measure | measure | add only if justified |

## 10.3. Surviving-capacity test

Before fault:

1. Measure requests/sec per Ready replica.
2. Identify replicas per AZ.
3. Estimate traffic after one AZ loss.
4. Run a controlled capacity test with only surviving replica count available.
5. Record:
   - CPU;
   - memory;
   - throttling;
   - p95/p99;
   - error rate;
   - queue/pool saturation.

The system must not rely exclusively on reactive HPA if one surviving replica immediately violates SLO before metrics arrive.

## 10.4. Scale-up acceptance

For every HPA-protected service:

- HPA conditions healthy before fault.
- `desiredReplicas` changes when metric crosses target.
- replacement pods schedule in remaining AZs.
- no `FailedGetResourceMetric`.
- no `FailedComputeMetricsReplicas`.
- no `ScalingLimited` due maxReplicas during required recovery.
- no pending pods due NodePool limit.
- capacity ready within app RTO budget.

## 10.5. Payment/shipping/quote decision

Add HPA only when all conditions hold:

1. Workload supports horizontal replication safely.
2. CPU or selected metric correlates with throughput/saturation.
3. Resource requests are realistic.
4. Startup time fits recovery budget.
5. Max replicas fit quota/budget.
6. Topology spread allows scheduling in remaining AZ.
7. Service is bottleneck or material RTO contributor.

If no HPA is added, final report must show why baseline replicas are sufficient under one-AZ-loss load.

## 10.6. MinReplica decision

Possible actions:

- keep `minReplicas: 2`;
- increase selected service to 3;
- pre-warm node capacity;
- adjust CPU requests;
- add missing HPA;
- modify maxReplicas;
- combine selectively.

No global increase without per-service evidence.

## 10.7. Scale-down safety

During drill:

- scaleDown stabilization must not remove replacement capacity during recovery oscillation;
- Karpenter consolidation must not race with recovery;
- no temporary `do-not-disrupt` workaround left after test.

Do not permanently disable cost controls without ADR.

---

# 11. Scheduling, topology and PDB specification

## 11.1. Topology render gate

For every required service, rendered Pod template must have zone spread.

Record:

```yaml
topologyKey: topology.kubernetes.io/zone
whenUnsatisfiable: DoNotSchedule
```

Also review:

- labelSelector matches Pod labels;
- maxSkew;
- minDomains if present;
- nodeAffinityPolicy;
- nodeTaintsPolicy;
- eligible domains after AZ removal.

## 11.2. Hard-spread deadlock test

A hard `DoNotSchedule` constraint can cause Pending Pod after AZ removal if eligible-domain calculation is not what team assumes.

Test:

1. Remove all schedulable nodes from one AZ in rehearsal.
2. Observe replacement scheduling.
3. Confirm no Pod Pending with:
   - topology spread unsatisfiable;
   - node affinity mismatch;
   - insufficient CPU/memory;
   - pod density/IP exhaustion.
4. Capture scheduler event message.

Do not weaken `DoNotSchedule` to `ScheduleAnyway` merely to clear Pending without risk analysis.

## 11.3. PDB validation

PDB acceptance:

- selector matches intended workload.
- expectedPods matches controller desired replicas.
- `minAvailable: 1` does not deadlock rehearsal.
- PDB is not cited as sudden-failure protection.
- checkout PDB works with Rollout/workloadRef behavior.

For abrupt loss, capture PDB status but expect involuntary disruption can violate it.

## 11.4. Node headroom

At stable load before fault, calculate remaining allocatable capacity in each surviving AZ.

Required report:

```json
{
  "zone": "ap-southeast-1b",
  "allocatableCpuMilli": 8000,
  "requestedCpuMilli": 5200,
  "headroomCpuMilli": 2800,
  "allocatableMemoryMi": 30000,
  "requestedMemoryMi": 21000,
  "headroomMemoryMi": 9000,
  "availablePodSlots": 42
}
```

Compare with replacement request set for the failed AZ.

## 11.5. Karpenter gate

Before relying on Karpenter:

- NodePool Ready.
- EC2NodeClass Ready.
- allowed subnets span remaining AZs.
- Spot capacity types available.
- NodePool `cpu: 12` limit not exhausted.
- EC2 quota not exhausted.
- no subnet IP shortage.
- AMI can boot.
- node role and CNI healthy.
- image pull access works.

Measure cold NodeClaim-to-NodeReady time.

## 11.6. Spot-only risk

Current NodePool is Spot-only.

For DR:

- record whether base managed nodes provide enough stable capacity;
- record whether replacement depends on Spot availability;
- test at least one cold scale-up;
- define fallback decision if Spot is unavailable.

Do not silently switch to expensive On-Demand without cost/ownership review.

---

# 12. Load and SLO contract

## 12.1. Load profile

Final drill must use sustained workload, not one curl loop.

Minimum journey:

```text
browse
→ product detail/catalog
→ add cart
→ view cart
→ checkout
→ order acknowledgement
```

Load profile must record:

- virtual users;
- arrival rate;
- duration;
- think time;
- request distribution;
- retry behavior;
- timeout;
- dataset;
- commit SHA;
- target hostname.

## 12.2. SLO metrics

At minimum:

```text
browse success rate
cart success rate
checkout success rate
frontend p95/p99
checkout p95/p99
HTTP/gRPC error rate
orders acknowledged
orders persisted
duplicate orders
```

Use exact SLO thresholds from signed project ADR/evidence.

Do not create easier thresholds for this drill.

## 12.3. Load-generator independence

Load generator must not run only in AZ being killed.

Preferred:

- external load generator;
- or workload known to survive target AZ;
- or separate controlled environment.

If load generator dies with AZ, test invalid.

## 12.4. Retry accounting

Client retries must be visible.

Report separately:

```text
initial attempt success
retry success
retry exhausted
unknown checkout outcome
duplicate result
```

A high client retry rate can hide server recovery problems.

---

# 13. Observability contract

## 13.1. Required telemetry

Capture:

### Kubernetes

- Node Ready condition.
- Pod phase/Ready condition.
- Deployment/Rollout desired/current/available.
- EndpointSlice endpoints and zone hints if present.
- HPA status/conditions.
- PDB status.
- events.
- scheduler failures.
- Karpenter NodeClaim lifecycle.

### Application

- request rate.
- error rate.
- p50/p95/p99.
- in-flight requests.
- connection errors.
- timeout/retry counts.
- order reconciliation.

### Infrastructure

- EC2 instance state.
- AZ/subnet.
- managed-store failover events from CDO02.
- load balancer target health.
- node autoscaling events.

## 13.2. Timestamp normalization

All evidence timestamps must use UTC ISO-8601:

```text
2026-07-21T12:34:56.789Z
```

No screenshot-only timestamp without source query.

Synchronize operator host clock before drill.

## 13.3. Prometheus query contract

Save exact PromQL in Git.

Examples, subject to actual labels:

```promql
sum(rate(http_server_request_duration_seconds_count{
  service_name=~"frontend|checkout|cart|product-catalog|payment|currency|shipping|quote",
  http_response_status_code=~"5.."
}[1m]))
/
sum(rate(http_server_request_duration_seconds_count{
  service_name=~"frontend|checkout|cart|product-catalog|payment|currency|shipping|quote"
}[1m]))
```

```promql
histogram_quantile(
  0.95,
  sum by (le, service_name) (
    rate(http_server_request_duration_seconds_bucket[1m])
  )
)
```

```promql
kube_deployment_status_replicas_available{
  namespace="techx-tf3"
}
```

```promql
kube_hpa_status_desired_replicas{
  namespace="techx-tf3"
}
```

Queries must be corrected to match actual metrics before use.

## 13.4. Event timeline collector

A collector should capture every few seconds:

```text
nodes
pods
endpointslices
deployments
rollouts
hpas
pdbs
nodeclaims
events
```

Do not rely on manually copying `kubectl get` after recovery.

---

# 14. Proposed file impact map

## 14.1. Production config candidates

Modify only when evidence requires:

```text
phase3 - information/deploy/values-prod.yaml
gitops/infrastructure/hpa-hotpath.yaml
gitops/infrastructure/pdb-checkout.yaml
gitops/karpenter/spot-nodepool.yaml
```

PDB/Karpenter changes are not automatic requirements.

## 14.2. Scripts to add

```text
scripts/dr/mandate-21/preflight.sh
scripts/dr/mandate-21/render-audit.sh
scripts/dr/mandate-21/capture-timeline.sh
scripts/dr/mandate-21/capture-capacity.sh
scripts/dr/mandate-21/rehearse-az-evacuation.sh
scripts/dr/mandate-21/recover-rehearsal.sh
scripts/dr/mandate-21/reconcile-orders.py
scripts/dr/mandate-21/analyze-rto.py
scripts/dr/mandate-21/verify-evidence.py
```

## 14.3. Tests to add

```text
tests/mandate-21/test_render_contract.py
tests/mandate-21/test_hpa_contract.py
tests/mandate-21/test_topology_contract.py
tests/mandate-21/test_probe_contract.py
tests/mandate-21/test_rto_analyzer.py
tests/mandate-21/fixtures/
```

## 14.4. Docs to add

```text
docs/adr/00XX-mandate-21-application-recovery.md
docs/runbooks/mandate-21-application-recovery.md
docs/runbooks/mandate-21-az-rehearsal.md
docs/evidence/mandate-21/application-recovery/README.md
```

## 14.5. Protected areas

PM-163 must not change without separate approval:

```text
flagd fault configuration
public/private ingress boundary
RDS/MSK/ElastiCache topology
backup retention
Kyverno policy mode
NetworkPolicy
application payment semantics
ECR supply-chain policy
```

---

# 15. Script contracts

## 15.1. `preflight.sh`

Must fail closed on:

- wrong AWS account;
- wrong cluster;
- dirty Git tree;
- Argo Degraded;
- missing metrics-server;
- missing required HPA/PDB inventory;
- critical service replica <2;
- service concentrated in one AZ;
- fewer than two healthy AZs;
- loadgen unavailable;
- no RTO commitment;
- no rollback owner;
- Mandate 20 prerequisite not accepted for final test.

Output machine-readable JSON.

## 15.2. `render-audit.sh`

Must:

- discover Argo values inputs;
- render chart;
- extract all required services;
- verify probes;
- verify grace period/lifecycle;
- verify topology;
- verify replicas;
- compare HPA targets;
- compare PDB selectors;
- fail on missing dependency closure.

## 15.3. `capture-timeline.sh`

Must:

- accept drill ID;
- record UTC timestamps;
- poll API objects;
- not mutate cluster;
- continue through transient API errors;
- mark gaps explicitly;
- write JSONL;
- flush frequently;
- terminate cleanly.

## 15.4. `capture-capacity.sh`

Must calculate:

- allocatable/requested/headroom per AZ;
- required replacement requests for target AZ;
- NodePool remaining limit;
- pending pod reasons;
- subnet IP availability snapshot.

## 15.5. `rehearse-az-evacuation.sh`

Safety:

- require explicit AZ argument;
- print selected nodes;
- reject empty/unknown AZ;
- reject when AZ contains all nodes;
- require typed confirmation or CI-approved environment;
- record node list hash;
- cordon first;
- drain sequentially or according to approved plan;
- respect PDB;
- timeout;
- no `--force` by default;
- no deletion of unmanaged Pod without explicit approval;
- emit recovery commands before execution.

This script is rehearsal only.

## 15.6. `recover-rehearsal.sh`

Must:

- uncordon original nodes still present;
- verify node Ready;
- verify workloads;
- remove only drill-specific temporary state;
- never modify GitOps-owned production configuration imperatively;
- run smoke tests;
- capture post-state.

## 15.7. `reconcile-orders.py`

Inputs:

```text
load-generator request log
acknowledged order IDs
datastore query/export
drill time window
```

Output:

```json
{
  "attempted": 0,
  "acknowledged": 0,
  "persistedAcknowledged": 0,
  "missingAcknowledged": [],
  "duplicateOrderIds": [],
  "unknownOutcome": []
}
```

Exit non-zero when `missingAcknowledged` is non-empty.

## 15.8. `analyze-rto.py`

Must:

- parse timeline JSONL;
- parse SLO time series;
- accept committed thresholds;
- find first breach;
- find sustained recovery;
- calculate all T0–T16 metrics;
- identify missing evidence;
- not interpolate silently;
- output JSON and Markdown summary.

---

# 16. PR execution plan

## PR 0 — Baseline, ADR draft, harness

### Changes

- record latest-main process;
- dependency closure;
- render audit script;
- timeline/capacity collector;
- RTO analyzer tests;
- no production config change.

### Exit gate

- latest production render captured;
- exact current probes/HPA/PDB/topology known;
- current node/AZ distribution known;
- RTO fields assigned;
- scripts run read-only;
- no claim of improvement.

---

## PR 1 — Probe semantics and measured tuning

### Changes

Only services whose tests show a gap.

Possible:

- TCP → gRPC/HTTP readiness;
- period/threshold tuning;
- startup probe;
- no speculative liveness dependency checks.

### Exit gate

- render contract pass;
- isolated rollout pass;
- no false-positive soak;
- planned Pod delete/rollout pass;
- business smoke pass;
- no restart storm.

### Rollback

Git revert PR 1.

---

## PR 2 — HPA coverage/capacity changes

### Changes

Only evidence-backed:

- payment HPA;
- shipping HPA;
- quote HPA;
- min/max/target adjustments;
- scale behavior adjustment;
- selected replica baseline.

### Exit gate

- CPU/metric correlation proven;
- HPA target resource exists;
- scale-up measured;
- no quota breach;
- no Pending;
- budget impact recorded;
- scale-down stable.

### Rollback

Git revert PR 2.

---

## PR 3 — Scheduling/headroom remediation

Only if rehearsal exposes:

- topology Pending;
- insufficient node capacity;
- NodePool limit;
- subnet/IP issue;
- anti-affinity/scheduling gap.

Do not combine multiple unproven fixes.

### Exit gate

- targeted failure reproduced before fix;
- same failure absent after fix;
- no normal-operation regression;
- cost delta recorded.

---

## PR 4 — Planned AZ evacuation rehearsal

### Purpose

Validate:

- PDB;
- graceful shutdown;
- topology scheduling;
- replacement capacity;
- HPA/Karpenter observation;
- evidence tooling.

### Explicit limitation

Does not close final sudden-AZ DoD.

---

## PR 5 — Coordinated sudden-AZ acceptance drill

Owned jointly:

```text
CDO01: application recovery / probes / HPA / app RTO
CDO02: fault mechanism / node-AZ / managed-store failover / total RTO-RPO
Mentor: unexpected AZ and timing
```

No code change during drill except approved emergency rollback.

---

## PR 6 — Evidence and closure

- final ADR;
- RTO report;
- order reconciliation;
- SLO graphs;
- timeline;
- residual risk;
- exact contribution to PM-159;
- no statement that PM-163 alone closes full Mandate 21.

---

# 17. Detailed execution plan

## Phase A — Confirm prerequisite and ownership

Before final acceptance:

- Mandate 20 restore drill accepted.
- CDO02 confirms managed-store failover readiness.
- RTO/RPO commitment signed.
- mentor/CDO02 agrees fault mechanism.
- operator access survives target AZ loss.
- load generator independent.
- rollback owner named.

## Phase B — Render and inventory

1. Pull latest main.
2. Discover Argo source files.
3. Render production.
4. Extract service matrix.
5. Compare rendered vs live.
6. Explain drift before proceeding.
7. Capture probes, replicas, topology, lifecycle.
8. Capture HPA/PDB targets.
9. Capture node/AZ placement.

Stop on unexplained drift.

## Phase C — Probe semantics testing

For each required service:

1. Measure cold start.
2. Measure port-open time.
3. Measure business/protocol-ready time.
4. Verify readiness transitions.
5. Induce process non-serving state.
6. Verify endpoint removal.
7. Verify liveness only restarts unrecoverable process.
8. Run dependency transient test.
9. Soak.
10. Decide no-change or patch.

Every no-change decision needs evidence.

## Phase D — Capacity model

1. Run stable target load.
2. Measure per-pod utilization/throughput.
3. Calculate lost replicas for each possible AZ.
4. Calculate surviving capacity.
5. Calculate replacement Pod requests.
6. Compare node headroom.
7. Measure Karpenter cold provision.
8. Identify service likely to break SLO first.
9. Decide HPA/minReplica/headroom changes.
10. Record cost delta.

## Phase E — HPA test

For each target:

1. Record baseline current/desired replicas.
2. Increase load predictably.
3. Capture metric sample time.
4. Capture desiredReplicas change.
5. Capture Pod creation.
6. Capture Ready time.
7. Verify remaining AZ distribution.
8. Verify max not limiting.
9. Reduce load.
10. Verify stable scale-down.

## Phase F — Rehearsal

1. Start telemetry collector.
2. Start order-aware load.
3. Wait stable baseline.
4. Select an AZ for rehearsal.
5. Record nodes and Pod distribution.
6. Cordon all selected nodes.
7. Drain using approved options.
8. Observe replacement.
9. Measure app recovery.
10. Verify order data.
11. Recover/uncordon.
12. Run post-smoke.
13. Document planned-disruption result and limitations.

## Phase G — Sudden acceptance drill

1. Start collectors before mentor action.
2. Do not know target AZ/time.
3. Mentor/CDO02 injects fault.
4. CDO01 does not manually scale.
5. Capture T0–T16.
6. Observe endpoint removal.
7. Observe replacement scheduling.
8. Observe HPA and Karpenter.
9. Observe application SLO.
10. Keep load running.
11. Reconcile orders.
12. Confirm stable recovery.
13. CDO02 restores infrastructure according to runbook.
14. Capture full post-state.

## Phase H — Analysis and closure

1. Run RTO analyzer.
2. Compare against commitment.
3. Separate app vs store/network contribution.
4. List bottleneck.
5. Explain any errors.
6. Prove no acknowledged order loss.
7. Record duplicates/unknown outcomes.
8. Record cost and residual risks.
9. Update Jira with evidence paths.
10. Do not close when evidence is incomplete.

---

# 18. Rehearsal command skeleton

## 18.1. Select nodes by AZ

```bash
AZ="ap-southeast-1a"

mapfile -t NODES < <(
  kubectl get nodes \
    -l "topology.kubernetes.io/zone=${AZ}" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
)

printf '%s\n' "${NODES[@]}"
test "${#NODES[@]}" -gt 0
```

## 18.2. Pre-capture

```bash
DRILL_ID="pm163-rehearsal-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "docs/evidence/mandate-21/application-recovery/drills/${DRILL_ID}"

kubectl get nodes -o wide \
  > ".../${DRILL_ID}/nodes-before.txt"

kubectl -n techx-tf3 get pod -o wide \
  > ".../${DRILL_ID}/pods-before.txt"

kubectl -n techx-tf3 get hpa,pdb \
  > ".../${DRILL_ID}/autoscaling-disruption-before.txt"
```

Use actual path, not literal ellipsis.

## 18.3. Cordon

```bash
for node in "${NODES[@]}"; do
  kubectl cordon "$node"
done
```

## 18.4. Drain

Options must be approved after inventory.

Conceptual:

```bash
for node in "${NODES[@]}"; do
  kubectl drain "$node" \
    --ignore-daemonsets \
    --delete-emptydir-data \
    --grace-period=-1 \
    --timeout=15m
done
```

Do not add `--force` by default.

Drain failure due PDB is evidence, not a reason to bypass automatically.

## 18.5. Recovery

```bash
for node in "${NODES[@]}"; do
  kubectl uncordon "$node" || true
done
```

Only uncordon nodes that still exist and are healthy.

---

# 19. Sudden-AZ acceptance guardrails

PM-163 does not prescribe the destructive infrastructure command.

CDO02 runbook must guarantee:

1. Exact target AZ is recorded.
2. Exact target instances/nodes are recorded.
3. Fault is abrupt.
4. Failed AZ does not immediately receive replacement capacity.
5. EKS control plane access remains.
6. Load generator remains.
7. Recovery path exists.
8. Managed-store state is monitored.
9. No data deletion is used to simulate AZ loss.
10. Blast radius is limited to agreed TF3 resources.
11. Stop/restore owner is online.
12. Fault action is auditable.

Prohibited for CDO01 ad-hoc use:

```text
editing subnet NACL without reviewed runbook
deleting subnets
deleting route tables
deleting node groups
deleting persistent data
changing cluster security group broadly
turning off observability before test
```

---

# 20. Test matrix

## 20.1. Static/render tests

| ID | Test | Expected |
|---|---|---|
| RENDER-001 | Production chart renders | Pass |
| RENDER-002 | Argo values source set matches render command | Pass |
| RENDER-003 | All seven Jira services present | Pass |
| RENDER-004 | frontend-proxy present | Pass |
| RENDER-005 | quote present | Pass |
| RENDER-006 | Required replicas >=2 | Pass or approved exception |
| RENDER-007 | Readiness exists | Pass |
| RENDER-008 | Liveness exists | Pass |
| RENDER-009 | Startup probe required by measured startup | Present |
| RENDER-010 | termination grace exists | Pass |
| RENDER-011 | lifecycle/preStop expected | Pass |
| RENDER-012 | Zone topology constraint exists | Pass |
| RENDER-013 | Zone selector matches Pod labels | Pass |
| RENDER-014 | Rolling strategy preserves availability | Pass |
| RENDER-015 | HPA target exists | Pass |
| RENDER-016 | HPA target kind correct | Pass |
| RENDER-017 | Checkout HPA targets Rollout | Pass |
| RENDER-018 | PDB selector matches workload | Pass |
| RENDER-019 | Rendered/live drift unexplained | Fail |
| RENDER-020 | Flagd config changes in PM-163 PR | Fail |

## 20.2. Probe tests

| ID | Test | Expected |
|---|---|---|
| PROBE-001 | Cold start readiness | No traffic before ready |
| PROBE-002 | Port opens before protocol ready | Readiness stays false if applicable |
| PROBE-003 | Healthy steady state | Ready true |
| PROBE-004 | Process non-serving | Ready false within measured budget |
| PROBE-005 | Endpoint removal after Ready false | Measured |
| PROBE-006 | Process deadlock/unrecoverable | Liveness restart |
| PROBE-007 | RDS transient failure | No restart storm |
| PROBE-008 | Valkey transient failure | No restart storm |
| PROBE-009 | Kafka transient failure | No restart storm |
| PROBE-010 | Telemetry backend failure | No readiness/liveness cascade |
| PROBE-011 | High load | No false liveness |
| PROBE-012 | 30-minute soak | No flapping |
| PROBE-013 | gRPC health unsupported | Do not configure gRPC probe blindly |
| PROBE-014 | TCP accepted with ADR | Semantics documented |
| PROBE-015 | Startup p99 exceeds liveness window | Startup probe required |

## 20.3. Graceful shutdown tests

| ID | Test | Expected |
|---|---|---|
| GRACE-001 | Pod delete planned | preStop observed |
| GRACE-002 | Endpoint removed before exit | Pass |
| GRACE-003 | In-flight request completes within budget | Pass |
| GRACE-004 | Container exits before grace deadline | Pass |
| GRACE-005 | Drain respects PDB | Pass |
| GRACE-006 | Abrupt node loss | No claim preStop ran |
| GRACE-007 | Stale connection after endpoint loss | Bounded timeout/retry |
| GRACE-008 | Non-idempotent retry | No duplicate order/charge |
| GRACE-009 | Infinite retry | Fail |
| GRACE-010 | Grace period exceeded | Investigate/fail |

## 20.4. HPA tests

| ID | Test | Expected |
|---|---|---|
| HPA-001 | Metrics-server healthy | Pass |
| HPA-002 | CPU requests exist | Pass |
| HPA-003 | HPA conditions healthy | Pass |
| HPA-004 | Stable load below target | No unnecessary scale |
| HPA-005 | Load exceeds target | desired increases |
| HPA-006 | scale-up timestamp captured | Pass |
| HPA-007 | Pods become Ready | Within budget |
| HPA-008 | maxReplicas reached before SLO recovery | Fail/tune |
| HPA-009 | ScalingLimited during required recovery | Fail/tune |
| HPA-010 | FailedGetResourceMetric | Fail |
| HPA-011 | New Pod missing metrics | Explained/measured |
| HPA-012 | payment capacity sufficient without HPA | Evidence |
| HPA-013 | payment insufficient | Add/tune HPA |
| HPA-014 | shipping capacity sufficient without HPA | Evidence |
| HPA-015 | shipping insufficient | Add/tune HPA |
| HPA-016 | quote capacity sufficient without HPA | Evidence |
| HPA-017 | quote insufficient | Add/tune HPA |
| HPA-018 | Scale-down after recovery | Stable |
| HPA-019 | Scale-down causes second SLO dip | Fail |
| HPA-020 | HPA manual scaling needed in final drill | Fail automatic recovery |

## 20.5. Topology/PDB tests

| ID | Test | Expected |
|---|---|---|
| TOPO-001 | Nodes span >=2 AZ | Pass |
| TOPO-002 | Critical Pods span AZ | Pass |
| TOPO-003 | Mentor-selected AZ holds critical Pods | Test valid |
| TOPO-004 | Remove one AZ in rehearsal | replacements schedule |
| TOPO-005 | Hard topology causes Pending | Fail/tune |
| TOPO-006 | Selector mismatch | Fail |
| TOPO-007 | PDB expectedPods matches | Pass |
| TOPO-008 | PDB disruptionsAllowed before drain | >0 as required |
| TOPO-009 | Drain blocked by correct safety PDB | Investigate, no force |
| TOPO-010 | Abrupt failure violates PDB | Expected limitation documented |
| TOPO-011 | All Ready replicas in one AZ | Fail |
| TOPO-012 | Replacement lands failed AZ during acceptance | Test invalid/fail fault model |
| TOPO-013 | Surviving zones receive replacement | Pass |
| TOPO-014 | Node taint blocks replacement | Fail/tune |
| TOPO-015 | Insufficient pod slots/IP | Fail/tune |

## 20.6. Karpenter/capacity tests

| ID | Test | Expected |
|---|---|---|
| KARP-001 | NodePool Ready | Pass |
| KARP-002 | EC2NodeClass Ready | Pass |
| KARP-003 | Remaining NodePool CPU limit sufficient | Pass |
| KARP-004 | Remaining memory limit sufficient | Pass |
| KARP-005 | Subnet IP sufficient | Pass |
| KARP-006 | Spot capacity available in remaining AZ | Pass or fallback decision |
| KARP-007 | Pending Pod triggers NodeClaim | Pass |
| KARP-008 | NodeClaim created timestamp captured | Pass |
| KARP-009 | Node Ready within budget | Pass |
| KARP-010 | Image pull/start succeeds | Pass |
| KARP-011 | Node launches in failed AZ | Fail drill semantics |
| KARP-012 | NodePool limit blocks recovery | Fail/tune |
| KARP-013 | EC2 quota blocks recovery | Fail/preflight |
| KARP-014 | Consolidation removes recovery node too soon | Fail/tune |
| KARP-015 | Karpenter unavailable | Stop final drill |

## 20.7. Rehearsal tests

| ID | Test | Expected |
|---|---|---|
| REH-001 | Sustained load stable 5m | Pass |
| REH-002 | Selected AZ recorded | Pass |
| REH-003 | All target nodes cordoned | Pass |
| REH-004 | PDB respected | Pass |
| REH-005 | Replacement Pods created | Pass |
| REH-006 | Replacement Pods in remaining AZ | Pass |
| REH-007 | HPA observed | Pass |
| REH-008 | Karpenter observed if needed | Pass |
| REH-009 | Browse/cart/checkout measured | Pass |
| REH-010 | Orders reconciled | 0 missing acknowledged |
| REH-011 | Nodes uncordoned/recovered | Pass |
| REH-012 | Rehearsal labeled as planned | Pass |
| REH-013 | Rehearsal presented as final sudden test | Fail report |

## 20.8. Sudden-AZ tests

| ID | Test | Expected |
|---|---|---|
| AZ-001 | Mentor/CDO02 chooses AZ unexpectedly | Pass |
| AZ-002 | Load active before fault | Pass |
| AZ-003 | Fault abrupt, no drain | Pass |
| AZ-004 | Failed AZ remains unavailable | Pass |
| AZ-005 | Node loss timestamp | Captured |
| AZ-006 | Endpoint evacuation | Captured |
| AZ-007 | SLO dip | Captured or no dip proven |
| AZ-008 | Replacement automatic | Pass |
| AZ-009 | HPA automatic | Pass if required |
| AZ-010 | Karpenter automatic | Pass if required |
| AZ-011 | No manual service scale | Pass |
| AZ-012 | App RTO <= committed budget | Pass |
| AZ-013 | Total RTO provided to PM-159 | Pass |
| AZ-014 | Acknowledged order loss | Zero |
| AZ-015 | Duplicate order | Zero/unexplained zero |
| AZ-016 | Unknown outcomes reconciled | Pass |
| AZ-017 | Recovery stable | Pass |
| AZ-018 | Any-AZ design evidence | Pass |
| AZ-019 | Load generator lost with AZ | Test invalid |
| AZ-020 | Failed AZ immediately reused | Test invalid |
| AZ-021 | Manual restart required | Fail automatic recovery |
| AZ-022 | Storefront operational boundary changed | Fail |

## 20.9. Evidence integrity tests

| ID | Test | Expected |
|---|---|---|
| EVID-001 | Main SHA recorded | Pass |
| EVID-002 | Drill ID unique | Pass |
| EVID-003 | UTC timestamps | Pass |
| EVID-004 | Raw load output present | Pass |
| EVID-005 | Raw K8s timeline present | Pass |
| EVID-006 | PromQL saved | Pass |
| EVID-007 | Order reconciliation input/output | Pass |
| EVID-008 | RTO analyzer reproducible | Pass |
| EVID-009 | Screenshot without raw query | Insufficient |
| EVID-010 | Missing time window | Fail |
| EVID-011 | Config commit differs from deployed | Fail |
| EVID-012 | Manual unexplained correction | Fail |
| EVID-013 | Reviewer can run verify script | Pass |
| EVID-014 | Secret/token in evidence | Fail/security incident |
| EVID-015 | Final report separates app and total RTO | Pass |

---

# 21. Stop conditions

Stop before or during drill when:

- Mandate 20 prerequisite not complete for final acceptance.
- Active customer/production incident.
- Wrong AWS account or cluster context.
- Git/Argo drift unexplained.
- Fewer than two healthy AZs.
- Critical service already below desired replicas.
- PDB unhealthy before rehearsal.
- HPA metrics unavailable.
- Karpenter/NodePool not Ready.
- Remaining subnet IP insufficient.
- NodePool limit leaves no recovery capacity.
- load generator cannot reconcile orders.
- observability unavailable.
- operator access depends on selected AZ.
- managed store not ready for failover.
- no approved RTO/RPO.
- no rollback/fault recovery owner.
- fault method has broader blast radius than TF3.
- failed AZ can immediately receive replacement during final test.
- storefront SLO is already failing before T0.
- order reconciliation detects data corruption.
- checkout/payment duplicate risk becomes unbounded.
- API server access is lost.
- fault action affects backups.
- unrelated flagd/security/network configuration drifts.
- mentor/CDO02 aborts.

During a sudden drill, “stop” means execute CDO02 recovery runbook; do not mutate application randomly.

---

# 22. Rollback and recovery

## 22.1. Config rollback

Use Git revert for each isolated PR:

```bash
git revert <probe-tuning-commit>
git push
```

Separate commits for:

- probes;
- HPA;
- topology;
- Karpenter capacity.

## 22.2. Rehearsal recovery

- uncordon healthy nodes;
- wait for Ready;
- ensure no lingering drain process;
- ensure all workloads available;
- ensure HPA stable;
- ensure no Pod Pending;
- verify storefront/cart/checkout;
- reconcile orders;
- archive evidence.

## 22.3. Sudden fault recovery

Owned by CDO02.

PM-163 responsibilities after infrastructure is restored:

- verify node registration;
- verify Pod redistribution;
- verify HPA stabilization;
- verify no stale endpoint;
- verify no restart loop;
- verify application SLO;
- verify order consistency.

## 22.4. Rollback validation

```bash
kubectl -n argocd get application
kubectl get nodes -L topology.kubernetes.io/zone
kubectl -n techx-tf3 get deploy,rollout,pod,hpa,pdb
kubectl -n techx-tf3 get endpointslice
```

Run exact smoke/load verification from evidence contract.

---

# 23. Evidence pack

```text
docs/evidence/mandate-21/application-recovery/
├── README.md
├── baseline/
│   ├── main-sha.txt
│   ├── aws-identity-redacted.json
│   ├── cluster-info.txt
│   ├── nodes.json
│   ├── node-zone-capacity.json
│   ├── pods.json
│   ├── pod-zone-distribution.json
│   ├── hpas.yaml
│   ├── pdbs.yaml
│   ├── nodepools.yaml
│   ├── nodeclaims.yaml
│   ├── rendered-hotpath.yaml
│   ├── probe-inventory.json
│   └── topology-inventory.json
├── probes/
│   ├── before.json
│   ├── cold-start-results.json
│   ├── failure-detection-results.json
│   ├── false-positive-soak.json
│   ├── after.json
│   └── decision.md
├── hpa/
│   ├── baseline.json
│   ├── metric-correlation.csv
│   ├── scale-up-timeline.jsonl
│   ├── scale-down-timeline.jsonl
│   ├── payment-decision.md
│   ├── shipping-decision.md
│   ├── quote-decision.md
│   └── capacity-model.json
├── rehearsal/
│   └── <DRILL_ID>/
│       ├── manifest.json
│       ├── target-az.txt
│       ├── target-nodes.json
│       ├── load-config.json
│       ├── raw-load-output.json
│       ├── timeline.jsonl
│       ├── events.jsonl
│       ├── hpa.jsonl
│       ├── endpointslices.jsonl
│       ├── nodeclaims.jsonl
│       ├── rto-analysis.json
│       ├── rto-analysis.md
│       ├── order-reconciliation.json
│       ├── smoke-after.txt
│       └── limitations.md
├── sudden-az/
│   └── <DRILL_ID>/
│       ├── manifest.json
│       ├── mentor-fault-record.txt
│       ├── target-az.txt
│       ├── target-nodes.json
│       ├── load-config.json
│       ├── raw-load-output.json
│       ├── prometheus-range-results/
│       ├── timeline.jsonl
│       ├── events.jsonl
│       ├── hpa.jsonl
│       ├── endpointslices.jsonl
│       ├── nodeclaims.jsonl
│       ├── infrastructure-events-redacted.json
│       ├── rto-analysis.json
│       ├── rto-analysis.md
│       ├── order-reconciliation.json
│       ├── post-recovery-soak.json
│       └── mentor-checklist.md
├── queries/
│   ├── slo.promql
│   ├── kubernetes.promql
│   ├── hpa.promql
│   └── node.promql
├── final/
│   ├── closure-checklist.md
│   ├── application-rto.md
│   ├── contribution-to-total-rto.md
│   ├── residual-risks.md
│   ├── deployed-commit.txt
│   └── reviewer-reproduction.md
└── README.md
```

Do not commit:

- credentials;
- kubeconfig;
- bearer token;
- AWS session token;
- DB password;
- private endpoint secret;
- customer PII;
- full payment data.

---

# 24. Evidence manifest schema

Every drill folder must include:

```json
{
  "schemaVersion": 1,
  "drillId": "pm163-sudden-az-...",
  "type": "rehearsal-or-sudden",
  "repository": "tuu-ngo/Phase3-TF3-Infra-Sentinel",
  "sourceSha": "<40-hex>",
  "deployedRevision": "<40-hex>",
  "cluster": "techx-corp-tf3",
  "region": "ap-southeast-1",
  "namespace": "techx-tf3",
  "startedAtUtc": "...",
  "faultAtUtc": "...",
  "targetAz": "...",
  "loadProfile": "...",
  "rtoCommitmentSeconds": 0,
  "applicationRtoBudgetSeconds": 0,
  "rpoCommitment": "0 acknowledged orders lost",
  "operators": [],
  "mentorPresent": true,
  "artifacts": [],
  "sha256": {}
}
```

Evidence verifier must hash important raw files.

---

# 25. DoD mapping

## DoD 1

> Mô phỏng mất 1 AZ → Pod reschedule sang AZ khác trong thời gian đo được.

Required evidence:

- target AZ/nodes;
- Pod placement before;
- fault timestamp;
- replacement creation timestamp;
- scheduling timestamp;
- Ready timestamp;
- replacement AZ;
- no manual scale;
- RTO analysis.

Rehearsal satisfies preparation. Final mandate evidence requires sudden drill.

## DoD 2

> HPA scale bù kịp ở AZ còn lại, không để thiếu capacity kéo dài.

Required evidence:

- HPA status before/during/after;
- metrics samples;
- desired/current replicas timeline;
- Pod Ready timeline;
- scheduler/Karpenter timeline;
- SLO timeline;
- max/limit status;
- decision for payment/shipping/quote;
- surviving-capacity model.

If HPA does not need to scale because headroom keeps SLO, report that fact rather than fabricate HPA action. Jira’s intent is sufficient capacity, not forcing scale for demonstration.

## DoD 3

> Đóng góp rõ vào RTO tổng.

Required:

```text
application_rto
endpoint_evacuation
replacement_ready
hpa_reaction
node_provisioning
data-store failover contribution supplied by CDO02
total_rto
```

Final report must state which stage dominated.

## DoD 4

> Probe/HPA/graceful configuration confirmed or corrected.

Required:

- render before;
- test method;
- decision per service;
- render after;
- no false-positive soak;
- planned graceful test;
- sudden-loss limitation;
- deployed Git revision.

---

# 26. Distinction from full Mandate 21

PM-163 closes application recovery/performance contribution.

Full Mandate 21 still needs combined evidence for:

- Mandate 20 prerequisite;
- managed-store failover;
- zero data loss;
- full AZ fault mechanism;
- infrastructure automatic recovery;
- total RTO/RPO;
- mentor-selected sudden fault;
- signed DR ADR;
- cost tradeoff.

Final closure language:

```text
PM-163 complete:
application-layer recovery, probe behavior, autoscaling/capacity,
replacement scheduling and application RTO contribution verified.

Full Mandate 21 remains dependent on PM-159/CDO02 combined
sudden-AZ and managed-store evidence.
```

Do not write:

```text
Mandate 21 hoàn thành 100%
```

unless parent evidence satisfies every directive requirement.

---

# 27. Agent execution contract

Agent must:

1. Pull latest main.
2. Record exact SHA.
3. Discover actual Argo values inputs.
4. Render before editing.
5. Never infer live state from comments alone.
6. Separate planned drain from abrupt loss.
7. Never claim probe detects dead AZ.
8. Never claim HPA reschedules lost Pod.
9. Include frontend-proxy and quote in test closure.
10. Audit payment/shipping/quote HPA gap.
11. Measure before changing min replicas.
12. Measure Karpenter capacity/limits.
13. Verify remaining-AZ subnet IP.
14. Preserve flagd.
15. Preserve network exposure boundary.
16. Keep production changes in small PRs.
17. Use Git rollback.
18. Never force drain automatically.
19. Never run destructive AZ fault without CDO02/mentor.
20. Keep load running through fault.
21. Reconcile order IDs.
22. Record UTC timestamps.
23. Store raw evidence.
24. Run post-recovery soak.
25. Stop on stop condition.
26. State residual risks honestly.
27. Do not close full Mandate 21 from PM-163 alone.

## Agent final report format

```text
Task:
Phase:
Branch:
Base main SHA:
Deployed SHA:
PRs:
Commits:
Files changed:

RTO commitments:
- Total:
- Application budget:
- RPO:

Baseline:
- Healthy AZs:
- Nodes per AZ:
- Critical Pod distribution:
- HPA inventory:
- PDB inventory:
- Karpenter headroom:
- Subnet/IP headroom:

Probe decisions:
- frontend:
- checkout:
- cart:
- product-catalog:
- payment:
- currency:
- shipping:
- frontend-proxy:
- quote:

Graceful shutdown:
- Planned-drain result:
- Abrupt-loss limitation:
- Connection timeout/retry result:

HPA/capacity:
- frontend-proxy:
- frontend:
- product-catalog:
- cart:
- checkout:
- payment:
- currency:
- shipping:
- quote:
- NodePool limit:
- Node provisioning time:

Rehearsal:
- Drill ID:
- AZ:
- Fault type:
- Replacement ready:
- App RTO:
- SLO:
- Orders:
- Limitation:

Sudden-AZ:
- Drill ID:
- Mentor-selected AZ:
- Fault timestamp:
- SLO dip:
- Endpoint evacuation:
- Replacement creation:
- NodeClaim:
- Node Ready:
- Pod Ready:
- HPA scale:
- SLO recovery:
- Application RTO:
- Fault-to-recovery:
- Stable window:
- Missing acknowledged orders:
- Duplicates:

Contribution to PM-159:
- App layer:
- Infrastructure/store layer:
- Total:
- Dominant stage:

Evidence paths:
Rollback commits:
Residual risks:
Recommendation:
```

---

# 28. Final acceptance checklist

## Baseline

- [ ] Latest `main` recorded.
- [ ] Deployed revision recorded.
- [ ] Argo source inputs discovered.
- [ ] Render/live drift explained.
- [ ] AWS account and cluster correct.
- [ ] Mandate 20 prerequisite recorded.
- [ ] RTO/RPO commitment signed.

## Dependency closure

- [ ] Seven Jira services covered.
- [ ] frontend-proxy covered.
- [ ] quote covered.
- [ ] managed dependencies coordinated with CDO02.
- [ ] load generator independent of target AZ.

## Probes

- [ ] Readiness semantics verified for every service.
- [ ] Liveness semantics verified for every service.
- [ ] Startup behavior measured.
- [ ] TCP probe limitations documented.
- [ ] Protocol probe used only when supported.
- [ ] No dependency-based restart storm.
- [ ] False-positive soak passed.
- [ ] New Pod not receiving traffic early.

## Graceful shutdown

- [ ] preStop rendered.
- [ ] grace period rendered.
- [ ] planned Pod termination measured.
- [ ] endpoint removed before planned exit.
- [ ] in-flight planned request behavior measured.
- [ ] sudden-loss limitation explicit.
- [ ] retry/timeouts bounded.
- [ ] checkout/payment idempotency risk reviewed.

## HPA/capacity

- [ ] HPA conditions healthy.
- [ ] CPU requests valid.
- [ ] Per-service metric correlation measured.
- [ ] Surviving capacity measured.
- [ ] payment HPA decision documented.
- [ ] shipping HPA decision documented.
- [ ] quote HPA decision documented.
- [ ] max replicas not blocking recovery.
- [ ] NodePool remaining limit sufficient.
- [ ] subnet IP sufficient.
- [ ] Spot availability risk documented.
- [ ] scale-up timestamps captured.
- [ ] scale-down stable.

## Scheduling/PDB

- [ ] Nodes span required AZs.
- [ ] Critical Pods span AZs.
- [ ] Topology selectors match.
- [ ] Hard spread does not deadlock remaining AZs.
- [ ] PDB selectors match.
- [ ] PDB status healthy.
- [ ] PDB not misrepresented as sudden-failure protection.
- [ ] Checkout Rollout/workloadRef behavior verified.

## Rehearsal

- [ ] Load stable before rehearsal.
- [ ] Target AZ/nodes recorded.
- [ ] Cordon/drain performed safely.
- [ ] Replacement automatic.
- [ ] Replacement lands remaining AZ.
- [ ] SLO measured.
- [ ] Orders reconciled.
- [ ] Recovery/un-cordon complete.
- [ ] Rehearsal labeled planned, not final.

## Sudden-AZ acceptance

- [ ] Mentor/CDO02 selected AZ unexpectedly.
- [ ] Fault abrupt, no graceful drain.
- [ ] Failed AZ unavailable during observation.
- [ ] Load remained active.
- [ ] T0–T16 captured.
- [ ] Endpoint evacuation measured.
- [ ] Replacement creation measured.
- [ ] Scheduler time measured.
- [ ] Karpenter time measured if used.
- [ ] Pod readiness measured.
- [ ] HPA reaction measured if used.
- [ ] Application RTO within commitment.
- [ ] SLO recovery stable.
- [ ] Zero acknowledged order loss.
- [ ] No unexplained duplicates.
- [ ] No manual app scale/restart.
- [ ] Post-recovery soak passed.

## Evidence

- [ ] Raw load output present.
- [ ] Raw Kubernetes timeline present.
- [ ] PromQL committed.
- [ ] RTO analyzer reproducible.
- [ ] Order reconciliation reproducible.
- [ ] Evidence manifest complete.
- [ ] Important files hashed.
- [ ] No secrets committed.
- [ ] Reviewer reproduction guide works.
- [ ] Contribution to total RTO documented.
- [ ] Full Mandate 21 residual dependency stated.

---

# 29. Recommended implementation order

```text
Latest-main baseline
→ Argo/render inventory
→ dependency closure
→ probe semantics benchmark
→ surviving-capacity model
→ HPA/Karpenter cold test
→ small evidence-backed config PRs
→ planned AZ evacuation rehearsal
→ fix measured blockers
→ coordinated sudden-AZ mentor drill
→ order reconciliation
→ application/total RTO decomposition
→ evidence closure.
```

---

# 30. Final review position

This task must be reviewed against the following statements:

1. A readiness probe does not detect a dead Availability Zone.
2. HPA does not reschedule replicas lost with a node.
3. PDB does not protect against involuntary AZ failure.
4. `preStop` may not execute during abrupt node loss.
5. Two replicas can preserve availability but may not preserve capacity.
6. A 60-second HPA policy window is not identical to a 60-second reaction delay.
7. A planned drain is necessary rehearsal but not final Mandate 21 proof.
8. The real checkout dependency closure includes more than the seven service names in Jira.
9. Application RTO must be separated from datastore/network RTO.
10. Zero data loss must be proven with acknowledged order IDs.
11. Recovery must be automatic during final drill.
12. Any production change must be justified by before/after evidence.

A review that cannot verify these twelve statements from the final implementation and evidence should not approve closure.
