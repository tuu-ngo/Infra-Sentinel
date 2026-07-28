# MANDATE 17 / PM-142
# RBAC Least-Privilege — SEC-01 Grafana Namespaced RBAC + SEC-02 Disable Kubernetes ServiceAccount Token Automount

## Technical Specification, Execution Plan, Render Contract, Test Matrix, Rollback và Evidence Contract

**Repository triển khai:** `tuu-ngo/Phase3-TF3-Infra-Sentinel`  
**Baseline khảo sát public:** `main@7ec4e0aaa19ec3ab55bd1bd6804a604aeb9c0d94`  
**Baseline bắt buộc khi thực thi:** latest `origin/main` tại thời điểm tạo branch; ghi lại bằng `git rev-parse HEAD`  
**Cluster:** `techx-corp-tf3`  
**Namespace sản phẩm:** `techx-tf3`  
**Argo CD Application:** `techx-corp`  
**Helm chart:** `phase3 - information/techx-corp-chart`  
**Grafana dependency tại baseline:** chart `12.3.0`  
**Task owner:** Lê Hoàng Việt  
**Task liên quan:** PM-142, SEC-01, SEC-02, Mandate 17 requirement #4  
**Due date Jira:** 21/07/2026  
**Mức ưu tiên:** cao  
**Trạng thái tài liệu:** đặc tả triển khai; **không phải bằng chứng production đã hoàn thành**

---

# 0. Kết luận điều tra hiện trạng

## 0.1. Những gì audit cũ đã xác nhận

Tài liệu `docs/evidence/10-security-baseline-rbac.md` đã xác nhận trên live cluster:

1. ServiceAccount `techx-tf3:grafana` được bind tới `grafana-clusterrole`.
2. `grafana-clusterrole` có `get/list/watch` đối với `configmaps` và `secrets` ở phạm vi toàn cluster.
3. Impersonation test từng trả:

```text
kubectl auth can-i list secrets \
  --as=system:serviceaccount:techx-tf3:grafana \
  -n kube-system

=> yes
```

4. Các business Deployment dùng ServiceAccount chung `techx-corp` mà không khai báo `automountServiceAccountToken: false`.
5. ServiceAccount `techx-corp` tại thời điểm audit chưa có quyền đọc Kubernetes resources, nhưng token vẫn được mount không cần thiết.
6. Audit đã đề xuất:
   - Grafana `rbac.namespaced: true`;
   - tắt automount Kubernetes API token;
   - xác minh lại bằng `kubectl auth can-i`, Pod filesystem và runtime smoke test.

## 0.2. Những gì source hiện tại đang thể hiện

Tại baseline khảo sát:

1. Argo CD render application bằng đúng bốn values file, theo thứ tự:

```text
values.yaml
../deploy/values-flagd-sync.yaml
../deploy/values-prod.yaml
../deploy/values-aio-llm.yaml
```

2. Argo CD bật:

```yaml
syncPolicy:
  automated:
    prune: true
    selfHeal: true
```

3. `values-prod.yaml` có block cấu hình Grafana nhưng chưa có:

```yaml
grafana:
  rbac:
    namespaced: true
```

4. `templates/serviceaccount.yaml` chưa render trường:

```yaml
automountServiceAccountToken
```

cho cả shared ServiceAccount và component-scoped ServiceAccount.

5. `templates/_objects.tpl` render `serviceAccountName`, nhưng chưa render:

```yaml
spec:
  automountServiceAccountToken: false
```

trong Pod template.

6. `values.schema.json` chưa định nghĩa field automount tương ứng.

7. `component.yaml` hỗ trợ component-scoped ServiceAccount bằng cách merge cấu hình global với cấu hình của component.

8. `product-reviews` dùng ServiceAccount riêng:

```text
product-reviews-bedrock
```

với annotation IRSA để gọi Amazon Bedrock.

## 0.3. Hai gap chính đúng theo Jira

### Gap A — SEC-01

Grafana đang có quyền đọc Secret cluster-wide thay vì chỉ trong `techx-tf3`.

### Gap B — SEC-02

Business workloads nhận Kubernetes API credential dù không cần gọi Kubernetes API.

## 0.4. Bốn gap phụ bắt buộc phải xử lý để task không bị review lại

### Gap phụ 1 — Chỉ sửa ServiceAccount không làm Pod cũ tự thay đổi

Nếu chỉ cập nhật:

```yaml
kind: ServiceAccount
automountServiceAccountToken: false
```

các Pod đang chạy trước đó vẫn giữ projected volume đã được tạo lúc admission. DoD yêu cầu Pod sống sau fix không còn token, nên phải có một rollout có kiểm soát.

Thiết kế final của task này dùng **cả Pod-level và ServiceAccount-level false**:

- Pod-level field làm Pod template thay đổi và kích hoạt declarative rollout.
- ServiceAccount-level field là defense-in-depth cho workload mới hoặc manifest khác quên khai báo Pod-level field.

### Gap phụ 2 — Không được giả định `grafana.rbac.namespaced: true` chắc chắn không render ClusterRole

Helm chart phải được render bằng đúng chart version và đúng bốn values file. Gate chỉ pass khi output thực tế:

- có namespaced `Role` và `RoleBinding` cho Grafana;
- không còn Grafana `ClusterRole`/`ClusterRoleBinding` cấp quyền đọc Secret;
- RoleBinding trỏ đúng ServiceAccount `techx-tf3:grafana`.

Nếu chart vẫn render cluster-scoped RBAC, task phải dừng và chuyển sang phương án `existingRole` hoặc repo-managed Role/RoleBinding; không được xóa thủ công rồi để Argo tạo lại.

### Gap phụ 3 — `product-reviews` dùng IRSA

Tắt Kubernetes API token không được làm mất IRSA token dùng cho AWS STS.

Phải phân biệt:

```text
Kubernetes API token:
/var/run/secrets/kubernetes.io/serviceaccount/token

IRSA projected web-identity token:
/var/run/secrets/eks.amazonaws.com/serviceaccount/token
```

Final gate yêu cầu:

- Kubernetes API token path không tồn tại;
- IRSA token path vẫn tồn tại trong `product-reviews`;
- `AWS_ROLE_ARN` và `AWS_WEB_IDENTITY_TOKEN_FILE` vẫn được inject;
- Bedrock path vẫn hoạt động.

Không được mặc định set `automountServiceAccountToken: true` cho `product-reviews` chỉ vì nó dùng IRSA.

### Gap phụ 4 — Lệnh `kubectl exec ... ls` có thể báo sai lý do

Nhiều first-party image có thể distroless hoặc không chứa `ls`/`sh`.

Không được coi lỗi:

```text
exec: "ls": executable file not found
```

là bằng chứng token không tồn tại.

Bằng chứng chính phải dựa trên Pod spec volume/mount inventory. `kubectl exec` là evidence bổ sung khi container xác nhận có command cần thiết.

---

# 1. Mục tiêu

Sau khi hoàn thành task này:

1. Grafana chỉ có quyền `get/list/watch` `configmaps` và `secrets` trong namespace `techx-tf3`.
2. Grafana không có quyền đọc Secret ở `kube-system`, `argocd`, `kyverno` hoặc namespace khác.
3. Grafana upstream chart không còn tạo Grafana ClusterRole/ClusterRoleBinding nguy hiểm.
4. Shared ServiceAccount `techx-corp` có:

```yaml
automountServiceAccountToken: false
```

5. Mọi first-party business Pod không cần Kubernetes API có:

```yaml
spec:
  automountServiceAccountToken: false
```

6. Các Pod mới sau rollout không có `kube-api-access-*` projected volume và không mount `/var/run/secrets/kubernetes.io/serviceaccount`.
7. `product-reviews` vẫn nhận IRSA web-identity token riêng và vẫn gọi được Bedrock.
8. Grafana UI, datasource/dashboard sidecars, storefront, product browse, cart và checkout không bị hỏng.
9. Argo CD vẫn `Synced/Healthy`; không có drift do thay đổi imperative.
10. Evidence đủ để mentor tự chạy lại toàn bộ DoD.
11. Rollback nằm trong Git và đã được chuẩn bị trước cutover.

---

# 2. Phạm vi

## 2.1. In scope

- Grafana RBAC do dependency chart tạo trong release `techx-corp`.
- Helm production values.
- Shared ServiceAccount `techx-corp`.
- Component-scoped ServiceAccount rendering.
- Business Deployment Pod template rendering.
- `product-reviews-bedrock` IRSA regression test.
- Helm schema validation.
- Helm render contract tests.
- Argo CD prune/self-heal behavior.
- Controlled rollout của business Deployments.
- RBAC impersonation tests.
- Token mount inventory.
- Grafana/storefront/browse/cart/checkout/Bedrock smoke test.
- Evidence pack, ADR và rollback runbook.

