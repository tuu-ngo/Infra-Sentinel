# ADR-0011 — Mandate 17 Security: NetworkPolicy Containment + RBAC Least-Privilege

**Trạng thái:** Accepted  
**Ngày:** 2026-07-20  
**Tác giả:** CDO01 (Security)  
**Liên quan:** MANDATE-17, SEC-01, SEC-02, SEC-03  
**Phạm vi:** Namespace `techx-tf3`, cluster `techx-corp-tf3`

> **Lưu ý phân công:** ADR này chỉ bao gồm phần Security (Yêu cầu #3 + #4) của Directive 17.  
> Phần Reliability (Yêu cầu #1 — fallback dependency, Yêu cầu #2 — AZ resilience) do **CDO02** phụ trách riêng — không thuộc scope của ADR này.

---

## Bối cảnh

Sau audit live ngày 20/07/2026 (xem `docs/evidence/mandate-17-security-gap-analysis.md`), cluster `techx-corp-tf3` có 3 gap bảo mật đã được xác nhận:

| Gap | Mô tả | Mức độ |
|---|---|---|
| **SEC-01** | Grafana SA có ClusterRole đọc `secrets` toàn cluster kể cả `kube-system` | HIGH |
| **SEC-02** | 22/22 business deployment mount SA token mặc định (không cần thiết) | MEDIUM |
| **SEC-03** | 18+ business service không có NetworkPolicy — lateral movement tự do, egress internet mở | HIGH |

**Bằng chứng lateral movement "TRƯỚC"** (20/07/2026 ~14:28 UTC):
- `load-generator` → `payment:8080` → **OPEN**
- `load-generator` → `checkout:8080` → **OPEN**
- `load-generator` → internet (`ifconfig.me` = `13.213.127.91`) → **OPEN**

---

## Quyết định

### 1. NetworkPolicy (SEC-03) — Default-Deny Per-Service

**Cách tiếp cận:** Per-service NetworkPolicy với `policyTypes: [Ingress, Egress]`.  
Mỗi service chỉ được phép ingress từ callers hợp lệ và egress tới downstream cần thiết.

**Lý do chọn per-service thay vì global default-deny:**
- Global default-deny (`podSelector: {}`) ảnh hưởng cả observability pods đang có NP riêng chỉ với `policyTypes: [Ingress]` → sẽ bị deny egress ngoài ý muốn
- Per-service an toàn hơn: mỗi thay đổi chỉ ảnh hưởng service cụ thể, dễ rollback từng phần
- Học từ PM-0006: tránh global rule gây cascade failure

**File:** `gitops/infrastructure/network-policy-business-services.yaml`  
Bao gồm NP cho: checkout, cart, currency, shipping, quote, ad, recommendation, product-catalog, product-reviews, payment, email, accounting, fraud-detection, frontend, frontend-proxy, image-provider, llm, flagd, aiops-engine, cloudflared.

**Common egress rules cho tất cả business pods:**
```yaml
# DNS (bắt buộc — không có DNS = không resolve hostname)
- ports: [{port: 53, protocol: UDP}, {port: 53, protocol: TCP}]

# OTel Collector (bắt buộc — thiếu → cascading failure như PM-0006)
- to: [{podSelector: {app.kubernetes.io/name: opentelemetry-collector, component: agent-collector}}]
  ports: [{port: 4317, protocol: TCP}, {port: 4318, protocol: TCP}]
```

**Ngoại lệ có ghi nhận (TODO):**

| Service | Ngoại lệ | Lý do | Hành động tiếp theo |
|---|---|---|---|
| `payment` | Egress HTTPS 443 ra internet (`0.0.0.0/0` trừ RFC1918) | External payment gateway — chưa biết CIDR | Lock xuống CIDR cụ thể khi biết endpoint |
| `email` | Egress SMTP 587/465/25 ra internet | AWS SES — chưa biết CIDR SES region | Lock xuống AWS SES CIDR sau |
| `llm` | Egress HTTPS 443 ra internet | Bedrock endpoint — chưa rõ VPC endpoint hay internet | Nếu VPC endpoint: đổi sang private CIDR |
| `flagd` | Egress HTTPS 443 ra internet | BTC flagd sync endpoint | Không thay đổi — cần cho feature flag |
| `cloudflared` | Egress 443+7844 TCP/UDP ra internet | Cloudflare edge tunnel | Không thay đổi — cần cho Cloudflare Access |

### 2. RBAC Least-Privilege (SEC-01) — Grafana namespaced RBAC

**Vấn đề:** Upstream Grafana Helm chart tạo `ClusterRole` cho Grafana SA với quyền `get/list/watch` trên `secrets` toàn cluster.

**Giải pháp:** Bật `grafana.rbac.namespaced: true` trong `values-prod.yaml`.

Kết quả: Chart sẽ tạo `Role` (namespace-scoped trong `techx-tf3`) + `RoleBinding` thay vì `ClusterRole` + `ClusterRoleBinding`. ArgoCD sẽ sync và xóa `grafana-clusterrole` / `grafana-clusterrolebinding`.

**Lý do không patch kubectl trực tiếp:** `grafana-clusterrole` có `argocd.argoproj.io/tracking-id` — ArgoCD selfHeal=true sẽ revert bất kỳ out-of-band change nào.

**Verify sau sync:**
```bash
kubectl auth can-i list secrets --as=system:serviceaccount:techx-tf3:grafana -n kube-system
# Phải trả: no
```

**Đánh đổi:** Grafana Kubernetes datasource (nếu cấu hình) cần đọc resources ở namespace `techx-tf3` — sau khi đổi sang Role, scope chỉ còn `techx-tf3`. Đây là behavior mong muốn.

### 3. automountServiceAccountToken=false (SEC-02)

**Vấn đề:** 22/22 business deployment mount SA token mặc định (`techx-corp`) dù không cần gọi K8s API.

**Giải pháp:** Thêm `automountServiceAccountToken: {{ .automountServiceAccountToken | default false }}` vào `_objects.tpl`. Default là `false` — component nào cần K8s API phải set `automountServiceAccountToken: true` trong values.

**⚠️ Kafka gotcha (PM-0007):**  
Kafka dùng `strategy: Recreate`. Thay đổi pod template → Kafka pod restart ~25s → trong cửa sổ đó `checkout` publish Kafka thất bại → sự kiện đơn hàng bị drop không thể recover (không có DLQ).

Quyết định: deploy PR automount **cho toàn bộ trừ Kafka** trước, Kafka riêng sau trong giờ thấp điểm có người trực.

**Verify sau deploy:**
```bash
kubectl -n techx-tf3 exec deploy/cart -- cat /var/run/secrets/kubernetes.io/serviceaccount/token
# Phải trả: error — No such file or directory
```

---

## Hậu quả

### Dự kiến
- **Lateral movement bị chặn:** Pod bị compromise không thể kết nối sang service không liên quan
- **Egress bị khóa:** Pod không gọi được internet tùy tiện (trừ payment/email/llm/flagd/cloudflared có ngoại lệ đã ghi nhận)
- **SA token bị thu hẹp:** Business pod không còn credential để gọi K8s API
- **Grafana blast-radius giảm:** Nếu Grafana bị compromise, attacker không đọc được secrets ở kube-system

### Rủi ro còn lại
- Các ngoại lệ egress (payment/email/llm) vẫn mở ra internet — cần followup để lock CIDR
- SA `techx-corp` vẫn tồn tại (không xóa token, chỉ không mount) — cần audit xem có ClusterRole binding nào sau này không
- Kafka downtime window khi deploy automount — cần window giờ thấp điểm

### Rollback
```bash
# Rollback NetworkPolicy (xóa NP mới, không đụng NP cũ):
kubectl -n techx-tf3 delete networkpolicy \
  checkout-network-policy cart-network-policy currency-network-policy \
  shipping-network-policy quote-network-policy ad-network-policy \
  recommendation-network-policy product-catalog-network-policy \
  product-reviews-network-policy payment-network-policy email-network-policy \
  accounting-network-policy fraud-detection-network-policy frontend-network-policy \
  frontend-proxy-network-policy image-provider-network-policy llm-network-policy \
  flagd-network-policy aiops-engine-network-policy cloudflared-network-policy \
  attacker-demo-deny-all

# Rollback Grafana RBAC: xóa rbac.namespaced từ values-prod.yaml + ArgoCD sync

# Rollback automount: xóa dòng trong _objects.tpl + ArgoCD sync
# (Không cần restart thủ công — RollingUpdate tự xử lý)
```

---

## Bằng chứng sau fix ("SAU")

*Sẽ điền sau khi verify live:*

| Kiểm tra | TRƯỚC | SAU |
|---|---|---|
| `kubectl get networkpolicy -n techx-tf3 \| wc -l` | 8 | _TBD_ |
| `kubectl auth can-i list secrets --as=grafana -n kube-system` | `yes` | _TBD_ |
| `automountServiceAccountToken` trên checkout | NOT SET (=true) | `false` |
| TCP từ attacker-demo → `payment:8080` | OPEN | _TBD_ |
| TCP từ attacker-demo → `checkout:8080` | OPEN | _TBD_ |
| Egress từ attacker-demo → internet | OPEN | _TBD_ |

---

## Liên kết

- Gap analysis: [`docs/evidence/mandate-17-security-gap-analysis.md`](../evidence/mandate-17-security-gap-analysis.md)
- NetworkPolicy files: [`gitops/infrastructure/network-policy-business-services.yaml`](../../gitops/infrastructure/network-policy-business-services.yaml)
- Demo pod: [`gitops/infrastructure/demo-attacker-pod.yaml`](../../gitops/infrastructure/demo-attacker-pod.yaml)
- Demo runbook: [`docs/evidence/mandate-17-demo-runbook.md`](../evidence/mandate-17-demo-runbook.md)
- PM-0006 (NP gotcha): [`docs/postmortem/0006-networkpolicy-observability-outage.md`](../postmortem/0006-networkpolicy-observability-outage.md)
- PM-0007 (Kafka gotcha): [`docs/postmortem/0007-kafka-recreate-rollout-order-event-loss.md`](../postmortem/0007-kafka-recreate-rollout-order-event-loss.md)
