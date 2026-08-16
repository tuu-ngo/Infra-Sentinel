# Gỡ tắc Trivy gate cho image aiops-engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đưa image `tf-2-ai-engine` qua được Trivy gate và push lên ECR có chữ ký Cosign, mà không che giấu lỗ hổng thật.

**Architecture:** Xử lý hai nhóm lỗi bằng hai cách khác nhau — nhóm false positive vendored thì ghi vào `.trivyignore` có tài liệu; nhóm kubectl thì ghim phiên bản để build tái lập được rồi đánh giá riêng. Task 3 (bỏ hẳn binary kubectl) là hướng sửa gốc, tách riêng vì cần AIO02 đổi code.

**Tech Stack:** Trivy v0.72.0, Docker buildx, GitHub Actions, ECR `tf-2-ai-engine`, Python 3.10.

## Global Constraints

- Account `197826770971`, region `ap-southeast-1`, ECR repo ảnh `tf-2-ai-engine`.
- AWS profile `default` — **không** `export AWS_PROFILE=techx-new`.
- **Không push thẳng `main`.** Branch từ `origin/main` sau `git fetch`, merge qua PR.
- Commit message **không** kèm `Co-Authored-By` hay chữ ký nền tảng (`.claude/rules/git.md`).
- **Không** sửa hay đọc `CLAUDE.md` (quy tắc `CLAUDE.local.md`).
- **Không** đụng `flagd` / `values-flagd-sync.yaml` / filter `envoy.filters.http.fault` — disqualify.
- Chỉ chạy kubectl read-only (`get`, `diff`); mọi mutation cluster cần user duyệt trước.
- **Nguyên tắc bất di bất dịch:** `.trivyignore` chỉ dành cho false positive **chứng minh được**. CVE có bản vá và thật sự áp dụng thì phải vá, không được nhét vào để build xanh.

---

## Bối cảnh đã kiểm chứng

Build đầu tiên: run `30366047175`, `completed/failure`. Gate hoạt động **đúng thiết kế** — bước
`Scan candidate with Trivy` fail, ba bước `Push` / `Install Cosign` / `Sign and verify` đều
`skipped`. **Không ảnh nào lọt lên ECR.**

Tổng 6 lỗi HIGH **có bản vá** (`--ignore-unfixed` đã lọc hết CVE nền Debian không vá được;
tầng `debian 13.6` báo 0):

| Nhóm | Package | CVE | Đang có | Bản vá |
|---|---|---|---|---|
| Python | `jaraco.context` (METADATA) | CVE-2026-23949 | 5.3.0 | 6.1.0 |
| Python | `wheel` (METADATA) | CVE-2026-24049 | 0.45.1 | 0.46.2 |
| kubectl (gobinary) | `golang.org/x/net` | CVE-2026-25681 | v0.49.0 | 0.55.0 |
| kubectl (gobinary) | `golang.org/x/net` | CVE-2026-27136 | v0.49.0 | 0.55.0 |
| kubectl (gobinary) | `golang.org/x/net` | CVE-2026-33814 | v0.49.0 | 0.53.0 |
| kubectl (gobinary) | `golang.org/x/net` | CVE-2026-39821 | v0.49.0 | 0.55.0 |

**Nhóm Python là false positive đã có tiền lệ trong repo này.** Cả hai CVE nằm ở bản
**vendored bên trong build tooling của setuptools**
(`usr/local/lib/python3.10/site-packages/setuptools/_vendor/...`), không phải dependency
của ứng dụng, không nằm trên đường chạy. `shopping-copilot/.trivyignore` đã ghi nhận và bỏ
qua **đúng hai CVE này** với cùng lý do (khác mỗi `python3.11` vs `python3.10`).

**Nhóm kubectl là lỗ hổng thật trong binary.** `Dockerfile` kéo bản `stable` mới nhất
(`dl.k8s.io/release/stable.txt`) mà vẫn dính, nên ghim sang bản khác gần như chắc chắn
không vá được — cần kiểm chứng ở Task 2 Step 1 thay vì giả định.

**kubectl không gỡ được ngay.** Engine shell-out kubectl cho mọi hành động remediation —
`aiops-engine/main.py:552-563` dựng chuỗi lệnh `kubectl -n techx-tf3 rollout restart ...`,
`scale deploy/... --replicas=N`. Gỡ binary là remediation chết.