## 2.2. Out of scope

- Tách một ServiceAccount riêng cho toàn bộ từng service.
- Viết RBAC Role riêng cho từng business service.
- NetworkPolicy default-deny hoặc service-to-service allow-list.
- Dependency timeout/circuit breaker/fallback.
- Full-AZ loss test.
- Toàn bộ phần resilience còn lại của Mandate 17.
- Thay đổi Grafana admin password hoặc SEC-03, trừ khi phát hiện incident.
- Upgrade Grafana dependency chart nếu `rbac.namespaced` hiện tại hoạt động đúng.
- Thay đổi Prometheus, Jaeger hoặc OpenTelemetry RBAC.
- Thay đổi IRSA IAM policy của `product-reviews`.
- Thay đổi application source code.
- Thay đổi HPA, PDB, topology spread, Argo Rollouts strategy hoặc datastore.
- Thay đổi flagd/OpenFeature/fault-injection behavior.
- Chuyển Grafana public/private ingress architecture.

## 2.3. Không được tuyên bố sau task

Không được ghi:

```text
Mandate 17 hoàn thành 100%
```

Task này chỉ đóng hai finding:

```text
SEC-01 + SEC-02
```

Full Mandate 17 còn yêu cầu:

- dependency failure containment;
- AZ failure resilience;
- NetworkPolicy containment;
- separate ServiceAccount / least-privilege RBAC đầy đủ cho từng workload;
- mentor-driven containment tests.

---

# 3. Mapping tới Mandate 17 và Jira DoD

## 3.1. Mandate 17 requirement được đóng

Requirement #4 của Mandate 17 yêu cầu giảm blast radius bằng:

- least-privilege Kubernetes RBAC;
- ServiceAccount phù hợp;
- token không được mount khi workload không cần Kubernetes API.

Task này đóng hai phần cụ thể:

| Control | Trước | Sau |
|---|---|---|
| Grafana Secret read scope | Toàn cluster | Chỉ `techx-tf3` |
| Business Pod K8s API token | Mặc định mount | Bị tắt tường minh |

## 3.2. Jira DoD mapping

| Jira DoD | Technical gate |
|---|---|
| Grafana không list Secret `kube-system` | `kubectl auth can-i ... -n kube-system` = `no` |
| Grafana vẫn list Secret `techx-tf3` | `kubectl auth can-i ... -n techx-tf3` = `yes` |
| Checkout và service khác không có token dir | Pod spec inventory + valid exec evidence |
| Grafana/storefront hoạt động | Grafana API/UI + browse/cart/checkout smoke |

---

# 4. Security invariants

## 4.1. Grafana RBAC invariant

ServiceAccount:

```text
system:serviceaccount:techx-tf3:grafana
```

chỉ được có quyền cần thiết trong namespace `techx-tf3`.

Tối đa cho control này:

```yaml
apiGroups: [""]
resources:
  - configmaps
  - secrets
verbs:
  - get
  - list
  - watch
```

Không được có các quyền sau thông qua role khác:

```text
create
update
patch
delete
deletecollection
impersonate
bind
escalate
```

Không được có read quyền Secret ở namespace khác.

## 4.2. Business token invariant

Mọi business Pod không cần Kubernetes API phải render:

```yaml
spec:
  automountServiceAccountToken: false
```

Shared ServiceAccount cũng phải render:

```yaml
automountServiceAccountToken: false
```

## 4.3. IRSA invariant

`product-reviews` phải giữ:

```text
ServiceAccount: product-reviews-bedrock
IRSA annotation: eks.amazonaws.com/role-arn
AWS_ROLE_ARN: expected Bedrock role
AWS_WEB_IDENTITY_TOKEN_FILE: EKS web identity path
```

Kubernetes API token phải không tồn tại, nhưng IRSA projected token phải còn tồn tại.

## 4.4. GitOps invariant

Nguồn sự thật là Git.

Không dùng các thao tác sau làm final implementation:

```bash
kubectl delete clusterrole ...
kubectl patch serviceaccount ...
kubectl patch deployment ...
kubectl edit ...
helm upgrade ...
```

vì Argo CD `selfHeal/prune` sẽ reconcile theo Git.

Imperative commands chỉ được dùng cho:

- đọc trạng thái;
- test;
- emergency rollback có phê duyệt, sau đó phải reconcile Git ngay.

## 4.5. Availability invariant

Trong rollout:

- Argo application không `Degraded`;
- money path không xuống dưới SLO hiện hành;
- không có hàng loạt `CrashLoopBackOff` hoặc `ImagePullBackOff`;
- Grafana sidecar vẫn load dashboard/datasource;
- Bedrock path vẫn hoạt động;
- không có thay đổi flagd.

---

# 5. Threat model

## 5.1. SEC-01 attack path trước fix

```text
Compromise Grafana Pod
→ đọc auto-mounted Grafana SA token
→ authenticate Kubernetes API
→ list/get Secrets toàn cluster
→ đọc Secret ở kube-system / application namespaces
→ credential theft / lateral movement / monitoring compromise
```

## 5.2. SEC-01 containment sau fix

```text
Compromise Grafana Pod
→ Grafana SA token vẫn có thể tồn tại vì Grafana sidecar cần Kubernetes API
→ API access bị giới hạn bởi RoleBinding trong techx-tf3
→ kube-system/argocd/kyverno Secret access bị deny
→ blast radius bị giới hạn namespace
```

## 5.3. SEC-02 attack path trước fix

```text
Compromise bất kỳ business Pod
→ đọc /var/run/secrets/kubernetes.io/serviceaccount/token
→ Kubernetes API reconnaissance
→ chờ hoặc khai thác RBAC drift trên shared SA
→ lateral movement
```

## 5.4. SEC-02 containment sau fix

```text
Compromise business Pod
→ không có Kubernetes API token mặc định
→ không thể dùng shared SA credential từ filesystem
→ RBAC drift trong tương lai không tự cấp credential cho các Pod đã harden
```

---

# 6. Current architecture facts cần giữ nguyên

## 6.1. Authoritative production render

Phải render đúng như Argo CD:

```bash
helm dependency build "phase3 - information/techx-corp-chart"

helm template techx-corp \
  "phase3 - information/techx-corp-chart" \
  --namespace techx-tf3 \
  -f "phase3 - information/techx-corp-chart/values.yaml" \
  -f "phase3 - information/deploy/values-flagd-sync.yaml" \
  -f "phase3 - information/deploy/values-prod.yaml" \
  -f "phase3 - information/deploy/values-aio-llm.yaml" \
  > /tmp/mandate17-rendered.yaml
```

Không render thiếu `values-aio-llm.yaml`, vì file này tạo ServiceAccount riêng cho `product-reviews`.

## 6.2. Component-scoped ServiceAccount merge

`component.yaml` merge global ServiceAccount config vào component-specific config. Vì vậy thêm global:

```yaml
serviceAccount:
  automountServiceAccountToken: false
```

có thể được thừa kế bởi `product-reviews-bedrock`.

Đây là hành vi mong muốn nếu IRSA regression test pass.

## 6.3. Grafana path hiện tại

`values-prod.yaml` đặt Grafana ở hostname riêng và:

```yaml
root_url: "%(protocol)s://%(domain)s/"
serve_from_sub_path: false
```

Do đó lệnh Jira cũ:

```text
http://localhost:8080/grafana/
```

có thể không còn là endpoint authoritative.

Final evidence phải gồm:

1. internal health check qua service/port-forward;
2. private hostname hiện hành nếu người thực thi có Cloudflare Access;
3. legacy `/grafana/` chỉ test nếu route đó vẫn còn trong render/runtime.

Không sửa Grafana routing chỉ để làm cho lệnh cũ pass.

---

# 7. Critical design decisions

## 7.1. SEC-01 dùng upstream values trước, không hand-write Role ngay

Ưu tiên:

```yaml
grafana:
  rbac:
    create: true
    namespaced: true
    pspEnabled: false
```

Lý do:

- giữ ownership trong dependency chart;
- tránh duplicate Role/RoleBinding;
- Argo prune được resource cũ;
- dễ upgrade chart về sau.

Nhưng `helm template` là source of truth. Nếu chart vẫn sinh ClusterRole, không merge.

## 7.2. SEC-01 không `kubectl delete` resource cũ làm implementation

Argo CD đang bật `prune: true`.

Flow đúng:

```text
Git values đổi
→ Helm desired manifest không còn ClusterRole/CRB
→ Argo sync
→ Argo prune resource cũ
→ verify live cluster
```

Nếu Argo không prune vì ownership/annotation khác, điều tra ownership trước. Chỉ xóa thủ công khi đã xác nhận Git không còn render resource và có change approval.

