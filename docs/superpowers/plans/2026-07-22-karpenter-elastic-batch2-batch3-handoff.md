# Karpenter Elastic Batch 2 And Batch 3 Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chuyển an toàn bốn backend replicated ở batch 2 và bốn workload critical ở batch 3 sang lớp Karpenter elastic, giữ mỗi service trên ít nhất hai hostname và hai AZ, không làm checkout vi phạm SLO hoặc làm gián đoạn telemetry.

**Architecture:** Managed Node Group On-Demand tiếp tục giữ platform, stateful và singleton. Hai Karpenter NodePool dùng chung scheduling contract `techx.io/workload=elastic`: Spot weight `100` là lựa chọn chính, On-Demand fallback weight `10` và bị giới hạn `4 vCPU/16Gi/2 node`. Mỗi batch là một PR riêng; auto-sync chỉ được phép rollout batch sau khi batch trước đạt đủ placement, readiness, SLO và soak gate.

**Tech Stack:** AWS EKS 1.35, Kubernetes topology spread/PDB/HPA, Karpenter 1.14.0, Helm, Argo CD, Argo Rollouts, Prometheus, Grafana, Jaeger.

**Availability objective:** Quy trình được thiết kế để giữ endpoint Ready trong lúc thay pod và rollback sớm khi gate xấu. Không tuyên bố xác suất downtime tuyệt đối `0%`; chỉ được tiếp tục khi bằng chứng live chứng minh capacity, placement, PDB, canary, SLO và telemetry đều đạt.

## Global Constraints

- AWS account phải là `197826770971`, region `ap-southeast-1`, cluster `techx-corp-tf3`, namespace `techx-tf3`.
- Không sửa, vô hiệu hóa hoặc bypass `flagd`, OpenFeature hooks, `/flagservice` hay `envoy.filters.http.fault`.
- Không đưa platform Deployment/StatefulSet, stateful workload hoặc singleton lên elastic capacity trong hai batch này. DaemonSet hệ thống vẫn chạy trên mọi node theo thiết kế; `otel-gateway` là ngoại lệ stateless, replicated và được kiểm chứng riêng ở batch 3.
- Không merge batch 2 và batch 3 trong cùng PR.
- Không merge batch 3 trước khi batch 2 soak tối thiểu 30 phút và mọi gate đều xanh.
- Mọi elastic workload phải có ít nhất hai Ready replica, PDB `ALLOWED DISRUPTIONS >= 1`, hard spread trên hai hostname và hai AZ.
- Mọi hostname/AZ topology constraint phải có `maxSkew: 1`, `minDomains: 2`, `whenUnsatisfiable: DoNotSchedule`.
- Giữ nguyên image, resources, HPA bounds, probes, graceful shutdown, `maxUnavailable: 0` và `maxSurge: 1`.
- Checkout success phải `>=99%`; browse/cart success phải `>=99.5%`; frontend p95 phải `<1000ms`; mọi query phải có traffic khác 0.
- Dừng ngay khi có pod cũ mất readiness trước khi pod thay thế Ready, replica co-locate cùng hostname/AZ, PDB `ALLOWED=0`, restart/OOM, Argo `Degraded`, hoặc SLO vi phạm.
- Không drain/delete node, scale thủ công hoặc chỉnh NodePool live để ép rollout đi tiếp.
- Khi rollback khẩn cấp, pin `techx-corp` về revision trước merge và tắt auto-sync chỉ sau khi có quyền production mutation; sau đó bắt buộc tạo revert PR và khôi phục `main + auto-sync`.

## Handoff Baseline

Snapshot live ngày `2026-07-22` sau PR `#319`, revision `a2b4dcfb9e4dedcefd3288adc4f810736286478e`:

| Gate | Live result |
|---|---|
| Argo | `techx-corp` và `karpenter-nodepool` đều `Synced/Healthy` |
| Spot NodePool | `flash-sale-spot`: 2 node `t3.medium`, weight 100, Ready |
| Fallback NodePool | `elastic-ondemand-fallback`: 0 node, weight 10, Ready |
| Failure domains | Spot node ở `ap-southeast-1a` và `ap-southeast-1c` |
| Batch 1 | `currency`, `quote`, `shipping`: mỗi service một replica ở `1a`, một replica ở `1c` |
| Spot CPU request | Khoảng `280m/14%` trên mỗi node |
| Pending | 0 |
| Batch 2 readiness | `product-catalog`, `product-reviews`, `cart`, `payment`: đều `2/2` |
| Batch 3 readiness | `frontend`, `frontend-proxy`, `otel-gateway`: `2/2`; `checkout-rollout`: Healthy `2/2` |
| PDB | Tất cả workload batch 2/3 có `minAvailable: 1`, live `ALLOWED DISRUPTIONS=1` |

