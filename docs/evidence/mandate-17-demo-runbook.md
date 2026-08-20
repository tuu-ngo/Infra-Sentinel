# Mandate 17 — Demo Runbook: Pod "Kẻ Tấn Công" Bị Khoanh Vùng

**Mục đích:** Mentor tự exec vào pod `attacker-demo` và xác nhận containment đang hoạt động.  
**Thời gian demo:** ~10 phút  
**Người thực hiện:** Mentor (với `kubectl` đã cấu hình trỏ về cluster `techx-corp-tf3`)

---

## Trước khi demo — Checklist (CDO01 chuẩn bị)

```bash
# 1. Xác nhận tunnel SSM đang chạy (terminal riêng, giữ mở)
aws ssm start-session \
  --target i-02a8d3e39b87180ce \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters host="ADA05FFC84146C0AED730F78786EB320.gr7.ap-southeast-1.eks.amazonaws.com",portNumber="443",localPortNumber="8443" \
  --region ap-southeast-1
# Thấy "Port 8443 opened" → tunnel đang sống

# 2. Xác nhận kubectl trỏ đúng cluster
kubectl get nodes

# 3. Deploy demo pod
kubectl apply -f gitops/infrastructure/demo-attacker-pod.yaml
kubectl -n techx-tf3 get pod attacker-demo   # chờ Running
```

---

## Kịch bản Demo

### PHẦN 1 — Chứng minh NetworkPolicy đang hoạt động (~3 phút)

#### Bước 1.1 — Xem toàn bộ NetworkPolicy hiện có

```bash
kubectl -n techx-tf3 get networkpolicy
```

**Kỳ vọng:** Danh sách ~25+ NP, bao gồm tất cả business services.  
**Điểm highlight:** Trước đây chỉ có 8 NP (observability/datastore). Bây giờ business services đều có NP riêng.

---

#### Bước 1.2 — Exec vào pod "kẻ tấn công"

```bash
kubectl -n techx-tf3 exec -it attacker-demo -- sh
```

*Trong shell của attacker-demo:*

#### Bước 1.3 — Thử kết nối tới payment service (PHẢI thất bại)

```python
python3 -c "
import socket
try:
    s = socket.create_connection(('payment', 8080), timeout=3)
    print('OPEN - lateral movement POSSIBLE (FAIL: containment không hoạt động!)')
    s.close()
except Exception as e:
    print('BLOCKED:', type(e).__name__, '← Containment hoạt động đúng!')
"
```

**Kỳ vọng:** `BLOCKED: TimeoutError ← Containment hoạt động đúng!`

---

#### Bước 1.4 — Thử kết nối tới checkout (PHẢI thất bại)

```python
python3 -c "
import socket
try:
    s = socket.create_connection(('checkout', 8080), timeout=3)
    print('OPEN - FAIL')
    s.close()
except Exception as e:
    print('BLOCKED:', type(e).__name__, '← Containment hoạt động đúng!')
"
```

**Kỳ vọng:** `BLOCKED: TimeoutError`

---

#### Bước 1.5 — Thử gọi ra internet (PHẢI thất bại)

```python
python3 -c "
import urllib.request
try:
    resp = urllib.request.urlopen('http://ifconfig.me', timeout=3)
    print('INTERNET ACCESS:', resp.read().decode(), '← FAIL!')
except Exception as e:
    print('INTERNET BLOCKED:', type(e).__name__, '← Egress containment hoạt động đúng!')
"
```

**Kỳ vọng:** `INTERNET BLOCKED: TimeoutError ← Egress containment hoạt động đúng!`

---

#### Bước 1.6 — Baseline comparison (nhắc lại)

Trước khi có NetworkPolicy (20/07/2026):
```
load-generator → payment:8080   = OPEN  ← đây là gap cũ
load-generator → internet       = OPEN (IP: 13.213.127.91) ← đây là gap cũ
```
Bây giờ với attacker-demo (cùng loại pod, nhưng đã có NP):
```
attacker-demo → payment:8080    = BLOCKED ← containment
attacker-demo → internet        = BLOCKED ← egress lock
```

---

### PHẦN 2 — Chứng minh RBAC least-privilege (SEC-01 + SEC-02) (~3 phút)

#### Bước 2.1 — Verify Grafana không còn đọc kube-system secrets

```bash
# Thoát khỏi attacker-demo shell trước (exit)
kubectl auth can-i list secrets \
    --as=system:serviceaccount:techx-tf3:grafana \
    -n kube-system
```

**Kỳ vọng:** `no`  
*(Trước: `yes` — Grafana SA đọc được secrets toàn cluster kể cả kube-system)*

---

#### Bước 2.2 — Verify business pod không mount SA token

```bash
kubectl -n techx-tf3 get deploy cart \
    -o jsonpath="{.spec.template.spec.automountServiceAccountToken}"
```

**Kỳ vọng:** `false`

```bash
# Xác nhận token không tồn tại trong container (dùng pod mới vừa deploy)
kubectl -n techx-tf3 exec deploy/cart -- ls /var/run/secrets/ 2>&1
```

**Kỳ vọng:** `ls: /var/run/secrets/: No such file or directory`  
*(Hoặc thư mục trống — token không được mount)*

---

### PHẦN 3 — Xác nhận storefront vẫn hoạt động (~2 phút)

```bash
# Các pod chính phải vẫn Running
kubectl get pods -n techx-tf3

# Thử port-forward và truy cập storefront
kubectl -n techx-tf3 port-forward svc/frontend-proxy 8080:8080
# Truy cập http://localhost:8080 → phải load bình thường
```

---

## Sau demo — Dọn dẹp

```bash
kubectl delete pod attacker-demo -n techx-tf3
```

---

## So sánh "TRƯỚC" vs "SAU"

| Kiểm tra | TRƯỚC (20/07/2026) | SAU |
|---|---|---|
| `get networkpolicy -n techx-tf3 \| wc -l` | 8 | 25+ |
| `curl payment:8080` từ pod business | ✅ OPEN | ❌ Timeout |
| `curl ifconfig.me` từ pod business | ✅ OPEN (13.213.127.91) | ❌ Timeout |
| `auth can-i list secrets --as=grafana -n kube-system` | `yes` | `no` |
| `automountServiceAccountToken` trên cart/checkout | NOT SET (=true) | `false` |
| Storefront vẫn phục vụ | ✅ | ✅ |
