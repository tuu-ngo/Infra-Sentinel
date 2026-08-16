# Bàn giao: công việc aiops-engine (28/07/2026)

Tài liệu này để người tiếp nhận (Codex hoặc bất kỳ ai) đọc một lần rồi làm tiếp được, không
phải hỏi lại. Viết lúc kết thúc phiên 28/07.

**Trạng thái một câu:** `aiops-engine` (workload AIOps của đội AIO02) đã được đưa từ chỗ chạy
tay hoàn toàn ngoài quản lý về dưới ArgoCD, source đã kéo về repo này, CI build có Trivy +
Cosign đã dựng xong. Build đầu tiên **bị Trivy chặn đúng thiết kế** — đó là việc tiếp theo.

---

## 1. Bối cảnh: vì sao có việc này

Người dùng hỏi "repo AIO02 chứa code aiops, xem cách chuyển nó vào gitops quản lý". Khảo sát
phát hiện `aiops-engine` chạy 13 ngày trong namespace `techx-tf3` **hoàn toàn ngoài GitOps**:
deploy bằng `kubectl apply` tay (`deployment.kubernetes.io/revision: 68`), có dán label
`app.kubernetes.io/managed-by: argocd` **giả** nhưng không ArgoCD Application nào quản.

Kèm theo ba lỗ hổng, chi tiết ở §6.

---

## 2. Đọc code ở đâu

### Repo hạ tầng (repo này) — `tuu-ngo/Phase3-TF3-Infra-Sentinel`