Sự cố cần nhớ: PR `#317` chỉ thêm selector/toleration nhưng giữ hostname spread mềm và thiếu `minDomains`; Kubernetes coi một elastic AZ là đủ và đặt cả hai replica của ba service lên cùng một Spot node. PR `#318` đã rollback. PR `#319` sửa bằng hard spread + `minDomains: 2` và đã chứng minh Karpenter tạo node thứ hai ở AZ khác.

## File Map

- Modify `phase3 - information/deploy/values-prod.yaml`: scheduling contract cho batch 2 và batch 3; thêm `otelGateway.schedulingRules`.
- Modify `phase3 - information/techx-corp-chart/templates/otel-gateway.yaml`: render node selector, tolerations và topology spread cho custom OTEL gateway Deployment.
- Read `gitops/infrastructure/pdb-checkout.yaml`: PDB của application path.
- Read `gitops/infrastructure/pdb-otel-gateway.yaml`: PDB của OTEL gateway.
- Read `gitops/infrastructure/hpa-hotpath.yaml`: min/max replicas của HPA.
- Read `gitops/karpenter/spot-nodepool.yaml`: Spot limits, taint, disruption freeze.
- Read `gitops/karpenter/ondemand-fallback-nodepool.yaml`: fallback limits và weight.
- Update this file after each batch with merge SHA, node placement, SLO values và rollback decision.

---

### Task 1: Take Over And Revalidate The Baseline

**Files:**
- Read: `docs/superpowers/plans/2026-07-22-karpenter-elastic-batch2-batch3-handoff.md`
- Read: `phase3 - information/deploy/values-prod.yaml`

**Interfaces:**
- Consumes: merged PR `#319` and current live cluster state.
- Produces: a timestamped GO/NO-GO decision and `PRE_BATCH2_MAIN` rollback revision.

- [ ] **Step 1: Create a clean worktree from newest main**

```bash
git fetch origin main
git worktree add .worktrees/karpenter-elastic-batch2 \
  -b fix/karpenter-elastic-placement-batch2 origin/main
cd .worktrees/karpenter-elastic-batch2
export PRE_BATCH2_MAIN=$(git rev-parse origin/main)
echo "$PRE_BATCH2_MAIN"
```

Expected: worktree clean; `PRE_BATCH2_MAIN` includes PR `#319` or a later reviewed revision.

- [ ] **Step 2: Verify identity, GitOps and capacity**

```bash
aws sts get-caller-identity --query '{Arn:Arn,Account:Account}' --output json
kubectl -n argocd get application techx-corp karpenter-nodepool \
  -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,REVISION:.status.sync.revision'
kubectl get nodepool,nodeclaim -o wide
kubectl get pods -A --field-selector=status.phase=Pending -o wide
```

Expected: account `197826770971`; both Argo apps `Synced/Healthy`; both NodePools `Ready=True`; no Pending pod.

- [ ] **Step 3: Verify batch 1 is still split over two failure domains**

```bash
kubectl -n techx-tf3 get pods \
  -l 'opentelemetry.io/name in (currency,quote,shipping)' \
  -o custom-columns='NAME:.metadata.name,READY:.status.containerStatuses[*].ready,NODE:.spec.nodeName,ZONE:.metadata.labels.topology\.kubernetes\.io/zone'
kubectl -n techx-tf3 get pdb currency-pdb quote-pdb shipping-pdb
```

Expected: exactly two Ready pods per service; each pair uses two hostnames and at least two AZs; each PDB `ALLOWED DISRUPTIONS >= 1`.

- [ ] **Step 4: Verify batch 2 and batch 3 starting readiness**