**Nhưng có đường ra gốc.** `requirements.txt` khai `kubernetes>=26.0.0` và ảnh đã cài
`kubernetes-36.0.3`, trong khi **không file Python nào `import kubernetes`**
(`grep -rn '^from kubernetes\|^import kubernetes' aiops-engine/*.py` → rỗng). Thư viện client
chính thức đã nằm sẵn trong ảnh mà không được dùng. Chuyển sang nó thì gỡ được binary,
xoá cả 4 CVE lẫn bước `curl latest` làm build không tái lập. Đó là Task 3.

---

## Task 1: Ghi nhận 2 false positive vendored vào `.trivyignore`

**Files:**
- Modify: `aiops-engine/.trivyignore`

**Interfaces:**
- Produces: `.trivyignore` có 2 mục kèm tài liệu — Task 2 chạy build dựa trên nó

- [ ] **Step 1: Nhánh mới**

```bash
cd /home/tutruong/project/Phase3-TF3-Infra-Sentinel
git fetch origin
git checkout -b fix/aiops-trivy-gate origin/main
```

- [ ] **Step 2: Tự xác minh đây thật sự là bản vendored, đừng tin plan**

```bash
grep -n 'CVE-2026-24049\|CVE-2026-23949\|_vendor' shopping-copilot/.trivyignore
```

Expected: thấy cả 2 CVE và phần giải thích nhắc `setuptools/_vendor`.

Tải report JSON của build đã fail để xác nhận đường dẫn thật sự nằm trong `_vendor`:

```bash
gh run download 30366047175 -n trivy-aiops-30366047175 -D /tmp/trivy-aiops
python3 - <<'PY'
import json,glob
for f in glob.glob('/tmp/trivy-aiops/*.json'):
    d=json.load(open(f))
    for r in d.get('Results',[]):
        for v in r.get('Vulnerabilities',[]):
            if v['VulnerabilityID'] in ('CVE-2026-24049','CVE-2026-23949'):
                print(v['VulnerabilityID'], '|', r.get('Target'), '|', v.get('PkgPath') or v.get('PkgName'))
PY
```

Expected: đường dẫn chứa `setuptools/_vendor`.

**Nếu đường dẫn KHÔNG chứa `_vendor`** (tức là `wheel`/`jaraco.context` được cài như
dependency thật): **DỪNG.** Khi đó nó không phải false positive — phải ghim phiên bản trong
`requirements.txt`, không được cho vào `.trivyignore`. Báo lại cho người giao việc.

- [ ] **Step 3: Thêm 2 mục vào `aiops-engine/.trivyignore`**

Giữ nguyên phần header sẵn có, nối vào cuối:

```
# --- Vendored trong build tooling của setuptools, không nằm trên đường chạy ---
# Cả hai được Trivy báo trên bản sao VENDORED bên trong setuptools, không phải
# dependency của ứng dụng:
#   usr/local/lib/python3.10/site-packages/setuptools/_vendor/wheel-0.45.1.dist-info
#   usr/local/lib/python3.10/site-packages/setuptools/_vendor/jaraco.context-5.3.0.dist-info
# setuptools chỉ chạy lúc `pip install` trong giai đoạn build; runtime của engine
# (uvicorn + main.py) không import chúng. Nâng setuptools không đổi được các bản vendored này.
# Cùng lý do và cùng 2 CVE đã ghi nhận ở shopping-copilot/.trivyignore.
# Xác minh lại: 2026-07-28, Trivy v0.72.0, run 30366047175.
CVE-2026-24049
CVE-2026-23949
```

- [ ] **Step 4: Xác nhận chưa vô tình bỏ qua CVE kubectl**

```bash
grep -cE 'CVE-2026-(25681|27136|33814|39821)' aiops-engine/.trivyignore
```

Expected: `0`. Bốn CVE kubectl **không được** vào file này ở Task 1.

- [ ] **Step 5: Commit**

```bash
git add aiops-engine/.trivyignore
git commit -m "fix(aiops): ghi nhận 2 CVE vendored-setuptools vào .trivyignore

wheel 0.45.1 (CVE-2026-24049) và jaraco.context 5.3.0 (CVE-2026-23949) được Trivy
báo trên bản sao vendored bên trong setuptools build tooling, không phải dependency
ứng dụng và không nằm trên đường chạy runtime.

Cùng 2 CVE, cùng lý do đã ghi nhận ở shopping-copilot/.trivyignore.

4 CVE golang.org/x/net trong binary kubectl CỐ Ý không đưa vào đây - chúng là lỗ
hổng thật, xử lý riêng."
```

---

## Task 2: Ghim phiên bản kubectl và đánh giá 4 CVE còn lại

**Files:**
- Modify: `aiops-engine/Dockerfile`
- Modify: `aiops-engine/README.md`
- Có thể modify: `aiops-engine/.trivyignore` (chỉ khi Step 4 kết luận như vậy)