## 7.3. SEC-02 dùng defense-in-depth hai tầng

Final desired state:

### ServiceAccount level

```yaml
serviceAccount:
  automountServiceAccountToken: false
```

### Pod level

```yaml
spec:
  automountServiceAccountToken: false
```

Lý do:

- Pod spec có precedence rõ ràng;
- thay Pod template để rollout declaratively;
- ServiceAccount-level bảo vệ workload khác hoặc template mới;
- không phụ thuộc vào manual restart.

## 7.4. Mặc định secure, override tường minh

Chart schema nên cho phép:

```yaml
default:
  automountServiceAccountToken: false

components:
  <component>:
    automountServiceAccountToken: true|false
```

Component override chỉ dùng khi có bằng chứng workload thực sự cần Kubernetes API token.

Task này không được thêm override `true` chỉ để né test.

## 7.5. Không nhầm Kubernetes API token với IRSA token

IRSA sử dụng projected web-identity token với audience cho AWS STS. Tắt default Kubernetes API credential không đồng nghĩa phải tắt IRSA.

Final implementation phải test thực tế, không dựa vào giả định.

## 7.6. Rollout phải staged

Thêm Pod-level field vào default có thể khiến toàn bộ business Deployment rollout trong một Argo sync.

Không merge behavior change cùng lúc với schema/template support nếu chưa render/test.

Recommended stages:

1. Chart support và test — không đổi runtime behavior.
2. SEC-01 Grafana only.
3. SEC-02 canary group.
4. SEC-02 remaining workloads.
5. Evidence closure.

## 7.7. Không dùng `ls` làm bằng chứng duy nhất

Primary evidence:

- live Pod `.spec.volumes`;
- live containers `.volumeMounts`;
- Pod-level automount field;
- ServiceAccount-level automount field.

Secondary evidence:

- filesystem command trong container có tool phù hợp.

---

# 8. Target architecture

```text
Git commit
   |
   v
Helm values/schema/templates
   |
   v
Authoritative four-values render
   |
   +------------------------------+
   |                              |
   v                              v
Grafana chart RBAC           Business Pod template
namespaced Role/Binding      automount=false
   |                              |
   v                              v
Argo CD sync + prune         Controlled rolling update
   |                              |
   v                              v
No Grafana ClusterRole       No kube-api-access volume
   |                              |
   +--------------+---------------+
                  |
                  v
Live verification
- RBAC impersonation
- token inventory
- IRSA preservation
- Grafana/storefront/money-path smoke
- Argo health
                  |
                  v
Evidence pack + rollback-ready closure
```

---

# 9. File impact map

## 9.1. Files chắc chắn cần sửa

```text
phase3 - information/techx-corp-chart/templates/serviceaccount.yaml
phase3 - information/techx-corp-chart/templates/_objects.tpl
phase3 - information/techx-corp-chart/values.schema.json
phase3 - information/techx-corp-chart/values.yaml
phase3 - information/deploy/values-prod.yaml
```

## 9.2. Files nên thêm

```text
scripts/ci/render-mandate17-rbac-inventory.py
scripts/ci/verify-mandate17-rbac-render.py
scripts/ci/verify-serviceaccount-token-mounts.py
scripts/ci/test_verify_mandate17_rbac_render.py
scripts/ci/test_verify_serviceaccount_token_mounts.py

tests/fixtures/mandate-17/
  good-namespaced-rbac.yaml
  bad-grafana-clusterrole.yaml
  good-token-disabled.yaml
  bad-token-defaulted.yaml
  good-product-reviews-irsa.yaml

docs/adr/0013-mandate-17-rbac-and-token-containment.md
docs/runbooks/mandate-17-rbac-cutover.md
docs/runbooks/mandate-17-rbac-rollback.md
docs/evidence/mandate-17/rbac/README.md
```

## 9.3. Files có thể cần sửa tùy test framework hiện hữu

```text
.github/workflows/terraform-plan.yml
.github/workflows/test-image-bump.yml
.github/workflows/<helm-validation-workflow>.yml
Makefile
```

Không tạo workflow mới nếu repo đã có Helm validation job có thể mở rộng.

## 9.4. Protected files/areas

PR không được thay đổi behavior của:

```text
flagd/OpenFeature
fault injection
HPA
Karpenter
Argo Rollouts strategy
PDB/topology spread
RDS/ElastiCache/MSK cutover
CloudFront/Cloudflare ingress
Bedrock IAM role/policy
application source code
```

CI hoặc review checklist phải flag unrelated diff.

---

# 10. SEC-01 implementation specification

## 10.1. Production values change

Trong existing `grafana:` block của `values-prod.yaml`, thêm:

```yaml
grafana:
  rbac:
    create: true
    namespaced: true
    pspEnabled: false
```

Không tạo duplicate top-level `grafana:` key.

Không xóa các setting hiện có:

```yaml
grafana.ini
sidecar.resources
resources
```

## 10.2. Render assertions

Sau render, script phải extract tất cả RBAC object liên quan Grafana:

```bash
yq -o=json -I=0 '
  select(
    (.kind == "Role") or
    (.kind == "RoleBinding") or
    (.kind == "ClusterRole") or
    (.kind == "ClusterRoleBinding")
  )
  | select(
      (.metadata.name | test("grafana"; "i")) or
      ([.metadata.labels // {} | to_entries[]? | .value] | join(" ") | test("grafana"; "i"))
    )
' /tmp/mandate17-rendered.yaml
```

Final exact conditions:

```text
Grafana Role count >= 1
Grafana RoleBinding count >= 1
Grafana Secret-reading ClusterRole count == 0
Grafana Secret-reading ClusterRoleBinding count == 0
```

## 10.3. Rule semantics assertions

Grafana Role phải:

- namespace = `techx-tf3` hoặc namespace templated đúng release namespace;
- resources gồm `configmaps`, `secrets` nếu sidecar cần;
- verbs không vượt `get`, `list`, `watch`;
- không có wildcard resources/verbs/API groups.

RoleBinding phải:

- namespace = `techx-tf3`;
- subject = `ServiceAccount/grafana` namespace `techx-tf3`;
- `roleRef.kind = Role`;
- không trỏ ClusterRole nguy hiểm.

## 10.4. Hard-stop fallback

Nếu chart `12.3.0` với `namespaced: true` vẫn render ClusterRole/ClusterRoleBinding:

### Không được làm

```text
merge values rồi kubectl delete ClusterRole
```

### Phải làm một trong các phương án đã review

#### Option A — Existing namespaced Role

Nếu chart hỗ trợ `useExistingRole`/equivalent:

1. repo quản lý Role và RoleBinding;
2. chart dùng existing Role;
3. chart không tạo ClusterRole.

#### Option B — Patch chart version

Nâng dependency tới version đã xác minh fix, trong PR riêng có:

- changelog review;
- full Helm diff;
- Grafana migration check;
- rollback chart lock.

#### Option C — Post-render/Kustomize

Chỉ dùng khi A/B không khả thi và phải có ADR. Đây là lựa chọn cuối vì tăng complexity.

## 10.5. Live RBAC verification matrix

Sau Argo sync:

```bash
SUBJECT='system:serviceaccount:techx-tf3:grafana'
```

### Expected yes trong `techx-tf3`

```bash
for verb in get list watch; do
  kubectl auth can-i "$verb" secrets \
    --as="$SUBJECT" \
    -n techx-tf3

done
```

Expected: `yes` cho các verb chart cần.

Tương tự với ConfigMap nếu sidecar dùng ConfigMap.

### Expected no ngoài namespace

```bash
for ns in kube-system argocd kyverno default; do
  for verb in get list watch; do
    kubectl auth can-i "$verb" secrets \
      --as="$SUBJECT" \
      -n "$ns"
  done
done
```

Expected: toàn bộ `no`.

### Expected no cho mutation

```bash
for verb in create update patch delete deletecollection; do
  kubectl auth can-i "$verb" secrets \
    --as="$SUBJECT" \
    -n techx-tf3

done
```

Expected: toàn bộ `no`.

### Cluster-scoped lookup

```bash
kubectl auth can-i list secrets \
  --as="$SUBJECT" \
  --all-namespaces
```

Expected: `no`.

## 10.6. Live resource cleanup assertions

```bash
kubectl get clusterrole,clusterrolebinding -o json \
  | jq '[.items[] | select(.metadata.name | test("grafana"; "i"))]'
```

Không chỉ kiểm exact tên cũ. Phải kiểm mọi Grafana cluster-scoped object có Secret read rule.

Nếu exact old objects từng tồn tại:

```bash
kubectl get clusterrole grafana-clusterrole
kubectl get clusterrolebinding grafana-clusterrolebinding
```