```bash
kubectl -n techx-tf3 get deploy \
  product-catalog product-reviews cart payment \
  frontend frontend-proxy otel-gateway
kubectl -n techx-tf3 get rollout checkout-rollout
kubectl -n techx-tf3 get pdb \
  product-catalog-pdb product-reviews-pdb cart-pdb payment-pdb \
  frontend-pdb frontend-proxy-pdb checkout-pdb otel-gateway-pdb
```

Expected: every Deployment `2/2`; checkout Rollout `Healthy 2/2`; every PDB `ALLOWED DISRUPTIONS >= 1`.

- [ ] **Step 5: Record baseline SLO with non-zero traffic**

Open Prometheus locally:

```bash
kubectl -n techx-tf3 port-forward service/prometheus 19090:9090
```

Use Grafana `slo-dashboard` or Prometheus with a 5-minute and 15-minute window. Record:

```text
checkout PlaceOrder success >= 0.99
browse success >= 0.995
cart success >= 0.995
frontend p95 < 1000ms
checkout request rate > 0
```

Expected: all thresholds pass. Empty/no-data is a failed gate, not a pass.

- [ ] **Step 6: Stop on any failed baseline gate**

Do not edit or merge anything until the existing incident/drift is explained and cleared. Record the failing command and observed result in this document.

---

### Task 2: Implement Batch 2 Placement

**Files:**
- Modify: `phase3 - information/deploy/values-prod.yaml`
- Read: `gitops/infrastructure/pdb-checkout.yaml`
- Read: `gitops/infrastructure/hpa-hotpath.yaml`

**Interfaces:**
- Consumes: green Task 1 baseline and existing generic chart support for `schedulingRules`.
- Produces: rendered elastic scheduling for exactly `product-catalog`, `product-reviews`, `cart`, `payment` in addition to batch 1.

- [ ] **Step 1: Add the scheduling contract to exactly four components**

Under each component's existing `schedulingRules` block, add:

```yaml
nodeSelector:
  techx.io/workload: elastic
tolerations:
  - key: techx.io/workload
    operator: Equal
    value: elastic
    effect: NoSchedule
```

Components:

```text
components.product-catalog
components.product-reviews
components.cart
components.payment
```

- [ ] **Step 2: Harden both spread constraints for each component**

The complete scheduling shape below uses `product-catalog`. Apply the identical shape under `components.product-reviews`, `components.cart` and `components.payment`, setting both selector values to the component's exact name:

```yaml
schedulingRules:
  nodeSelector:
    techx.io/workload: elastic
  tolerations:
    - key: techx.io/workload
      operator: Equal
      value: elastic
      effect: NoSchedule
  topologySpreadConstraints:
    - maxSkew: 1
      minDomains: 2
      topologyKey: kubernetes.io/hostname
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          opentelemetry.io/name: product-catalog
    - maxSkew: 1
      minDomains: 2
      topologyKey: topology.kubernetes.io/zone
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          opentelemetry.io/name: product-catalog
```

The exact selector pairs are `product-catalog/product-catalog`, `product-reviews/product-reviews`, `cart/cart` and `payment/payment`. Do not copy the old `ScheduleAnyway` hostname rule.

- [ ] **Step 3: Confirm the diff changes scheduling only**

```bash
git diff -- 'phase3 - information/deploy/values-prod.yaml'
git diff --check
```

Expected: no image, digest, resources, HPA, replica, probe, strategy, environment or flagd change.

- [ ] **Step 4: Commit batch 2 atomically**

```bash
git add 'phase3 - information/deploy/values-prod.yaml'
git commit -m 'fix: place second stateless batch on elastic capacity'
```

---

### Task 3: Validate, Deliver And Roll Out Batch 2

**Files:**
- Test: rendered Helm manifests in `/tmp/techx-elastic-batch2.yaml`
- Update: `docs/superpowers/plans/2026-07-22-karpenter-elastic-batch2-batch3-handoff.md`

**Interfaces:**
- Consumes: Task 2 commit.
- Produces: merged batch 2 PR plus a 30-minute green soak record required by batch 3.

- [ ] **Step 1: Build dependencies and render exact Argo inputs**