**Interfaces:**
- Consumes: `.trivyignore` từ Task 1
- Produces: build qua được gate, hoặc kết luận có tài liệu rằng chưa qua được

**Vì sao ghim dù không vá được CVE:** `Dockerfile` hiện chạy
`curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"`.
Hai lần build cách nhau vài ngày cho ra hai ảnh khác nhau mà không ai biết, và một thay đổi
phía upstream lọt thẳng vào ảnh production. Ghim là điều kiện cần để bất kỳ kết luận bảo mật
nào về ảnh này có giá trị quá một ngày.

- [ ] **Step 1: Xác định phiên bản kubectl đang bị kéo về và tìm bản đã vá**

```bash
curl -sL https://dl.k8s.io/release/stable.txt
```

Ghi lại giá trị này — đó là bản build hôm nay lấy.

Tra xem có bản kubectl nào ship `golang.org/x/net` >= 0.55.0 chưa. Kiểm nhanh vài bản gần
nhất bằng cách quét trực tiếp binary:

```bash
for V in v1.35.0 v1.34.0 v1.33.0; do
  curl -sLO "https://dl.k8s.io/release/$V/bin/linux/amd64/kubectl" && chmod +x kubectl
  echo -n "$V: "
  trivy fs --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --format json kubectl 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(sorted({v['VulnerabilityID'] for r in d.get('Results',[]) for v in r.get('Vulnerabilities',[])}))"
  rm -f kubectl
done
```

Nếu máy không có `trivy`, cài theo hướng dẫn tại <https://trivy.dev/> hoặc chạy bằng docker:
`docker run --rm -v "$PWD:/w" aquasec/trivy:0.72.0 fs --scanners vuln ...`

- [ ] **Step 2: Ghim phiên bản trong `Dockerfile`**

Thay khối `curl` động bằng phiên bản cố định. Chọn bản **sạch nhất** tìm được ở Step 1; nếu
mọi bản đều dính như nhau thì ghim đúng bản `stable` hiện tại.

Sửa dòng trong `aiops-engine/Dockerfile` từ:

```dockerfile
    && curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
```

thành (thay `<VERSION>` bằng bản đã chọn, ví dụ `v1.35.0`):

```dockerfile
    # Ghim phiên bản kubectl: bản "stable" động làm build không tái lập được và cho
    # một thay đổi upstream lọt thẳng vào ảnh production. Nâng bản là một PR có chủ đích.
    && curl -LO "https://dl.k8s.io/release/<VERSION>/bin/linux/amd64/kubectl" \
```

Thêm kiểm tra checksum ngay sau đó (kubectl công bố `.sha256` cho từng bản):

```dockerfile
    && curl -LO "https://dl.k8s.io/release/<VERSION>/bin/linux/amd64/kubectl.sha256" \
    && echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check \
    && rm kubectl.sha256 \
```

- [ ] **Step 3: Build lại local và xem còn CVE nào**

```bash
cd /home/tutruong/project/Phase3-TF3-Infra-Sentinel
docker build -f aiops-engine/Dockerfile -t aiops-local-test aiops-engine
trivy image --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed \
  --ignorefile aiops-engine/.trivyignore aiops-local-test
```

Expected một trong hai:
- **Sạch** → sang Step 5.
- **Còn 4 CVE `golang.org/x/net`** → sang Step 4.

- [ ] **Step 4: Nếu vẫn còn 4 CVE kubectl — quyết định có tài liệu**

Đây là chỗ dễ sai nhất của cả plan. **Không** nhét 4 CVE vào `.trivyignore` chỉ để build xanh.

Tra từng CVE (`https://nvd.nist.gov/vuln/detail/<CVE>`) và trả lời: lỗ hổng nằm ở đường
**server** hay đường **client** của `golang.org/x/net`? kubectl trong ảnh này chỉ được dùng
làm **client** gọi tới kube-apiserver của chính cụm mình — nó không phục vụ request nào từ
bên ngoài, và endpoint nó nói chuyện là API server tin cậy.

Chọn một trong ba, ghi rõ lý do:

**(a) CVE chỉ áp dụng cho đường server, hoặc cần một endpoint độc hại mà kubectl ở đây không
bao giờ gọi tới** → được đưa vào `.trivyignore`, kèm mục ghi đủ: mã CVE, đường dẫn
`usr/local/bin/kubectl`, phiên bản kubectl đã ghim, câu trả lời cho câu hỏi trên, và ngày
đánh giá. Thiếu bất kỳ phần nào là không đủ tiêu chuẩn của file này.