Expected: `NotFound` sau prune.

---

# 11. SEC-02 implementation specification

## 11.1. Schema additions

Thêm optional boolean vào `ServiceAccountConfig`:

```json
"automountServiceAccountToken": {
  "type": "boolean",
  "description": "Whether Kubernetes API credentials are automatically mounted for Pods using this ServiceAccount."
}
```

Thêm optional boolean vào default/component Pod config schema:

```json
"automountServiceAccountToken": {
  "type": "boolean",
  "description": "Pod-level ServiceAccount token automount control. Pod value takes precedence over ServiceAccount value."
}
```

Schema phải tiếp tục reject:

- string `"false"`;
- integer `0`;
- unknown misspelled field.

## 11.2. Shared ServiceAccount template

Trong shared ServiceAccount:

```yaml
{{- if hasKey .Values.serviceAccount "automountServiceAccountToken" }}
automountServiceAccountToken: {{ .Values.serviceAccount.automountServiceAccountToken }}
{{- end }}
```

Dùng `hasKey`, không dùng logic khiến boolean `false` bị coi là empty và bỏ render.

## 11.3. Component-scoped ServiceAccount template

Trong component-scoped ServiceAccount:

```yaml
{{- if hasKey .serviceAccount "automountServiceAccountToken" }}
automountServiceAccountToken: {{ .serviceAccount.automountServiceAccountToken }}
{{- end }}
```

Phải test `product-reviews-bedrock` nhận đúng giá trị merge cuối cùng.

## 11.4. Pod template

Ngay sau `serviceAccountName` trong Pod spec, render theo precedence:

```yaml
{{- if hasKey . "automountServiceAccountToken" }}
automountServiceAccountToken: {{ .automountServiceAccountToken }}
{{- else if hasKey .defaultValues "automountServiceAccountToken" }}
automountServiceAccountToken: {{ .defaultValues.automountServiceAccountToken }}
{{- end }}
```

Không dùng:

```gotemplate
{{ .automountServiceAccountToken | default false }}
```

nếu cần hỗ trợ explicit `true`, vì Helm `default` coi `false` là empty.

## 11.5. Values final state

### Shared ServiceAccount

Trong chart values:

```yaml
serviceAccount:
  create: true
  automountServiceAccountToken: false
```

Giữ nguyên:

- annotations;
- name;
- create semantics.

### Business Pod default

Trong `default:`:

```yaml
default:
  automountServiceAccountToken: false
```

Không thêm component override `true` trừ khi test chứng minh workload cần Kubernetes API.

## 11.6. Expected rendered examples

### Shared SA

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: techx-corp
automountServiceAccountToken: false
```

### Normal business Deployment

```yaml
spec:
  template:
    spec:
      serviceAccountName: techx-corp
      automountServiceAccountToken: false
```

### Product reviews SA

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: product-reviews-bedrock
  annotations:
    eks.amazonaws.com/role-arn: <existing-role>
automountServiceAccountToken: false
```

### Product reviews Pod

```yaml
spec:
  serviceAccountName: product-reviews-bedrock
  automountServiceAccountToken: false
```

EKS mutating webhook vẫn được kỳ vọng inject AWS-specific projected token; live test quyết định acceptance.

---

# 12. Render contract

## 12.1. Inventory output

Thêm script tạo JSON:

```json
{
  "serviceAccounts": [],
  "deployments": [],
  "grafanaRbac": [],
  "violations": []
}
```

Mỗi Deployment record:

```json
{
  "name": "checkout",
  "namespace": "techx-tf3",
  "serviceAccountName": "techx-corp",
  "automountServiceAccountToken": false,
  "usesIrsa": false
}
```

## 12.2. Render fail conditions

CI phải fail khi:

- Grafana cluster-scoped Secret reader tồn tại;
- Grafana Role/RoleBinding không tồn tại;
- Grafana RoleBinding subject sai namespace/name;
- Grafana Role có wildcard verb/resource;
- any first-party business Deployment thiếu Pod-level false;
- shared `techx-corp` SA thiếu SA-level false;
- component-scoped business SA thiếu expected false;
- `product-reviews-bedrock` mất IRSA annotation;
- values schema không reject type xấu;
- render thiếu một trong bốn values file;
- deployment set lệch baseline mà không được giải thích;
- PR thay đổi protected areas.

## 12.3. Exact workload count

Không hardcode `22` trong script như source of truth.

Script phải lấy workload set từ authoritative render và phân loại:

- business Deployment;
- dependency chart Deployment;
- Stateful workloads;
- external controllers.

Evidence có thể ghi “22” nếu render/live tại thời điểm test đúng là 22.

---

# 13. Controlled rollout strategy

## 13.1. Vì sao phải rollout

Pod admission quyết định projected ServiceAccount volume tại thời điểm Pod được tạo. Pod cũ không tự bỏ volume khi ServiceAccount object đổi.

Pod-level template change bảo đảm Kubernetes Deployment controller tạo ReplicaSet mới.

## 13.2. Staging groups

### Group A — canary low-risk

Chọn 2–3 service ít ảnh hưởng money path và có health probe rõ, ví dụ sau khi kiểm tra live:

```text
image-provider
quote
email
```

Không chọn cứng nếu service hiện không healthy hoặc không có replica headroom.

### Group B — supporting services

```text
ad
currency
recommendation
shipping
fraud-detection
accounting
```

### Group C — money path

```text
frontend-proxy
frontend
product-catalog
cart
payment
checkout
```

### Group D — product-reviews/IRSA

Có thể canary riêng trước hoặc sau Group A, nhưng phải có Bedrock-specific verification.

## 13.3. Cách stage trong Git

### PR support-only

- thêm schema/template support;
- không đặt default false;
- render output phải tương đương trước change.

### Canary PR

- set `automountServiceAccountToken: false` cho component canary;
- không set global false gây toàn bộ Pod rollout.

### Final PR

- set global ServiceAccount false;
- set default Pod false;
- xóa temporary per-component false vì default đã cover;
- nếu cần temporary true exception, phải có owner/expiry/issue; final DoD của task không chấp nhận unexplained exception.

## 13.4. Availability gate mỗi group

Trước chuyển group tiếp theo:

- Deployment rollout complete;
- all Pods Ready;
- no CrashLoopBackOff;
- error rate không tăng bất thường;
- browse/cart/checkout smoke pass theo mức liên quan;
- token inventory pass;
- Argo Synced/Healthy.

## 13.5. Checkout special case

Checkout liên quan Argo Rollouts `workloadRef` và Deployment được reuse làm Pod template.

Phải xác minh Pod-template change thực sự đi qua luồng rollout hiện tại, không làm Argo Rollouts/Deployment tranh chấp.

Các command:

```bash
kubectl -n techx-tf3 get rollout checkout-rollout -o yaml
kubectl -n techx-tf3 get deploy checkout -o yaml
kubectl -n techx-tf3 argo rollouts status checkout-rollout --timeout 10m
```

Nếu CLI syntax khác, dùng `kubectl argo rollouts` đúng plugin đang cài.

---

# 14. Pull-request execution plan

## PR 0 — Baseline, ADR, tests

### Changes

- ghi latest main SHA;
- update ADR draft;
- add render inventory/verifier;
- add fixtures/unit tests;
- không đổi production values.

### Exit gate

- authoritative render pass;
- tests phát hiện đúng current SEC-01/SEC-02 violations;
- no production behavior change;
- exact workload and SA inventory recorded.

---

## PR 1 — Chart support, no behavior change

### Changes

- schema fields;
- shared/component SA template support;
- Pod template support;
- chưa set values false.

### Exit gate

- rendered production manifests semantically unchanged;
- explicit fixture false render đúng;
- explicit fixture true render đúng;
- schema invalid type fail;
- chart lint pass.

---

## PR 2 — SEC-01 Grafana namespaced RBAC

### Changes

- add `grafana.rbac.namespaced: true` production values;
- evidence/render tests;
- no SEC-02 behavior change.

### Exit gate

- render has Role/RoleBinding;
- render has no dangerous ClusterRole/CRB;
- Argo prune old live resources;
- own namespace can-i = yes;
- foreign namespace can-i = no;
- Grafana health/UI/dashboard/data source pass.

### Rollback

Revert PR 2. Do not manually recreate RBAC.

---

## PR 3 — SEC-02 canary

### Changes

- component-specific Pod automount false for selected canaries;
- product-reviews canary only after IRSA preflight.

### Exit gate

- declarative rollout completes;
- no kube-api-access volume/mount;
- service health pass;
- Argo clean.

### Rollback

Revert component values change.

---

## PR 4 — SEC-02 final default

### Changes

- shared SA false;
- default Pod false;
- remove temporary redundant canary overrides;
- no unexplained true exception.