```bash
helm dependency build 'phase3 - information/techx-corp-chart'

HELM_ARGS=(
  -f 'phase3 - information/deploy/values-flagd-sync.yaml'
  -f 'phase3 - information/deploy/values-prod.yaml'
  -f 'phase3 - information/deploy/values-aio-llm.yaml'
  --set default.image.repository=197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp
  --set default.image.tag=58b13f2
  --set components.frontend-proxy.ingress.enabled=false
)

helm lint 'phase3 - information/techx-corp-chart' "${HELM_ARGS[@]}"
helm template techx-corp 'phase3 - information/techx-corp-chart' \
  -n techx-tf3 "${HELM_ARGS[@]}" > /tmp/techx-elastic-batch2.yaml
```

Expected: lint exits 0 and render succeeds.

- [ ] **Step 2: Assert the exact elastic workload set**

```bash
yq -r '
  select(.kind == "Deployment") |
  select(.spec.template.spec.nodeSelector["techx.io/workload"] == "elastic") |
  .metadata.name
' /tmp/techx-elastic-batch2.yaml | sort
```

Expected exactly:

```text
cart
currency
payment
product-catalog
product-reviews
quote
shipping
```

- [ ] **Step 3: Assert hard multi-domain fields and server schema**

```bash
yq -c '
  select(.kind == "Deployment") |
  select(.metadata.name == "product-catalog" or
         .metadata.name == "product-reviews" or
         .metadata.name == "cart" or
         .metadata.name == "payment") |
  {name: .metadata.name,
   spread: [.spec.template.spec.topologySpreadConstraints[] |
     {topologyKey, whenUnsatisfiable, minDomains, maxSkew}]}
' /tmp/techx-elastic-batch2.yaml

yq -y '
  select(.kind == "Deployment") |
  select(.metadata.name == "product-catalog" or
         .metadata.name == "product-reviews" or
         .metadata.name == "cart" or
         .metadata.name == "payment")
' /tmp/techx-elastic-batch2.yaml > /tmp/techx-elastic-batch2-deployments.yaml

kubectl apply --dry-run=server -f /tmp/techx-elastic-batch2-deployments.yaml
```

Expected: every workload has two constraints with `minDomains=2`, `DoNotSchedule`, `maxSkew=1`; server dry-run exits 0.

- [ ] **Step 4: Push and create one batch 2 PR**

```bash
git push -u origin fix/karpenter-elastic-placement-batch2
gh pr create --base main \
  --head fix/karpenter-elastic-placement-batch2 \
  --title 'fix: place second stateless batch on elastic capacity' \
  --body-file /tmp/batch2-pr-body.md
```

PR body must list the seven expected elastic workloads, Helm/server dry-run evidence, baseline revision and rollback revision `PRE_BATCH2_MAIN`.

- [ ] **Step 5: Merge only when PR checks and live preflight pass**

Immediately before merge, rerun Task 1 Steps 2-5. Merge only when no unrelated commit changed `values-prod.yaml` after branch creation.

- [ ] **Step 6: Observe Argo and rollout without manual node operations**

```bash
kubectl -n argocd get application techx-corp -w
kubectl -n techx-tf3 rollout status deploy/product-catalog --timeout=5m
kubectl -n techx-tf3 rollout status deploy/product-reviews --timeout=5m
kubectl -n techx-tf3 rollout status deploy/cart --timeout=5m
kubectl -n techx-tf3 rollout status deploy/payment --timeout=5m
kubectl get nodeclaim -o wide
kubectl get pods -A --field-selector=status.phase=Pending -o wide
```

Expected: old managed replicas remain Ready until elastic replacements are Ready; Karpenter may reuse the two existing Spot nodes; no fallback node is required unless Spot offerings are unavailable.

- [ ] **Step 7: Prove placement, PDB and platform isolation**

```bash
kubectl -n techx-tf3 get pods \
  -l 'opentelemetry.io/name in (product-catalog,product-reviews,cart,payment)' \
  -o custom-columns='NAME:.metadata.name,READY:.status.containerStatuses[*].ready,NODE:.spec.nodeName,ZONE:.metadata.labels.topology\.kubernetes\.io/zone'
kubectl -n techx-tf3 get pdb \
  product-catalog-pdb product-reviews-pdb cart-pdb payment-pdb
for node in $(kubectl get nodes -l techx.io/workload=elastic -o name | cut -d/ -f2); do
  echo "=== $node ==="
  kubectl get pods -A -o wide --field-selector "spec.nodeName=$node"
done
```