**(b) CVE áp dụng cho đường client và khai thác được** → **không** ignore. Dừng lại, báo cho
người giao việc. Khi đó Task 3 (bỏ binary kubectl) thành việc chặn, không phải việc sau.

**(c) Không kết luận được** → **không** ignore. Báo lại. Đoán mò rồi suppress là cách một lỗ
hổng thật đi vào production kèm một tờ giấy nói nó an toàn.

- [ ] **Step 5: Cập nhật `aiops-engine/README.md`**

Mục "Hai điểm cần AIO02 xử lý trong `Dockerfile`" hiện nói kubectl kéo bản `latest`. Sửa cho
khớp: đã ghim `<VERSION>` kèm kiểm checksum; nâng bản là PR có chủ đích. Giữ nguyên mục nói
về việc thiếu chỉ thị `USER` (chưa xử lý).

Thêm một mục ngắn ghi lại kết quả đánh giá 4 CVE `golang.org/x/net` ở Step 4 — người sau đọc
`.trivyignore` sẽ cần biết vì sao.

- [ ] **Step 6: Commit và mở PR**

```bash
git add aiops-engine/Dockerfile aiops-engine/README.md aiops-engine/.trivyignore
git commit -m "fix(aiops): ghim phiên bản kubectl trong image + kiểm checksum

Dockerfile trước đây kéo kubectl 'stable' mới nhất mỗi lần build: build không tái
lập được và một thay đổi upstream lọt thẳng vào ảnh production. Nay ghim <VERSION>
kèm sha256sum --check.

<Ghi kết quả đánh giá 4 CVE golang.org/x/net ở đây>"
git push -u origin fix/aiops-trivy-gate
gh pr create --base main --title "fix(aiops): gỡ tắc Trivy gate cho image aiops-engine" --body "<mô tả 2 nhóm lỗi và cách xử lý từng nhóm>"
```

- [ ] **Step 7: Sau khi merge — chạy lại build**

```bash
gh workflow run build-push-aiops.yml --ref main
gh run watch "$(gh run list --workflow=build-push-aiops.yml --limit 1 --json databaseId -q '.[0].databaseId')"
```

Expected: toàn bộ bước xanh, gồm `Push`, `Sign and verify the digest`.

Lấy digest để ghim:

```bash
gh run view <run-id> --log | grep -A3 'Pin this in'
```

**Chưa repoint manifest ở đây.** Xem plan `2026-07-28-aiops-engine-source-import.md` Task 4:
ảnh mới build từ source `d68dd97` (27/07 20:32) **mới hơn** `IF-v63` đang chạy (push 27/07
15:38), nên repoint là deploy code mới chứ không phải đổi cách tham chiếu — cần AIO02 xác
nhận và user duyệt.

---

## Task 3: Bỏ hẳn binary kubectl, dùng Python kubernetes client (hướng sửa gốc)

**Files:**
- Modify: `aiops-engine/main.py` (và `remediation_handler.py` nếu nó cũng shell-out)
- Modify: `aiops-engine/Dockerfile`

**⚠️ Task này đổi code của AIO02 — cần họ đồng ý trước khi bắt đầu.** Nó cũng đổi hành vi
remediation trên production, nên phải có bài test trước khi merge.

**Vì sao đáng làm:** gỡ binary kubectl xoá cả 4 CVE `golang.org/x/net`, xoá luôn bước tải
file lúc build (giảm bề mặt supply-chain), và giảm kích thước ảnh. Thư viện thay thế
`kubernetes-36.0.3` **đã nằm sẵn trong ảnh** vì `requirements.txt` khai `kubernetes>=26.0.0`
— hiện không file nào import nó.

Một lợi ích phụ về bảo mật: cách hiện tại dựng **chuỗi lệnh shell** rồi lọc bằng blacklist từ
khoá cấm. Blacklist là mô hình sai cho việc này — client thư viện nhận tham số có kiểu, không
có chuỗi để mà thoát ra.

- [ ] **Step 1: Liệt kê đầy đủ mọi chỗ shell-out**

```bash
grep -rn 'kubectl' aiops-engine/*.py
grep -rn 'subprocess\|os.system\|shell=True' aiops-engine/*.py
```

Đã biết `aiops-engine/main.py:552-563` dựng các lệnh `rollout restart`, `rollout undo`,
`scale deploy --replicas=N`. Xác nhận không còn chỗ nào khác.

- [ ] **Step 2: Ánh xạ từng lệnh sang lời gọi thư viện**