| Đường dẫn | Nội dung |
|---|---|
| `aiops-engine/` | **Source Python của engine** (mới kéo về 28/07, PR #532). ~2.5MB / 80 file. FastAPI + scikit-learn. `main.py` ~2000 dòng là trung tâm. |
| `aiops-engine/tests/` | Test suite 10+ file, chạy được bằng `pytest`. |
| `aiops-engine/Dockerfile` | Base `python:3.10-slim`. **Xem §7 — có 2 vấn đề.** |
| `aiops-engine/.trivyignore` | Hiện **chỉ có header**, chưa CVE nào. Có chủ đích. |
| `aiops-engine/README.md` | Ghi nguồn gốc, commit gốc, những gì đã bị loại và vì sao. **Đọc file này trước.** |
| `aiops-engine/CDO_DEPLOYMENT_GUIDE.md` | Tài liệu gốc của AIO02, **đã lạc hậu** — có khối cảnh báo ở đầu file. Đừng làm theo nguyên văn. |
| `gitops/aiops-engine/` | **Manifest deploy — nguồn sự thật**, do ArgoCD quản. 7 tài nguyên. |
| `gitops/apps/aiops-engine-app.yaml` | ArgoCD Application, `prune: true` + `selfHeal: true`. |
| `.github/workflows/build-push-aiops.yml` | CI build image (mới, PR #532). |
| `.github/workflows/build-push-copilot.yml` | **Khuôn mẫu** mà workflow trên sao lại. Đối chiếu khi nghi ngờ. |
| `docs/superpowers/specs/2026-07-28-aiops-engine-gitops-adoption-design.md` | **Thiết kế đầy đủ.** Đọc trước khi làm Phase 2/3. |
| `docs/evidence/aiops-engine/` | Bằng chứng: manifest ingress đã xoá, output `kubectl diff`. |

### Repo nguồn của AIO02 — `DangThao195/AIO02_TF3_Phase3`

Vẫn còn tồn tại. Source gốc ở `AIOps/aiops-engine/`, kéo về từ commit
`d68dd9759491dc03e9a3d83c27393f52851dc8c9` (27/07 20:32 +07).

**⚠️ Repo đó KHÔNG còn là nguồn sự thật cho aiops-engine.** Người dùng nói AIO02 đã đồng ý
chuyển. Nếu thấy họ vẫn sửa `AIOps/aiops-engine/`, đó là hai nguồn sự thật — cần nói lại với
họ, đừng tự merge chéo.

Các phần khác của repo đó (`chaos-engine`, `AIE1`, `AIE2`) **không** thuộc phạm vi, xem §9.

---

## 3. Truy cập môi trường

```bash
# AWS: profile `default` đã login đúng account production 197826770971.
# ⚠️ KHÔNG export AWS_PROFILE=techx-new — profile đó KHÔNG tồn tại trên máy này.
#    (CLAUDE.md có chỗ ghi phải dùng techx-new; với máy này là SAI.)
aws sts get-caller-identity   # phải ra 197826770971

# kubectl: qua SSM tunnel, chạy script này rồi kubectl dùng được ngay
/home/tutruong/project/Phase3-TF3-Infra-Sentinel/scripts/kube-tunnel.sh
# Tunnel tự đóng sau ~10-20 phút idle. `connection refused` = chạy lại script.

# Cluster: techx-corp-tf3, ap-southeast-1, namespace techx-tf3
# ArgoCD UI: https://argocd.arthur-ngo.org (SSO, không cần kubectl)
```

Worktree đang làm việc:
`/home/tutruong/project/Phase3-TF3-Infra-Sentinel/.claude/worktrees/aiops-engine-argocd-adoption`

---

## 4. Đã xong (đã merge vào `main`)

| PR | Nội dung | Bằng chứng |
|---|---|---|
| — | **Phase 0:** xoá `ingress/aiops-engine-ingress` khỏi cluster | endpoint public trả `HTTP 000`; manifest lưu ở `docs/evidence/aiops-engine/` |
| **#519** | Adopt 7 tài nguyên vào ArgoCD | `revision` 68→**68**, cùng pod, `RESTARTS=0` |
| **#521** | Gỡ label `managed-by: argocd` dán tay | sync xong, revision vẫn 68 |
| **#522** | Hồ sơ + sửa comment `PriorityClass` nói sai sự thật | — |
| **#532** | Kéo source về + CI Trivy/Cosign | 80 file, quét secret sạch 2 lần |

Zero-downtime đã thực chứng **hai lần** (sau #519 và sau #521): revision không đổi, tên pod
không đổi, `RESTARTS=0`.

---

## 5. VIỆC TIẾP THEO — theo thứ tự

### 5.1. Gỡ tắc Trivy gate (việc ngay)

**Plan:** `docs/superpowers/plans/2026-07-28-aiops-image-trivy-unblock.md`

Build đầu tiên (run `30366047175`) **fail ở bước Trivy — đúng như thiết kế**. Push và Cosign
đều `skipped`, **không ảnh nào lọt lên ECR**.

6 lỗi HIGH có bản vá, **hai nhóm xử lý khác hẳn nhau**:

| Nhóm | Chi tiết | Cách xử lý |
|---|---|---|
| **Python (2)** | `wheel` 0.45.1 (CVE-2026-24049), `jaraco.context` 5.3.0 (CVE-2026-23949) | **False positive** — bản vendored trong `setuptools/_vendor/`, không nằm trên đường chạy. `shopping-copilot/.trivyignore` đã ghi nhận **đúng 2 CVE này**. Đưa vào `.trivyignore` kèm tài liệu. |
| **kubectl (4)** | `golang.org/x/net` v0.49.0 → cần 0.55.0. CVE-2026-25681, -27136, -33814, -39821 | **Lỗ hổng thật.** Ghim phiên bản kubectl + đánh giá từng CVE. **Tuyệt đối không nhét vào `.trivyignore` cho build xanh.** |

Plan có 3 task. Task 1–2 làm được ngay. **Task 3 (bỏ hẳn binary kubectl) cần AIO02 đồng ý** vì
nó đổi code của họ — nhưng đó là hướng sửa gốc: gỡ binary xoá cả 4 CVE lẫn bước tải file lúc
build. Thư viện thay thế `kubernetes-36.0.3` **đã có sẵn trong ảnh** mà không file nào import.

### 5.2. Repoint manifest sang ảnh mới (sau khi 5.1 xong, CẦN CỔNG CHẶN)

**Plan:** `docs/superpowers/plans/2026-07-28-aiops-engine-source-import.md` — **Task 4**

**⚠️ Đây không phải đổi cách tham chiếu, đây là deploy code mới.** Source ở `d68dd97`
(27/07 20:32) **mới hơn** ảnh `IF-v63` đang chạy (push 27/07 15:38, sớm hơn ~5 tiếng). Build
từ source hiện tại ra ảnh **chưa từng chạy production**.

Điều kiện bắt buộc: user duyệt + AIO02 xác nhận code sẵn sàng + làm giờ ít traffic.

### 5.3. Phase 2 — dựng IRSA, giết static admin key (QUAN TRỌNG NHẤT về bảo mật)

**Spec:** `docs/superpowers/specs/2026-07-28-aiops-engine-gitops-adoption-design.md` §Phase 2.
Chưa có plan chi tiết — cần viết.

**Thứ tự bắt buộc, đảo là engine chết:** dựng IRSA role bằng Terraform → verify engine chạy
được bằng IRSA → **rồi mới** gỡ env static key → **rồi mới** vô hiệu access key.

### 5.4. Phase 3 — NetworkPolicy, khôi phục Slack

Spec §Phase 3. **Phải phối hợp CDO01** — xem §8.

---

## 6. Lỗ hổng bảo mật: cái nào đóng, cái nào còn mở

### ✅ Đã đóng — API remediation public không xác thực

`ingress/aiops-engine-ingress` dùng `scheme: internet-facing`, path prefix `/remediation`.
Xác minh được từ Internet trước khi xoá:

```
GET http://k8s-techxtf3-aiopseng-...elb.amazonaws.com/remediation/mode
→ 200 {"status":"success","mode":"SLACK_HUMAN_APPROVAL",...}
```

`grep -rniE 'signing_secret|x-slack-signature|hmac|verify_slack'` toàn bộ engine → **0 kết
quả**. Không xác thực chữ ký Slack ở bất kỳ đâu. Bất kỳ ai cũng POST được
`/remediation/approve`, `/remediation/mode`, `/remediation/stop`.

Đã xoá 28/07. **Hệ quả:** nút Approve/Reject trên Slack của AIO02 ngừng hoạt động cho tới
Phase 3 — đây là đánh đổi có chủ đích (fail-safe).

### 🔴 CÒN MỞ — pod mang credential admin toàn account

Deployment inject `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` từ `secret/aiops-engine-secrets`.
Truy vết: IAM user `aio2-admin-team` → group `AIO2-Admin` → **`AdministratorAccess`**.

ServiceAccount có annotation `eks.amazonaws.com/role-arn: .../tf3-aiops-engine-irsa-role`
nhưng `aws iam get-role` trả **`NoSuchEntity`** — role không tồn tại. Kể cả nếu có, env var
vẫn đè lên IRSA. Engine sống hoàn toàn nhờ key admin dài hạn.

**Phase 0 chỉ bịt đường vào từ Internet. Credential vẫn nguyên.** Đây là việc §5.3.

### 🟡 CÒN MỞ — không có NetworkPolicy

Live: `kubectl get netpol -n techx-tf3 | grep -c aiops` → `0`. Xem §8.

---

## 7. Bẫy đã biết — đọc để khỏi vấp lại

**`kubectl diff` không còn là cổng kiểm chứng sạch.** Từ khi ArgoCD adopt xong, nó **luôn**
hiện nhiễu cố định (annotation `argocd.argoproj.io/tracking-id` như bị xoá, `generation` tăng)
trên **mọi** tài nguyên trong thư mục, kể cả file không đụng tới — vì `kubectl diff` chạy
dry-run client-side, không biết cơ chế annotation-tracking của ArgoCD. Đã kiểm chứng bằng
worktree tạm ở commit trước.

Dùng cái này thay thế:
```bash
kubectl get application aiops-engine -n argocd \
  -o jsonpath='{range .status.resources[*]}{.kind}/{.name}: {.status}{"\n"}{end}'
```

**Đổi trường `image` là pod restart**, kể cả khi trỏ về đúng ảnh đang chạy — pod-template-hash
đổi. Engine 1 replica nên có gián đoạn ngắn.

**`PriorityClass low-priority` thực chất là HIGH priority.** `value: 1000` +
`PreemptLowerPriority`, trong khi **44/44 pod trong `techx-tf3` ở priority 0**. Tên đánh lừa:
mỗi 19:00 UTC Chủ Nhật, cụm chật là job training **evict một pod production**. `value` và
`preemptionPolicy` là **immutable** — sửa phải xoá và tạo lại PriorityClass. Chưa xử lý.

**`Dockerfile` của AIO02, 2 vấn đề chưa sửa:**
- Không có chỉ thị `USER` → ảnh mặc định chạy root; chỉ nhờ `securityContext.runAsUser: 10001`
  của pod mới thành non-root.
- `curl` kubectl `latest` từ `dl.k8s.io/release/stable.txt` mỗi lần build → không tái lập
  được. Plan §5.1 Task 2 sửa cái này.

**Khuyết tật khuôn CI (có sẵn, áp cho cả 2 workflow):** workflow scan ảnh build lần 1 nhưng
**push ảnh build lần 2**, không tái dùng đúng ảnh đã qua gate. Có trong
`build-push-copilot.yml` đang chạy thật. Đáng lo hơn với aiops vì Dockerfile của họ
`apt-get update` + tải kubectl mỗi lần build.

**Ba thứ đã cố ý loại khi import source, đừng kéo lại:**

| Loại | Vì sao |
|---|---|
| `models/` (7 joblib, 14MB) | Kho thật là S3 `tf3-aiops-models-197826770971/current/`. `.dockerignore` của họ vốn đã loại khỏi ảnh. |
| `scratch/`, `audit_log.jsonl` | Script debug và state runtime. |
| `k8s/` (5 manifest) | **Nguy hiểm.** `ingress.yaml` chính là ingress internet-facing đã xoá ở Phase 0; `rbac.yaml` bind vào SA `default` với `pods/exec` + `pods: delete`. Ai `kubectl apply -f` là mở lại lỗ hổng. |
| `main.tf` | Terraform root **thứ hai**, không backend (state local), tạo `aws_opensearchserverless_collection` + Bedrock KB + S3 `force_destroy`. |

---

## 8. Va chạm với CDO01 — đọc trước khi làm Phase 3

CDO01 **đã có sẵn** NetworkPolicy cho chính workload này:
`gitops/infrastructure/network-policy-staged/07-aiops-engine.yaml`
(tên `aiops-engine-platform-policy`, annotate `promotion-blocked: "true"`,
`kubernetes-api-dependency: "unverified"`).

Spec Phase 3 lại lên kế hoạch tạo **file mới** `gitops/aiops-engine/networkpolicy.yaml` thuộc
**ArgoCD app khác**. Nếu cả hai cùng lên: nhẹ thì hai policy trùng chức năng do hai owner
quản; nặng thì trùng tên → hai app cùng `selfHeal` giành một object, `OutOfSync` lật qua lật
lại vĩnh viễn.

**Phải chọn một owner, không viết lại.** Phối hợp với CDO01.

Hai điểm kỹ thuật cho NetworkPolicy (bài học `docs/postmortem/0012-...` — batch netpol dùng
`podSelector` thay `ipBlock` đã gây outage 30 phút ngày 20/07):
- Trên VPC CNI, egress rule bằng `podSelector` tới ClusterIP **không hoạt động**. Cần
  `ipBlock` ClusterIP `/32`: `172.20.0.1/32` (kube-apiserver) và `172.20.0.10/32` (DNS).
- File staged của CDO01 dính lỗi ngược lại: `0.0.0.0/0 except 172.16.0.0/12` **loại trừ** mất
  dải ClusterIP.

**Pod của CronJob training không có label nào** (`jobTemplate.metadata` và pod template đều là
`{}`). Policy staged chỉ chọn `app: aiops-engine`, còn `90-default-deny-all.yaml` chọn
`podSelector: {}` tức **toàn bộ pod**. Ngày CDO01 promote default-deny, job training mất DNS +
Prometheus + S3 và treo đủ 3600s **mỗi tuần**. Vá: thêm `app: aiops-engine` vào pod template
của `jobTemplate` (đổi jobTemplate không restart gì).

---

## 9. Ngoài phạm vi

- **`chaos-engine`** (`AIOps/chaos-engine/` ở repo AIO02): chỉ có `Dockerfile` + source +
  docs, **không manifest k8s nào**, không image trong ECR. Chưa deploy. Nếu AIO02 muốn deploy
  thì làm spec riêng. **Chaos Mesh** (công cụ OSS) là thứ khác và đã ở trong ArgoCD từ trước
  (`gitops/apps/chaos-mesh-app.yaml`, auto-sync tắt có chủ đích).
- **`AIE1/`, `AIE2/`** ở repo AIO02: `AIE1` là bản sao platform/chart đã có trong repo này;
  `AIE2/shopping-copilot` đã ở GitOps từ trước (`gitops/shopping-copilot/`).
- **Sửa code Python của engine** — việc AIO02, trừ Task 3 của plan §5.1 (đã thoả thuận).

---

## 10. Câu hỏi đang chờ AIO02

1. **Access key `AKIA…` của `aio2-admin-team` có dùng ở đâu khác không?** (CI của họ, máy cá
   nhân?) — chặn Phase 2. Vô hiệu bằng `Inactive` trước, đừng xoá ngay.
2. **CronJob training đang hỏng.** Hai Job `Failed`: `-29741460` và `-29751540`, đều
   `DeadlineExceeded` sau khi chạy đủ 3600s. Bằng chứng từ S3: job `-29741460` **đã ghi trọn 7
   model** lên `archive/20260721-080819/` lúc `08:08:25Z` (8 phút sau khi bắt đầu) rồi treo
   thêm 52 phút — tức Prometheus + S3 + train đều chạy được, nó chết ở bước **sau archive**,
   không promote sang `current/`. Job 26/07 (`IF-v25`) **không sinh archive nào** → hành vi
   khác hẳn. Model trong `current/` ghi lần cuối `2026-07-21T14:35:28Z` = **7 ngày**.
   Ngoài ra job `-29741460` chạy **trễ 37 giờ** so với slot lịch `2026-07-19T19:00:00Z` —
   CronJob không đặt `startingDeadlineSeconds`, dùng `concurrencyPolicy: Forbid`, nên lịch
   19/07 cũng đã lỡ âm thầm.
3. **CronJob đang ở `IF-v25`, engine ở `IF-v63`** — lệch 38 bản. Nâng cronjob lên cùng bản có
   an toàn không, hay `train_anomaly_model_eks.py` đã đổi interface?
4. **`main.tf` trong source của họ có phải nguồn của khoản OpenSearch Serverless mồ côi
   ~$80,6/tuần không?** Nó tạo `aws_opensearchserverless_collection` bằng state local.
5. **Có đồng ý thêm xác thực chữ ký Slack (`X-Slack-Signature` + `SLACK_SIGNING_SECRET`) ở tầng
   app không?** — cần cho Phase 3 khi khôi phục luồng duyệt.
6. **Task 3 của plan §5.1** (bỏ binary kubectl, dùng Python client) — có đồng ý không?

---

## 11. Quy tắc làm việc trong repo này

- **Không push thẳng `main`.** Branch từ `origin/main` sau `git fetch`, merge qua PR.
- **Commit message không kèm `Co-Authored-By`** hay chữ ký nền tảng (`.claude/rules/git.md`).
- **Không đọc/sửa `CLAUDE.md`** (quy tắc trong `CLAUDE.local.md`).
- **Luật cấm tuyệt đối (disqualify):** không gỡ/đổi hướng `flagd`, không đổi TOKEN/URI trong
  `values-flagd-sync.yaml`, không gỡ `/flagservice` khỏi Envoy, không gỡ filter
  `envoy.filters.http.fault` trong `frontend-proxy`, không commit secret thật vào file tracked.
- Với thao tác hủy hoại hoặc chạm production: xác nhận với user trước, làm giờ ít traffic.
- ArgoCD Application chạy `prune: true` + `selfHeal: true` — mọi thứ trong `gitops/aiops-engine/`
  áp thẳng lên production, và tài nguyên thuộc app mà thiếu trong git **sẽ bị xoá**.