### Exit gate

- all target workloads roll successfully;
- all target live Pods have no Kubernetes API token mount;
- product-reviews IRSA/Bedrock pass;
- money path pass;
- Argo clean.

### Rollback

Revert PR 4. If one workload uniquely needs K8s API, stop and open reviewed exception PR; do not patch live Deployment.

---

## PR 5 — Evidence and closure

### Changes

- final evidence index;
- final ADR decision;
- commands/output;
- Jira DoD mapping;
- residual full Mandate 17 controls.

### Exit gate

Mentor can reproduce all tests from docs without private unstated steps.

---

# 15. Detailed execution procedure

## Phase A — Preflight

```bash
git switch main
git pull --ff-only
git status --short
git rev-parse HEAD | tee /tmp/mandate17-main-sha.txt

git fetch origin main
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"
```

Cluster identity:

```bash
aws sts get-caller-identity
kubectl config current-context
kubectl cluster-info
kubectl get ns techx-tf3
```

Health:

```bash
kubectl -n argocd get application techx-corp
kubectl -n techx-tf3 get deploy,pod -o wide
kubectl -n techx-tf3 get events \
  --sort-by=.lastTimestamp | tail -100
```

Stop khi:

- active incident;
- Argo Degraded;
- checkout SLO fail;
- repo dirty/stale;
- wrong AWS account/cluster;
- current baseline khác spec nhưng chưa refresh inventory.

## Phase B — Capture before evidence

```bash
mkdir -p /tmp/mandate17-before

kubectl get clusterrole,clusterrolebinding -o yaml \
  > /tmp/mandate17-before/cluster-rbac.yaml

kubectl -n techx-tf3 get role,rolebinding,serviceaccount -o yaml \
  > /tmp/mandate17-before/namespaced-rbac-sa.yaml

kubectl -n techx-tf3 get deploy,pod -o json \
  > /tmp/mandate17-before/workloads.json

kubectl -n argocd get application techx-corp -o yaml \
  > /tmp/mandate17-before/argocd-app.yaml
```

Baseline RBAC:

```bash
SUBJECT='system:serviceaccount:techx-tf3:grafana'

kubectl auth can-i list secrets --as="$SUBJECT" -n kube-system \
  | tee /tmp/mandate17-before/grafana-kube-system.txt

kubectl auth can-i list secrets --as="$SUBJECT" -n techx-tf3 \
  | tee /tmp/mandate17-before/grafana-techx-tf3.txt
```

Baseline token inventory script phải ghi:

- Deployment name;
- Pod name;
- ServiceAccount;
- Pod automount value;
- SA automount value;
- `kube-api-access-*` volume count;
- K8s token mount count;
- IRSA token mount count.

## Phase C — Authoritative Helm render

```bash
helm dependency build "phase3 - information/techx-corp-chart"
helm lint "phase3 - information/techx-corp-chart" \
  -f "phase3 - information/techx-corp-chart/values.yaml" \
  -f "phase3 - information/deploy/values-flagd-sync.yaml" \
  -f "phase3 - information/deploy/values-prod.yaml" \
  -f "phase3 - information/deploy/values-aio-llm.yaml"

helm template techx-corp \
  "phase3 - information/techx-corp-chart" \
  --namespace techx-tf3 \
  -f "phase3 - information/techx-corp-chart/values.yaml" \
  -f "phase3 - information/deploy/values-flagd-sync.yaml" \
  -f "phase3 - information/deploy/values-prod.yaml" \
  -f "phase3 - information/deploy/values-aio-llm.yaml" \
  > /tmp/mandate17-rendered.yaml
```

Store dependency lock changes only if intentional. Revert generated noise before PR.

## Phase D — Static/unit tests

```bash
python3 -m pytest \
  scripts/ci/test_verify_mandate17_rbac_render.py \
  scripts/ci/test_verify_serviceaccount_token_mounts.py

python3 scripts/ci/verify-mandate17-rbac-render.py \
  --rendered /tmp/mandate17-rendered.yaml \
  --namespace techx-tf3 \
  --grafana-service-account grafana
```

Optional validators nếu repo có:

```bash
yamllint ...
kubeconform ...
helm unittest ...
```

## Phase E — SEC-01 deploy

Merge qua normal protected flow.

Observe:

```bash
kubectl -n argocd get application techx-corp -w
```

Then:

```bash
kubectl -n argocd get application techx-corp \
  -o jsonpath='{.status.sync.status} {.status.health.status}{"\n"}'
```

Expected:

```text
Synced Healthy
```

Verify prune and RBAC matrix before proceeding.

## Phase F — SEC-02 staged rollout

For each group:

```bash
kubectl -n techx-tf3 rollout status deploy/<name> --timeout=10m
```

Capture new ReplicaSet and Pod UID to prove Pod recreation:

```bash
kubectl -n techx-tf3 get deploy,rs,pod \
  -l opentelemetry.io/name=<name> \
  -o wide
```

Do not move to next group if one rollout is unresolved.

## Phase G — Final live verification

Run all sections in test matrix and write outputs into evidence pack.

---

# 16. Token mount verification

## 16.1. ServiceAccount object checks

```bash
kubectl -n techx-tf3 get sa techx-corp \
  -o jsonpath='{.automountServiceAccountToken}{"\n"}'
```

Expected:

```text
false
```

Product reviews:

```bash
kubectl -n techx-tf3 get sa product-reviews-bedrock -o json \
  | jq '{
      name: .metadata.name,
      automount: .automountServiceAccountToken,
      irsaRole: .metadata.annotations["eks.amazonaws.com/role-arn"]
    }'
```

Expected:

- automount false;
- IRSA role unchanged and non-empty.

## 16.2. Deployment Pod-template check

```bash
kubectl -n techx-tf3 get deploy -o json \
  | jq -r '
      .items[]
      | [
          .metadata.name,
          (.spec.template.spec.serviceAccountName // "default"),
          (.spec.template.spec.automountServiceAccountToken | tostring)
        ]
      | @tsv
    '
```

Expected for target business deployments:

```text
<name>  <service-account>  false
```

## 16.3. Live Pod volume/mount check

Primary verifier:

```bash
kubectl -n techx-tf3 get pods -o json \
  | jq -r '
      .items[]
      | select(
          (.spec.serviceAccountName == "techx-corp") or
          (.spec.serviceAccountName == "product-reviews-bedrock")
        )
      | {
          pod: .metadata.name,
          sa: .spec.serviceAccountName,
          automount: .spec.automountServiceAccountToken,
          kubeApiVolumes: [
            (.spec.volumes // [])[]?
            | select(.name | startswith("kube-api-access-"))
            | .name
          ],
          kubernetesApiMounts: [
            (.spec.containers // [])[]
            | {
                container: .name,
                mounts: [
                  (.volumeMounts // [])[]?
                  | select(.mountPath == "/var/run/secrets/kubernetes.io/serviceaccount")
                ]
              }
          ],
          irsaMounts: [
            (.spec.containers // [])[]
            | {
                container: .name,
                mounts: [
                  (.volumeMounts // [])[]?
                  | select(.mountPath == "/var/run/secrets/eks.amazonaws.com/serviceaccount")
                ]
              }
          ]
        }
    '
```

Final gate:

```text
kubeApiVolumes == []
kubernetesApiMounts[*].mounts == []
```

Cho `product-reviews`, expected thêm:

```text
irsaMounts chứa EKS web-identity mount
```

## 16.4. Filesystem evidence

Preflight kiểm command availability:

```bash
kubectl -n techx-tf3 exec deploy/checkout -- ls --version
```

Nếu `ls` không tồn tại, không dùng command đó làm evidence.

Khi command tồn tại:

```bash
set +e
kubectl -n techx-tf3 exec deploy/checkout -- \
  ls /var/run/secrets/kubernetes.io/serviceaccount/ \
  > /tmp/checkout-token-check.txt 2>&1
status=$?
set -e

test "$status" -ne 0
grep -Ei 'No such file or directory|cannot access' \
  /tmp/checkout-token-check.txt
! grep -q 'executable file not found' /tmp/checkout-token-check.txt
```

Lặp với ít nhất:

- checkout;
- payment;
- product-catalog;
- một canary non-money-path.

Nếu container không có tool, Pod spec verifier là evidence authoritative.

---

# 17. IRSA regression verification

## 17.1. Pod identity injection