| Lệnh hiện tại | Thay bằng |
|---|---|
| `kubectl -n techx-tf3 scale deploy/<svc> --replicas=N` | `AppsV1Api.patch_namespaced_deployment_scale` |
| `kubectl -n techx-tf3 rollout restart deployment/<svc>` | `patch_namespaced_deployment` với annotation `kubectl.kubernetes.io/restartedAt` |
| `kubectl -n techx-tf3 rollout undo deployment/<svc>` | đọc ReplicaSet cũ rồi patch lại pod template — **không có API một-lệnh**, cần cẩn thận |
| `kubectl -n techx-tf3 rollout restart rollout/checkout-rollout` | `CustomObjectsApi.patch_namespaced_custom_object` (`argoproj.io/v1alpha1`, `rollouts`) |

`rollout undo` là chỗ khó nhất — nó không phải một lời gọi API mà là logic phía client của
kubectl. Nếu quá phức tạp, cân nhắc giữ lại một đường riêng cho nó và bàn với AIO02.

- [ ] **Step 3: Viết test trước**

Có sẵn `aiops-engine/tests/`. Thêm test dùng mock cho client kubernetes, khẳng định mỗi hành
động remediation gọi đúng API với đúng namespace/tên/tham số. Chạy cho fail trước khi sửa
code.

```bash
cd aiops-engine && python -m pytest tests/ -v
```

- [ ] **Step 4: Sửa code cho test xanh**

- [ ] **Step 5: Gỡ kubectl khỏi `Dockerfile`**

Xoá cả khối `curl`/`install`/`rm kubectl`. `curl` vẫn giữ nếu probe cần.

- [ ] **Step 6: Build lại và xác nhận 4 CVE biến mất**

```bash
docker build -f aiops-engine/Dockerfile -t aiops-nokubectl aiops-engine
trivy image --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed \
  --ignorefile aiops-engine/.trivyignore aiops-nokubectl
```

Expected: không còn mục `usr/local/bin/kubectl (gobinary)`.

Nếu Step 4 của Task 2 đã đưa 4 CVE vào `.trivyignore`, **gỡ chúng ra ở đây** — chúng không
còn tồn tại, để lại là rác gây hiểu nhầm cho người sau.

- [ ] **Step 7: Test trên cụm trước khi merge**

Cần user duyệt. Kiểm rằng một hành động remediation thật vẫn chạy đúng end-to-end. Đây là
đường mà engine dùng để tự sửa production — hỏng ở đây nghĩa là mất khả năng khắc phục sự cố.

---

## Tiêu chí thành công

| # | Tiêu chí | Cách verify |
|---|---|---|
| 1 | Không CVE nào bị suppress mà thiếu tài liệu | mỗi mục trong `.trivyignore` có mã CVE, đường dẫn, lý do, ngày đánh giá |
| 2 | 4 CVE kubectl không bị suppress một cách vô căn cứ | Task 2 Step 4 kết luận rõ (a)/(b)/(c) và ghi vào README |
| 3 | Build tái lập được | `Dockerfile` không còn `stable.txt`; có `sha256sum --check` |
| 4 | Image qua gate và được ký | run `build-push-aiops.yml` xanh hết, gồm bước `Sign and verify` |
| 5 | (Task 3) Không còn binary kubectl | Trivy không báo target `usr/local/bin/kubectl` |
| 6 | (Task 3) Remediation vẫn hoạt động | test suite xanh + một hành động thật trên cụm |

## Rủi ro

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Suppress 4 CVE kubectl cho nhanh rồi quên | Cao | Task 2 Step 4 bắt buộc kết luận (a)/(b)/(c); (b) và (c) đều cấm ignore |
| Ghim kubectl vào bản cũ hơn, thêm CVE khác | Trung bình | Step 1 quét từng bản trước khi chọn |
| Task 3 làm hỏng remediation | Cao | Viết test trước; `rollout undo` không có API tương đương một-lệnh; cần AIO02 duyệt và test trên cụm |
| Ảnh mới khác code đang chạy | Cao | Không repoint trong plan này; xem plan source-import Task 4 |

## Ngoài phạm vi

- Repoint manifest sang digest mới — plan `2026-07-28-aiops-engine-source-import.md` Task 4.
- Thêm chỉ thị `USER` vào `Dockerfile` (ảnh mặc định chạy root) — ghi trong README, việc AIO02.
- Khuyết tật khuôn CI: workflow scan ảnh build lần 1 nhưng push ảnh build lần 2. Có sẵn trong
  `build-push-copilot.yml` đang chạy thật, áp cho cả hai workflow — sửa là việc riêng.