Expected: each service is split across at least two hostnames and two AZs; PDB `ALLOWED>=1`; elastic nodes contain only the approved stateless workload set plus DaemonSets.

- [ ] **Step 8: Soak for 30 minutes**

Every 5 minutes record:

```bash
kubectl -n argocd get application techx-corp
kubectl get nodeclaim -o wide
kubectl get pods -A --field-selector=status.phase=Pending
kubectl -n techx-tf3 get deploy product-catalog product-reviews cart payment
kubectl -n techx-tf3 get events --field-selector=type=Warning --sort-by=.lastTimestamp | tail -n 30
```

Record checkout/browse/cart success, frontend p95 and request rate at the beginning, midpoint and end. Any threshold violation blocks batch 3.

---

### Task 4: Implement Batch 3 Application Placement

**Files:**
- Modify: `phase3 - information/deploy/values-prod.yaml`
- Read: `phase3 - information/techx-corp-chart/templates/checkout-analysis-template.yaml`
- Read: `gitops/infrastructure/pdb-checkout.yaml`

**Interfaces:**
- Consumes: merged batch 2 with a documented 30-minute green soak.
- Produces: elastic scheduling for `frontend`, `frontend-proxy`, `checkout` while preserving checkout canary behavior.

- [ ] **Step 1: Create a fresh batch 3 worktree after batch 2**

```bash
cd /home/tutruong/project/Phase3-TF3-Infra-Sentinel
git fetch origin main
git worktree add .worktrees/karpenter-elastic-batch3 \
  -b fix/karpenter-elastic-placement-batch3 origin/main
cd .worktrees/karpenter-elastic-batch3
export PRE_BATCH3_MAIN=$(git rev-parse origin/main)
```

- [ ] **Step 2: Add the proven scheduling shape to three components**

Apply the complete Task 2 Step 2 scheduling shape, with exact component labels, to:

```text
components.frontend
components.frontend-proxy
components.checkout
```

Do not change checkout image, workloadRef, canary steps, AnalysisTemplate, HPA, Service selector or fault-injection integration.

- [ ] **Step 3: Confirm checkout canary remains unchanged**

```bash
git diff -- 'phase3 - information/deploy/values-prod.yaml'
git diff -- 'phase3 - information/techx-corp-chart/templates/checkout-analysis-template.yaml'
```

Expected: only scheduling fields differ; AnalysisTemplate diff is empty.

---

### Task 5: Implement OTEL Gateway Placement

**Files:**
- Modify: `phase3 - information/deploy/values-prod.yaml`
- Modify: `phase3 - information/techx-corp-chart/templates/otel-gateway.yaml`
- Read: `gitops/infrastructure/pdb-otel-gateway.yaml`

**Interfaces:**
- Consumes: the same elastic scheduling contract as application workloads.
- Produces: an OTEL gateway Deployment that renders placement fields without changing telemetry config or service endpoints.

- [ ] **Step 1: Add OTEL gateway scheduling values**

Under the existing top-level `otelGateway` block in `values-prod.yaml`, add:

```yaml
schedulingRules:
  nodeSelector:
    techx.io/workload: elastic
  tolerations:
    - key: techx.io/workload
      operator: Equal
      value: elastic
      effect: NoSchedule
  topologySpreadConstraints:
    - maxSkew: 1
      minDomains: 2
      topologyKey: kubernetes.io/hostname
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          opentelemetry.io/name: otel-gateway
    - maxSkew: 1
      minDomains: 2
      topologyKey: topology.kubernetes.io/zone
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          opentelemetry.io/name: otel-gateway
```

- [ ] **Step 2: Render optional scheduling fields in the custom template**

In `templates/otel-gateway.yaml`, immediately after pod `securityContext` and before the existing `affinity`, add:

```yaml
{{- with $gateway.schedulingRules.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
{{- end }}
{{- with $gateway.schedulingRules.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
{{- end }}
{{- with $gateway.schedulingRules.topologySpreadConstraints }}
      topologySpreadConstraints:
        {{- toYaml . | nindent 8 }}
{{- end }}
```

Keep the existing preferred pod anti-affinity, `maxUnavailable: 0`, `maxSurge: 1`, two replicas, readiness/liveness probes, Service, ConfigMap and 45-second termination grace unchanged.

- [ ] **Step 3: Confirm OTEL config and Service are untouched**