```bash
POD="$(kubectl -n techx-tf3 get pod \
  -l opentelemetry.io/name=product-reviews \
  -o jsonpath='{.items[0].metadata.name}')"

kubectl -n techx-tf3 get pod "$POD" -o json \
  | jq '{
      sa: .spec.serviceAccountName,
      automount: .spec.automountServiceAccountToken,
      awsEnv: [
        .spec.containers[].env[]?
        | select(
            .name == "AWS_ROLE_ARN" or
            .name == "AWS_WEB_IDENTITY_TOKEN_FILE"
          )
      ],
      volumes: [.spec.volumes[]? | select(.name | test("aws|token"; "i"))],
      mounts: [
        .spec.containers[]
        | {
            name: .name,
            mounts: [
              .volumeMounts[]?
              | select(.mountPath | test("eks.amazonaws.com/serviceaccount"))
            ]
          }
      ]
    }'
```

Expected:

- `sa = product-reviews-bedrock`;
- `automount = false`;
- AWS envs present;
- EKS token volume/mount present;
- Kubernetes API default token volume absent.

## 17.2. AWS identity test

Chỉ chạy nếu container có AWS CLI. Nếu không, không cài tool vào production Pod.

Ưu tiên application-level test:

- gọi product review summary endpoint;
- xác minh response không fallback do `AccessDenied`;
- kiểm log không có STS/Bedrock credential error;
- kiểm CloudWatch/trace nếu có.

Logs:

```bash
kubectl -n techx-tf3 logs deploy/product-reviews \
  --since=15m \
  | grep -Ei 'AccessDenied|InvalidIdentityToken|AssumeRoleWithWebIdentity|credential|bedrock|error'
```

No-match hoặc expected successful Bedrock log.

## 17.3. Stop condition

Nếu product-reviews mất IRSA:

- dừng rollout toàn bộ;
- rollback SEC-02 behavior commit;
- không set Pod automount true làm workaround trước khi xác định nguyên nhân;
- kiểm EKS mutating webhook annotation, projected volume và SDK credential chain.

---

# 18. Runtime smoke tests

## 18.1. Grafana internal health

Tìm service thực tế:

```bash
kubectl -n techx-tf3 get svc \
  -l app.kubernetes.io/name=grafana
```

Port-forward:

```bash
kubectl -n techx-tf3 port-forward svc/<grafana-service> 3000:80
```

Tùy service target port thực tế, điều chỉnh bằng manifest, không đoán.

Health:

```bash
curl --fail --silent --show-error \
  http://127.0.0.1:3000/api/health
```

Expected HTTP 200 và database status OK.

Do `root_url` hiện là private hostname, browser redirect có thể trỏ hostname đó. API health là internal authoritative check.

## 18.2. Grafana sidecar functionality

Verify:

- Grafana Pod Ready;
- dashboard sidecar không lỗi forbidden;
- datasource sidecar không lỗi forbidden;
- dashboard/datasource ConfigMaps/Secrets trong `techx-tf3` vẫn được watch.

```bash
kubectl -n techx-tf3 logs deploy/<grafana-deployment> \
  --all-containers \
  --since=15m \
  | grep -Ei 'forbidden|permission denied|failed to list|failed to watch|unauthorized'
```

Expected: không có lỗi RBAC mới.

## 18.3. Private Grafana URL

Nếu Cloudflare Access session hợp lệ:

```bash
curl -I https://grafana.arthur-ngo.org/
```

Expected status phù hợp flow Access/session. Không lưu cookie/token vào evidence.

## 18.4. Storefront and money path

Dùng endpoint/access path hiện hành. Không hardcode localhost route nếu environment khác.

Minimum:

```text
storefront root                  200
/api/products                   200
cart read                       200
cart mutation + read-back       success
checkout/place-order            success
```

Nếu repo có smoke script chính thức, dùng script đó thay vì curl tự chế.

Capture:

- timestamp;
- target URL đã redact host nếu cần;
- response code;
- order ID hoặc correlation ID không nhạy cảm;
- commit SHA;
- Pod revisions.

## 18.5. Observability smoke

- Prometheus datasource healthy;
- dashboard query trả data;
- traces vẫn chảy;
- Grafana sidecar vẫn discover resources trong own namespace.

---

# 19. Test matrix

## 19.1. Schema/template tests

| ID | Test | Expected |
|---|---|---|
| SCH-001 | Helm lint current values | Pass |
| SCH-002 | `automountServiceAccountToken: false` accepted | Pass |
| SCH-003 | `automountServiceAccountToken: true` accepted | Pass |
| SCH-004 | string `"false"` | Fail schema |
| SCH-005 | integer `0` | Fail schema |
| SCH-006 | misspelled key | Fail schema/additionalProperties gate |
| TPL-001 | Shared SA false renders | Pass |
| TPL-002 | Shared SA explicit true renders true | Pass fixture only |
| TPL-003 | Omitted SA field preserves old behavior in support-only PR | Pass |
| TPL-004 | Component SA inherits global false | Pass |
| TPL-005 | Component explicit override is honored | Pass fixture |
| TPL-006 | Pod default false renders | Pass |
| TPL-007 | Component Pod override false renders | Pass |
| TPL-008 | Component explicit true is not overwritten by Helm `default` | Pass fixture |
| TPL-009 | `product-reviews-bedrock` annotation preserved | Pass |
| TPL-010 | No duplicate ServiceAccount | Pass |

## 19.2. Grafana render tests

| ID | Test | Expected |
|---|---|---|
| GRF-001 | Four-values authoritative render | Pass |
| GRF-002 | Grafana Role exists | Pass |
| GRF-003 | Grafana RoleBinding exists | Pass |
| GRF-004 | Grafana Secret-read ClusterRole absent | Pass |
| GRF-005 | Grafana Secret-read CRB absent | Pass |
| GRF-006 | Role namespace is `techx-tf3` | Pass |
| GRF-007 | RoleBinding subject is SA `grafana` | Pass |
| GRF-008 | RoleRef kind is Role | Pass |
| GRF-009 | Allowed resources limited to required set | Pass |
| GRF-010 | No wildcard verbs | Pass |
| GRF-011 | No wildcard resources | Pass |
| GRF-012 | No mutation verbs on Secret | Pass |
| GRF-013 | Existing Grafana config retained | Pass |
| GRF-014 | Duplicate top-level Grafana YAML key | Fail review/static test |

## 19.3. Live RBAC tests

| ID | Test | Expected |
|---|---|---|
| RBAC-001 | list Secret `techx-tf3` | Yes |
| RBAC-002 | get Secret `techx-tf3` | Yes if chart needs |
| RBAC-003 | watch Secret `techx-tf3` | Yes if chart needs |
| RBAC-004 | list ConfigMap `techx-tf3` | Yes |
| RBAC-005 | list Secret `kube-system` | No |
| RBAC-006 | list Secret `argocd` | No |
| RBAC-007 | list Secret `kyverno` | No |
| RBAC-008 | list Secret `default` | No |
| RBAC-009 | list Secret all namespaces | No |
| RBAC-010 | create Secret own namespace | No |
| RBAC-011 | patch Secret own namespace | No |
| RBAC-012 | delete Secret own namespace | No |
| RBAC-013 | old Grafana ClusterRole absent | Pass |
| RBAC-014 | old Grafana CRB absent | Pass |
| RBAC-015 | no alternate ClusterRoleBinding grants equivalent access | Pass |

## 19.4. Token render/live tests

| ID | Test | Expected |
|---|---|---|
| TOK-001 | Shared SA automount | False |
| TOK-002 | Business Deployment Pod-level automount | False |
| TOK-003 | Component SA automount | False unless approved exception |
| TOK-004 | Live Pod spec automount | False |
| TOK-005 | `kube-api-access-*` volume | Absent |
| TOK-006 | Kubernetes API token mount path | Absent |
| TOK-007 | Checkout filesystem path | No such file, not missing-command error |
| TOK-008 | Payment filesystem path | No such file, not missing-command error |
| TOK-009 | Product catalog path | No such file, not missing-command error |
| TOK-010 | New Pod after reschedule | Still absent |
| TOK-011 | Deployment rollout creates new Pod UID | Pass |
| TOK-012 | Old ReplicaSet scaled down | Pass |
| TOK-013 | No default SA accidentally used | Pass |

## 19.5. IRSA tests

| ID | Test | Expected |
|---|---|---|
| IRSA-001 | `product-reviews-bedrock` SA exists | Pass |
| IRSA-002 | IRSA annotation unchanged | Pass |
| IRSA-003 | Pod uses dedicated SA | Pass |
| IRSA-004 | Pod automount K8s token false | Pass |
| IRSA-005 | Kubernetes default token volume absent | Pass |
| IRSA-006 | EKS web-identity volume present | Pass |
| IRSA-007 | AWS_ROLE_ARN present | Pass |
| IRSA-008 | AWS_WEB_IDENTITY_TOKEN_FILE present | Pass |
| IRSA-009 | Bedrock request succeeds | Pass |
| IRSA-010 | No `InvalidIdentityToken`/AccessDenied regression | Pass |