```bash
git diff -- 'phase3 - information/techx-corp-chart/templates/otel-gateway.yaml'
```

Expected: only pod scheduling rendering is added; no collector receiver/processor/exporter, port, Service selector or ConfigMap change.

- [ ] **Step 4: Commit batch 3 atomically**

```bash
git add \
  'phase3 - information/deploy/values-prod.yaml' \
  'phase3 - information/techx-corp-chart/templates/otel-gateway.yaml'
git commit -m 'fix: place critical stateless workloads on elastic capacity'
```

---

### Task 6: Validate And Deliver Batch 3

**Files:**
- Test: `/tmp/techx-elastic-batch3.yaml`
- Update: `docs/superpowers/plans/2026-07-22-karpenter-elastic-batch2-batch3-handoff.md`

**Interfaces:**
- Consumes: Tasks 4-5 commit.
- Produces: one reviewable batch 3 PR with exact render and rollback evidence.

- [ ] **Step 1: Run the exact Helm build/lint/template commands from Task 3**

Render to `/tmp/techx-elastic-batch3.yaml` using all three Argo value files and the three Argo parameters. Expected: lint and render exit 0.

- [ ] **Step 2: Assert exactly eleven elastic Deployments**

```bash
yq -r '
  select(.kind == "Deployment") |
  select(.spec.template.spec.nodeSelector["techx.io/workload"] == "elastic") |
  .metadata.name
' /tmp/techx-elastic-batch3.yaml | sort
```

Expected exactly:

```text
cart
checkout
currency
frontend
frontend-proxy
otel-gateway
payment
product-catalog
product-reviews
quote
shipping
```

- [ ] **Step 3: Assert every elastic Deployment has hard two-domain spread**

```bash
yq -r '
  select(.kind == "Deployment") |
  select(.spec.template.spec.nodeSelector["techx.io/workload"] == "elastic") |
  [.metadata.name,
   ([.spec.template.spec.topologySpreadConstraints[] |
      select(.minDomains == 2 and
             .maxSkew == 1 and
             .whenUnsatisfiable == "DoNotSchedule")] | length)] |
  @tsv
' /tmp/techx-elastic-batch3.yaml
```

Expected: every line ends with `2`.

- [ ] **Step 4: Server-side dry-run only the four batch 3 Deployments**

```bash
yq -y '
  select(.kind == "Deployment") |
  select(.metadata.name == "frontend" or
         .metadata.name == "frontend-proxy" or
         .metadata.name == "checkout" or
         .metadata.name == "otel-gateway")
' /tmp/techx-elastic-batch3.yaml > /tmp/techx-elastic-batch3-deployments.yaml

kubectl apply --dry-run=server -f /tmp/techx-elastic-batch3-deployments.yaml
```

Expected: all four resources pass API/admission validation.

- [ ] **Step 5: Push and create one batch 3 PR**

The PR body must include batch 2 soak evidence, `PRE_BATCH3_MAIN`, exact eleven-workload assertion, checkout canary gate, OTEL continuity gate and rollback commands.

---

### Task 7: Roll Out Batch 3 Under Canary And Telemetry Gates

**Files:**
- Read: `docs/runbooks/checkout-argo-rollouts-canary.md`
- Read: `phase3 - information/techx-corp-chart/templates/checkout-analysis-template.yaml`
- Update: `docs/superpowers/plans/2026-07-22-karpenter-elastic-batch2-batch3-handoff.md`

**Interfaces:**
- Consumes: approved batch 3 PR and green batch 2 soak.
- Produces: eleven elastic workloads with checkout canary and telemetry continuity proven.

- [ ] **Step 1: Verify no active checkout rollout before merge**

```bash
kubectl -n techx-tf3 get rollout checkout-rollout
kubectl -n techx-tf3 get analysisrun --sort-by=.metadata.creationTimestamp | tail -n 5
kubectl -n argocd get application techx-corp
```

Expected: Rollout `Healthy`, stable hash equals current hash, no Running AnalysisRun, Argo `Synced/Healthy`.

- [ ] **Step 2: Merge and let Argo auto-sync**

Do not disable auto-sync or manually patch workload resources during a normal rollout. Record the merge SHA and Argo revision.

- [ ] **Step 3: Monitor frontend, proxy and OTEL gateway rolling updates**

```bash
kubectl -n techx-tf3 rollout status deploy/frontend --timeout=5m
kubectl -n techx-tf3 rollout status deploy/frontend-proxy --timeout=5m
kubectl -n techx-tf3 rollout status deploy/otel-gateway --timeout=5m
kubectl -n techx-tf3 get endpointslice \
  -l 'kubernetes.io/service-name in (frontend,frontend-proxy,otel-gateway)'
```

Expected: desired Ready endpoints never reach 0; no restart/OOM; every workload splits over at least two hostname/AZ domains.

- [ ] **Step 4: Let checkout canary complete both analysis gates**

```bash
watch kubectl -n techx-tf3 get rollout checkout-rollout
kubectl -n techx-tf3 get analysisrun -w
```

Expected canary sequence:

```text
20% -> AnalysisRun (3 measurements, interval 2m) -> pause 5m
50% -> AnalysisRun (3 measurements, interval 2m) -> pause 5m
100% -> Healthy
```

Required metrics:

```text
checkout-request-rate >= 0.05
checkout-canary-success-rate >= 0.990
checkout-success-rate-regression-vs-stable <= 0.005
checkout-canary-p95-latency-ms <= 1000
checkout-p95-regression-vs-stable-ms <= 100
```

Do not `promote --full` and do not skip a failed/error AnalysisRun. A Prometheus timeout is a failed observability gate even if application pods are Ready.

- [ ] **Step 5: Prove telemetry continuity**

```bash
kubectl -n techx-tf3 get deploy otel-gateway
kubectl -n techx-tf3 get endpointslice -l kubernetes.io/service-name=otel-gateway
kubectl -n techx-tf3 logs \
  -l app.kubernetes.io/name=otel-gateway \
  --all-containers=true --prefix=true --since=20m \
  | rg -i 'export.*failed|context deadline|refused|dropped' || true
```

Prometheus must show non-zero recent `traces_span_metrics_calls_total` and no unexplained gap spanning the rollout. Jaeger must show traces newer than the batch 3 merge time. Do not call telemetry safe from pod readiness alone.

- [ ] **Step 6: Prove final placement and platform isolation**

```bash
kubectl -n techx-tf3 get pods -o wide
kubectl get nodeclaim -o wide
kubectl get pods -A --field-selector=status.phase=Pending -o wide
kubectl -n techx-tf3 get pdb
```

Expected: all eleven elastic workloads have Ready replicas split across at least two hostname/AZ domains; no unapproved platform Deployment/StatefulSet, stateful workload or singleton uses an elastic node; only expected DaemonSets are exempt. Fallback usage, if any, is recorded with node count and estimated duration/cost.

- [ ] **Step 7: Soak for 30 minutes after checkout becomes Healthy**

Record SLO and placement every 5 minutes. Batch 3 completes only after 30 uninterrupted minutes with all gates green.

---

### Task 8: Rollback Procedure For Either Batch

**Files:**
- Create only when needed: a dedicated revert branch and PR.

**Interfaces:**
- Consumes: `PRE_BATCH2_MAIN` or `PRE_BATCH3_MAIN`, failed batch PR number and explicit production mutation authority.
- Produces: restored previous placement, reconciled `main`, restored auto-sync and incident evidence.

- [ ] **Step 1: Trigger rollback immediately on a hard failure**

Hard failures include co-location of a replica pair, old Ready endpoints dropping before replacements, SLO violation, checkout AnalysisRun failure/error, telemetry gap, OOM/restart, or Pending without a progressing NodeClaim.

- [ ] **Step 2: Use revision pinning only for emergency containment**

With explicit production approval, pin `techx-corp` to `PRE_BATCH2_MAIN` when batch 2 fails or `PRE_BATCH3_MAIN` when batch 3 fails. Keep auto-sync enabled until Argo reaches the pinned revision so the full application returns to the exact pre-batch state; then disable auto-sync to prevent the app-of-apps path from racing the Git revert. Do not delete pods/nodes manually.

For batch 2, use `PRE_BATCH2_MAIN`; for batch 3, use `PRE_BATCH3_MAIN`:

```bash
export ROLLBACK_REVISION="$PRE_BATCH2_MAIN"
kubectl -n argocd patch application techx-corp --type merge -p \
  "{\"spec\":{\"source\":{\"targetRevision\":\"${ROLLBACK_REVISION}\"}}}"
kubectl -n argocd annotate application techx-corp \
  argocd.argoproj.io/refresh=hard --overwrite

until [ "$(kubectl -n argocd get application techx-corp \
  -o jsonpath='{.status.sync.revision}')" = "$ROLLBACK_REVISION" ] && \
  [ "$(kubectl -n argocd get application techx-corp \
  -o jsonpath='{.status.sync.status}')" = "Synced" ]; do
  kubectl -n argocd get application techx-corp
  sleep 10
done

kubectl -n argocd patch application techx-corp --type merge -p \
  '{"spec":{"syncPolicy":{"automated":null}}}'
```

Expected: Argo reports the exact rollback revision and `Synced`; workload readiness/SLO recover before Git reconciliation begins. If Argo becomes `Degraded`, stop and escalate rather than deleting pods or nodes.

- [ ] **Step 3: Create the Git revert immediately**

```bash
read -r -p 'Failed batch PR number: ' FAILED_BATCH_PR
FAILED_MERGE_SHA=$(gh pr view "$FAILED_BATCH_PR" \
  --json mergeCommit --jq '.mergeCommit.oid')
export REVERT_BRANCH="revert/karpenter-elastic-batch-${FAILED_BATCH_PR}"
git fetch origin main
git worktree add ".worktrees/revert-elastic-batch-${FAILED_BATCH_PR}" \
  -b "$REVERT_BRANCH" origin/main
cd ".worktrees/revert-elastic-batch-${FAILED_BATCH_PR}"
git revert -m 1 "$FAILED_MERGE_SHA"
git push -u origin "$REVERT_BRANCH"
gh pr create --base main \
  --head "$REVERT_BRANCH" \
  --title 'revert: restore workloads to previous capacity placement' \
  --body 'Emergency GitOps reconciliation for failed elastic placement rollout.'
```

Verify that `FAILED_MERGE_SHA` is the merge commit of the failed batch PR before running `git revert`. Merge through the protected branch workflow.

- [ ] **Step 4: Restore normal GitOps ownership**

After the revert PR merges:

```bash
kubectl -n argocd patch application techx-corp --type merge -p \
  '{"spec":{"source":{"targetRevision":"main"},"syncPolicy":{"automated":{"enabled":true,"prune":true,"selfHeal":true},"syncOptions":["RespectIgnoreDifferences=true"]}}}'
kubectl -n argocd annotate application techx-corp \
  argocd.argoproj.io/refresh=hard --overwrite
```

Expected: `techx-corp` returns to `Synced/Healthy` at the revert revision; auto-sync/prune/self-heal are true; no Pending pod; SLO returns above threshold.

---

### Task 9: Close The Handoff With Evidence

**Files:**
- Modify: `docs/superpowers/plans/2026-07-22-karpenter-elastic-batch2-batch3-handoff.md`

**Interfaces:**
- Consumes: final 30-minute batch 3 soak.
- Produces: auditable completion record for Mandate 13 continuation.

- [ ] **Step 1: Append the final evidence table**

Record exact values:

```markdown
| Evidence | Batch 2 | Batch 3 |
|---|---|---|
| Branch / PR / merge SHA | value | value |
| Previous rollback revision | value | value |
| Argo sync / health | value | value |
| NodePool / NodeClaim / AZ | value | value |
| Replica hostname/AZ split | value | value |
| PDB allowed disruptions | value | value |
| Pending / restart / OOM | value | value |
| Checkout success + request rate | value | value |
| Browse/cart success | value | value |
| Frontend p95 | value | value |
| Checkout AnalysisRuns | N/A | value |
| OTEL/Jaeger continuity | N/A | value |
| Fallback node duration/cost | value | value |
| Rollback required | value | value |
```

- [ ] **Step 2: Commit evidence separately**

```bash
git add docs/superpowers/plans/2026-07-22-karpenter-elastic-batch2-batch3-handoff.md
git commit -m 'docs: record elastic capacity rollout evidence'
```

- [ ] **Step 3: Stop before later Karpenter disruption work**

This handoff does not unfreeze Drifted/Underutilized disruption, remove temporary On-Demand baseline capacity, test Spot interruption, or start Graviton. Those are separate post-placement tasks and require their own live gate.