## 19.6. GitOps tests

| ID | Test | Expected |
|---|---|---|
| GIT-001 | Argo app before | Synced/Healthy |
| GIT-002 | Argo sync after SEC-01 | Synced/Healthy |
| GIT-003 | Argo prunes old cluster RBAC | Pass |
| GIT-004 | No manual live-only patch | Pass |
| GIT-005 | Self-heal does not restore bad RBAC | Pass |
| GIT-006 | Argo sync after each SEC-02 group | Synced/Healthy |
| GIT-007 | Desired/live manifests match | Pass |
| GIT-008 | Rollback via Git revert | Documented/testable |

## 19.7. Runtime tests

| ID | Test | Expected |
|---|---|---|
| LIVE-001 | All target Deployments available | Desired=Available |
| LIVE-002 | No new CrashLoopBackOff | Pass |
| LIVE-003 | No new ImagePullBackOff | Pass |
| LIVE-004 | Grafana `/api/health` | HTTP 200 |
| LIVE-005 | Grafana sidecar no forbidden | Pass |
| LIVE-006 | Grafana dashboard/datasource loads | Pass |
| LIVE-007 | Storefront root | HTTP 200 |
| LIVE-008 | Product browse | HTTP 200/success |
| LIVE-009 | Cart read/write | Success |
| LIVE-010 | Checkout order | Success |
| LIVE-011 | Product reviews Bedrock path | Success |
| LIVE-012 | Telemetry flows | Pass |
| LIVE-013 | Flagd invariant | Unchanged |
| LIVE-014 | Soak period | No delayed regression |

## 19.8. Negative tests

| ID | Failure | Expected behavior |
|---|---|---|
| NEG-001 | Grafana ClusterRole still rendered | Stop; do not merge |
| NEG-002 | Grafana own namespace access becomes no | Stop/rollback SEC-01 |
| NEG-003 | Grafana foreign namespace remains yes | Stop; task not fixed |
| NEG-004 | Role grants wildcard/mutation | Stop |
| NEG-005 | Shared SA field false omitted due Helm truthiness | Static test fails |
| NEG-006 | Pod false omitted | Static test fails |
| NEG-007 | Only SA changed, old Pods still carry token | DoD fails until declarative rollout |
| NEG-008 | `ls` command missing | Evidence invalid; use Pod spec verifier |
| NEG-009 | Product-reviews loses IRSA | Stop/rollback |
| NEG-010 | Bedrock returns AccessDenied | Stop/rollback |
| NEG-011 | Argo Degraded | Stop/rollback |
| NEG-012 | Checkout failure/regression | Immediate rollback |
| NEG-013 | Flagd diff | Immediate rollback |
| NEG-014 | PR contains unrelated infra/app diff | Stop review |
| NEG-015 | Manual deletion required because Git still renders RBAC | Fix desired state first |

---

# 20. Evidence pack

```text
docs/evidence/mandate-17/rbac/
├── README.md
├── baseline/
│   ├── main-sha.txt
│   ├── argocd-app.yaml
│   ├── grafana-rbac-before.yaml
│   ├── grafana-can-i-before.txt
│   ├── serviceaccounts-before.yaml
│   ├── workloads-before.json
│   └── token-inventory-before.json
├── render/
│   ├── helm-version.txt
│   ├── chart-lock.txt
│   ├── rendered-rbac.yaml
│   ├── rendered-serviceaccounts.yaml
│   ├── rendered-deployments.json
│   └── render-verification.json
├── sec-01/
│   ├── grafana-role.yaml
│   ├── grafana-rolebinding.yaml
│   ├── cluster-rbac-after.json
│   ├── can-i-own-namespace.txt
│   ├── can-i-foreign-namespaces.txt
│   ├── can-i-mutation.txt
│   ├── grafana-health.json
│   ├── grafana-sidecar-logs.txt
│   └── argocd-health.txt
├── sec-02/
│   ├── shared-sa.yaml
│   ├── product-reviews-sa.yaml
│   ├── deployment-automount-inventory.json
│   ├── live-token-mount-inventory.json
│   ├── checkout-token-check.txt
│   ├── payment-token-check.txt
│   ├── product-catalog-token-check.txt
│   ├── irsa-injection.json
│   ├── bedrock-smoke.txt
│   └── rollout-status.txt
├── runtime/
│   ├── pods-after.json
│   ├── storefront-smoke.txt
│   ├── browse-smoke.txt
│   ├── cart-smoke.txt
│   ├── checkout-smoke.txt
│   ├── telemetry-smoke.txt
│   └── soak-summary.md
└── final/
    ├── closure-checklist.md
    ├── dod-mapping.md
    ├── residual-mandate17-controls.md
    └── rollback-commits.txt
```

## 20.1. Evidence hygiene

Không commit:

- Secret values;
- ServiceAccount token;
- IRSA JWT;
- kubeconfig;
- Cloudflare cookie/token;
- Grafana password;
- AWS credentials;
- response body chứa PII.

RBAC evidence chỉ ghi resource names/rules, không dump Secret data.

---

# 21. Rollback

## 21.1. SEC-01 rollback

Primary:

```bash
git revert <sec-01-commit>
git push
```

Argo sẽ reconcile Role/ClusterRole theo Git.

Không hand-create ClusterRole bằng kubectl làm final rollback.

## 21.2. SEC-02 canary rollback

```bash
git revert <sec-02-canary-commit>
git push
```

Wait rollout and verify.

## 21.3. SEC-02 final rollback

```bash
git revert <sec-02-final-commit>
git push
```

Nếu chỉ một component lỗi và lý do hợp lệ:

- revert group commit hoặc tạo reviewed component override;
- issue phải ghi owner, reason, expiry và evidence;
- không `kubectl patch deployment` trừ emergency.

## 21.4. Emergency procedure

Chỉ khi production outage:

1. Incident commander phê duyệt.
2. Apply minimal temporary patch.
3. Ghi timestamp/actor/command.
4. Tạo Git revert/forward-fix ngay.
5. Để Argo reconcile.
6. Xóa emergency drift.
7. Viết incident note.

## 21.5. Rollback validation

```bash
kubectl -n argocd get application techx-corp
kubectl -n techx-tf3 get deploy,pod
kubectl auth can-i list secrets \
  --as=system:serviceaccount:techx-tf3:grafana \
  -n techx-tf3
```

Runtime smoke lại browse/cart/checkout/Grafana/Bedrock theo phần 18.

---

# 22. Stop conditions

Dừng ngay khi:

- baseline không phải latest main;
- render không dùng đúng bốn values file;
- Grafana namespaced option vẫn tạo dangerous ClusterRole;
- Grafana own-namespace permission bị mất;
- Grafana foreign-namespace permission vẫn còn;
- Argo không prune resource cũ và ownership chưa rõ;
- schema/template bỏ mất explicit false;
- product-reviews mất IRSA env/token;
- Bedrock path fail;
- any business Pod vẫn có kube-api-access volume sau final rollout;
- evidence chỉ chứng minh command `ls` không tồn tại;
- Argo app Degraded;
- rollout timeout;
- storefront/Grafana/checkout fail;
- active incident xảy ra;
- flagd/OpenFeature diff;
- PR chứa unrelated change;
- rollback commit chưa sẵn sàng.

---

# 23. DoD mapping chi tiết

## DoD 1

> `kubectl auth can-i list secrets --as=system:serviceaccount:techx-tf3:grafana -n kube-system` trả `no`.

Required evidence:

- command exact;
- stdout `no`;
- timestamp;
- cluster/context;
- corresponding live Role/RoleBinding;
- no alternate ClusterRoleBinding.

## DoD 2

> Cùng subject trong `techx-tf3` vẫn trả `yes`.

Required evidence:

- `get/list/watch` matrix;
- Grafana sidecar logs không forbidden;
- dashboard/datasource health.

## DoD 3

> Checkout và một số service không còn token directory.

Required evidence:

1. Pod template `automount=false`.
2. Live Pod `automount=false`.
3. No `kube-api-access-*` volume.
4. No mount path.
5. Filesystem `No such file` khi command tồn tại.
6. New Pod UID chứng minh workload đã recreate sau fix.

## DoD 4

> Grafana/storefront vẫn hoạt động.

Required evidence:

- Grafana internal `/api/health` 200;
- Grafana dashboards/datasource sidecar working;
- storefront root 200;
- `/api/products` success;
- cart read/write success;
- checkout success;
- product-reviews Bedrock success;
- Argo Synced/Healthy.

---

# 24. Full Mandate 17 distinction

Completing this task proves:

```text
Grafana RBAC blast radius reduced
+
Business Kubernetes API credential exposure reduced
```

It does **not** yet prove:

- one ServiceAccount per service;
- no shared identity across business workloads;
- all ServiceAccounts have minimal individual Role/RoleBinding;
- dependency fault containment;
- full-AZ survival;
- default-deny NetworkPolicy;
- compromised Pod lateral-movement tests.

Final Jira comment should say:

```text
SEC-01 and SEC-02 completed with mentor-reproducible evidence.
This closes the scoped RBAC/token findings under Mandate 17 requirement #4.
Full Mandate 17 retains separate work for per-service identity/RBAC,
NetworkPolicy containment, dependency failure and AZ failure drills.
```

---

# 25. Agent execution contract

Agent phải:

1. cập nhật latest `main`;
2. ghi base SHA;
3. đọc lại `docs/evidence/10-security-baseline-rbac.md`;
4. render đúng bốn values file từ Argo Application;
5. không hardcode workload count 22 trước inventory;
6. không tạo duplicate top-level `grafana` block;
7. không giả định chart namespaced behavior;
8. không merge nếu render còn dangerous ClusterRole;
9. không dùng manual kubectl delete làm desired-state fix;
10. thêm schema cùng template changes;
11. dùng `hasKey` để false không bị bỏ render;
12. bảo vệ cả shared và component-scoped ServiceAccounts;
13. thêm Pod-level field để trigger declarative rollout;
14. rollout theo nhóm;
15. giữ `product-reviews-bedrock` IRSA annotation;
16. phân biệt Kubernetes API token và EKS IRSA token;
17. không coi missing `ls` là token absent;
18. xác minh Pod spec volume/mount;
19. chạy RBAC matrix trong và ngoài namespace;
20. kiểm tra mutation verbs vẫn denied;
21. xác minh Argo prune/self-heal;
22. chạy Grafana/storefront/cart/checkout/Bedrock smoke;
23. chuẩn bị Git revert trước mỗi cutover;
24. dừng khi có stop condition;
25. không tuyên bố full Mandate 17 hoàn tất.

## Agent final report format

```text
Phase:
Branch:
Base main SHA:
PR:
Commits:
Files changed:

Authoritative render:
- Chart version:
- Values files:
- Workload count:
- Business workload set:
- Component-scoped SAs:

SEC-01:
- Grafana Role:
- Grafana RoleBinding:
- ClusterRole remaining:
- ClusterRoleBinding remaining:
- Own-namespace can-i:
- Foreign-namespace can-i:
- Mutation can-i:
- Grafana health:
- Sidecar RBAC errors:

SEC-02:
- Shared SA automount:
- Pod default automount:
- Workloads covered:
- Exceptions:
- Live kube-api-access volumes:
- Live K8s token mounts:
- Checkout filesystem result:
- Other service results:

IRSA:
- ServiceAccount:
- Annotation:
- Pod automount:
- AWS role env:
- Web identity token path:
- Kubernetes API token path:
- Bedrock result:

GitOps/runtime:
- Argo sync/health:
- Rollouts:
- Pods:
- Grafana:
- Storefront:
- Browse:
- Cart:
- Checkout:
- Telemetry:
- Flagd invariant:

Evidence paths:
Rollback commits:
Residual risks:
Full Mandate 17 remaining controls:
Recommendation:
```

---

# 26. Final acceptance checklist

## Baseline

- [ ] Latest `origin/main` checked out.
- [ ] Base SHA recorded.
- [ ] Correct AWS account/cluster verified.
- [ ] Argo `techx-corp` initially Synced/Healthy.
- [ ] Active incident absent.
- [ ] Before evidence captured.

## Render

- [ ] Dependency chart version recorded.
- [ ] Four Argo values files used in correct order.
- [ ] Helm dependency build/lint pass.
- [ ] Exact workload inventory generated.
- [ ] Exact ServiceAccount inventory generated.
- [ ] `product-reviews-bedrock` present in render.

## SEC-01

- [ ] `grafana.rbac.create=true`.
- [ ] `grafana.rbac.namespaced=true`.
- [ ] `grafana.rbac.pspEnabled=false` retained/confirmed.
- [ ] Existing Grafana values preserved.
- [ ] Grafana Role rendered.
- [ ] Grafana RoleBinding rendered.
- [ ] RoleBinding subject is `techx-tf3:grafana`.
- [ ] RoleRef is namespaced Role.
- [ ] No wildcard verb/resource.
- [ ] No mutation verb on Secret.
- [ ] No dangerous Grafana ClusterRole rendered.
- [ ] No dangerous Grafana ClusterRoleBinding rendered.
- [ ] Argo pruned old live ClusterRole/CRB.
- [ ] Own namespace Secret access = yes.
- [ ] kube-system Secret access = no.
- [ ] argocd Secret access = no.
- [ ] kyverno Secret access = no.
- [ ] all-namespace Secret list = no.
- [ ] Grafana sidecars have no forbidden errors.
- [ ] Grafana health 200.

## SEC-02 schema/templates

- [ ] SA schema boolean added.
- [ ] Default/component Pod schema boolean added.
- [ ] Shared SA template uses `hasKey`.
- [ ] Component SA template uses `hasKey`.
- [ ] Pod template uses explicit precedence with `hasKey`.
- [ ] False renders as false.
- [ ] True fixture renders as true.
- [ ] Invalid types fail schema.
- [ ] Support-only render has no behavior change.

## SEC-02 final values/runtime

- [ ] Shared SA automount false.
- [ ] Default business Pod automount false.
- [ ] Target Deployment templates show false.
- [ ] Target live Pods show false.
- [ ] Target Pod UIDs prove recreation.
- [ ] No kube-api-access volume.
- [ ] No Kubernetes API token mount.
- [ ] Checkout evidence is valid and not missing-command error.
- [ ] Payment evidence valid or Pod spec fallback recorded.
- [ ] Product-catalog evidence valid or Pod spec fallback recorded.
- [ ] New/rescheduled Pod remains token-free.
- [ ] No unexplained true exception.

## IRSA

- [ ] `product-reviews-bedrock` SA remains.
- [ ] IRSA annotation unchanged.
- [ ] Product-reviews uses dedicated SA.
- [ ] Kubernetes automount false.
- [ ] Kubernetes API token path absent.
- [ ] EKS web-identity token path present.
- [ ] AWS_ROLE_ARN present.
- [ ] AWS_WEB_IDENTITY_TOKEN_FILE present.
- [ ] No STS/Bedrock credential error.
- [ ] Product review Bedrock request succeeds.

## Availability

- [ ] Canary group healthy.
- [ ] Supporting group healthy.
- [ ] Money-path group healthy.
- [ ] Checkout Rollout healthy.
- [ ] All target Deployments available.
- [ ] No new CrashLoopBackOff.
- [ ] Grafana health/UI works.
- [ ] Storefront 200.
- [ ] Product browse works.
- [ ] Cart read/write works.
- [ ] Checkout works.
- [ ] Telemetry flows.
- [ ] Flagd unchanged.
- [ ] Soak window clean.

## GitOps/evidence

- [ ] No permanent imperative drift.
- [ ] Argo final Synced/Healthy.
- [ ] Evidence pack has no secret/token.
- [ ] Commands are reproducible.
- [ ] Rollback commits recorded.
- [ ] Jira DoD mapping complete.
- [ ] Residual full Mandate 17 controls stated honestly.

---

# 27. Recommended implementation order in one sentence

```text
Refresh baseline → authoritative render → add schema/template support with no behavior change →
Grafana namespaced RBAC render gate → SEC-01 Argo prune and live RBAC proof →
SEC-02 canary Pod-level false → verify token removal and IRSA →
set shared/default false → staged money-path rollout → runtime smoke → evidence closure.
```

---

# 28. Source-of-truth references

Project paths reviewed for this specification:

```text
docs/evidence/10-security-baseline-rbac.md
gitops/apps/techx-corp.yaml
phase3 - information/techx-corp-chart/Chart.yaml
phase3 - information/techx-corp-chart/values.yaml
phase3 - information/techx-corp-chart/values.schema.json
phase3 - information/techx-corp-chart/templates/component.yaml
phase3 - information/techx-corp-chart/templates/serviceaccount.yaml
phase3 - information/techx-corp-chart/templates/_objects.tpl
phase3 - information/deploy/values-prod.yaml
phase3 - information/deploy/values-aio-llm.yaml
```

External authoritative behavior references:

```text
Kubernetes documentation — Configure Service Accounts for Pods:
- ServiceAccount or Pod may disable token automount.
- Pod-level automountServiceAccountToken takes precedence.

Amazon EKS documentation — IAM roles for service accounts:
- IRSA uses an OIDC projected service-account token for AWS STS.

Mandate source:
phase3/mandates/MANDATE-17-resilience-and-containment.md
```
