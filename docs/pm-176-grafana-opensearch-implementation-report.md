# PM-176 — Báo cáo triển khai immutable Grafana OpenSearch plugin

**Ngày thực hiện:** 26–27/07/2026  
**Môi trường:** production, account `197826770971`, region
`ap-southeast-1`, EKS `techx-corp-tf3`, namespace `techx-tf3`  
**Nguồn deploy:** nhánh `main` qua ArgoCD  
**Trạng thái báo cáo:** core image/plugin/datasource đã triển khai và xác minh;
full Definition of Done còn chờ PR #426 và destructive recreation test.

## 1. Kết luận điều hành

PM-176 bắt đầu từ một dependency nguy hiểm: Grafana tải
`grafana-opensearch-datasource` từ public internet trong lúc Pod khởi động.
Nếu NetworkPolicy của PR #426 chặn egress trước khi sửa dependency này, Pod
mới có thể không có plugin và datasource `webstore-logs` sẽ hỏng.

Phần core đã hoàn tất:

- plugin `grafana-opensearch-datasource` version `2.34.0` nằm sẵn tại
  `/opt/grafana/plugins` trong image TF3;
- production dùng ECR image pin bằng tag và digest;
- runtime installer, default preinstall, auto-update và plugin admin đã bị
  vô hiệu;
- image build/scan cả `linux/amd64` và `linux/arm64`;
- Trivy blocking gate không có HIGH/CRITICAL;
- Grafana đăng ký plugin thành công mà không tải plugin lúc startup;
- datasource `webstore-logs` trả `HTTP 200`,
  `Index OK. Time field name OK.`;
- ArgoCD `techx-corp` đang `Synced/Healthy`.

Tuy nhiên, không được đánh dấu **full PM-176 Done** theo spec gốc:

- [PR #426](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/426)
  vẫn `OPEN`;
- NetworkPolicy live của Grafana hiện chỉ có `policyTypes: [Ingress]`, chưa
  enforce `Egress`;
- chưa chạy hai lần Pod recreation trong khi egress policy của #426 đang
  enforce;
- chưa lưu một query thật từ dashboard qua Grafana `POST /api/ds/query` dưới
  egress policy;
- identity readonly không có `pods/exec`, nên chưa đọc trực tiếp
  `TF3-PROVENANCE` trong Pod. CI đã kiểm tra file này trong image candidate.

Vì vậy trạng thái chính xác là:

```text
Core immutable rollout: PASS
Datasource functional health: PASS
PR #426 integration / full destructive DoD: PENDING
```

## 2. Ràng buộc và nguyên tắc đã giữ

- Chỉ deploy qua GitOps/ArgoCD từ `main`; không `helm upgrade`, `kubectl
  apply`, `kubectl patch` hay sửa image live.
- Không thay đổi flagd, `/flagservice`, TOKEN/URI của flag sync hoặc fault
  injection.
- Không commit secret, credential hay token.
- Không làm xanh Trivy bằng ignore rule.
- Không mở public egress dài hạn để né lỗi plugin.
- Không coi `Pod Ready` hoặc `/api/health` là bằng chứng functional duy nhất.
- Mọi rollback production phải đi qua revert PR và ArgoCD.

Các lệnh kiểm tra cluster được chạy trong WSL. Identity thực tế:

```text
Base AWS profile: tf3-member-base
Kubernetes identity:
arn:aws:sts::197826770971:assumed-role/
tf3-production-readonly/EKSGetTokenAuth
Kubernetes group: tf3-production-readers
```

`tf3-member-base` không có `ssm:StartSession`. SSM tunnel tới private EKS API
phải được một identity/operator có quyền mở và giữ terminal session chạy.

## 3. Thiết kế cuối cùng

### 3.1 Artifact

Image cuối:

```text
197826770971.dkr.ecr.ap-southeast-1.amazonaws.com/techx-corp:
b44ca10-30240572310-grafana@
sha256:198bff3b9b5f15962cf0942f38a0a90226f60277e7ef5212294987d160f55958
```

Các thành phần được pin:

- Grafana source commit:
  `5d189285069d02af604bfaeedb21a0b6ec4c4d0a`;
- Grafana runtime version: `13.2.0-30056490933`;
- OpenSearch datasource version: `2.34.0`;
- OpenSearch datasource source commit:
  `188f6f20d488f771808eff476e8647dccb901dad`;
- Go builder: `1.26.5`, pin bằng digest;
- `google.golang.org/grpc`: `v1.82.1`;
- plugin path: `/opt/grafana/plugins`.

Backend plugin được rebuild từ exact upstream commit để loại bỏ các HIGH đã
có bản vá. Vì backend khác binary trong archive do Grafana ký,
`MANIFEST.txt` cũ được xóa và artifact được khai báo trung thực là
`TF3-derived-unsigned`. Đây không phải tắt signature verification toàn cục:
Grafana chỉ allowlist đúng ID `grafana-opensearch-datasource`.

Integrity được bù bằng:

- source commit, builder digest, archive checksum và patch checksum;
- `go mod verify`;
- plugin directory root-owned và read-only;
- production image pin bằng digest;
- Trivy fail-closed cho cả hai architecture;
- SBOM và Cosign signing/verification;
- startup smoke và runtime functional gate.

Chi tiết quyết định trust model:
[ADR 0014](adr/0014-pm-176-derived-opensearch-plugin.md).

### 3.2 Grafana runtime

Chart đặt:

```ini
[paths]
plugins = /opt/grafana/plugins

[plugins]
allow_loading_unsigned_plugins = grafana-opensearch-datasource
preinstall_disabled = true
preinstall_auto_update = false
plugin_admin_enabled = false
plugin_admin_external_manage_enabled = false
```

Helm `grafana.plugins` runtime declaration đã bị xóa. Không còn
`GF_PLUGINS_PREINSTALL*`, init container hoặc command tải plugin trong
rendered Pod.

### 3.3 Datasource

Datasource cuối:

```yaml
uid: webstore-logs
type: grafana-opensearch-datasource
url: http://opensearch:9200/
jsonData:
  database: "[otel-logs-]YYYY-MM-DD"
  interval: Daily
  timeField: observedTimestamp
  pplEnabled: true
```

`interval: Daily` là bắt buộc. Chỉ có time pattern mà không có interval làm
plugin gửi nguyên chuỗi `[otel-logs-]YYYY-MM-DD` như tên index literal trong
Save & Test.

Dashboard PPL có thể tiếp tục dùng `source=otel-logs-*`; không cần đổi query
dashboard để chữa health endpoint.

## 4. Timeline PR và thay đổi

| PR | Merge commit | Nội dung | Kết quả |
| --- | --- | --- | --- |
| [#467](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/467) | `b8f12d6` | Dockerfile, compose target, build matrix và immutable pin contract ban đầu | Merge; main build bị Trivy chặn |
| [#469](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/469) | `ed7d78c` | Rebuild Grafana/plugin Go binaries với dependency đã vá | Trivy tiến triển; multi-platform build timeout |
| [#470](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/470) | `f5ba80a` | Chạy builder trên `$BUILDPLATFORM`, cross-compile theo target | Build/push thành công |
| [#471](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/471) | `74ce2f3` | Bot pin production image từ run `30210176908` | Image mới deploy |
| [#472](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/472) | `e0d822a` | Sửa admission contract để chấp nhận `tag@sha256` | Digest-pinned rollout được admit |
| [#473](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/473) | `f7ef66b` | Xóa Helm runtime plugin declaration, đặt immutable path và smoke | OpenSearch runtime download hết; default catalogue vẫn chạy |
| [#474](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/474) | `31df196` | Tắt Grafana 13 automatic preinstall/auto-update/plugin admin | Không còn runtime install/download |
| [#475](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/475) | `b875aee` | Không overlay binary lên signed archive | Signature sạch nhưng signed backend còn 4 HIGH |
| [#476](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/476) | `b44ca10` | Derived plugin, dependency patch, provenance, dual-arch Trivy/smoke | Candidate sạch và đủ release gate |
| [#478](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/478) | `4e4f2e4` | Bot pin image/digest từ run `30240572310` | Production dùng image cuối |
| [#479](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/479) | `011e963` | Đổi wildcard thành daily time pattern | Pattern đã sync nhưng health vẫn coi literal |
| [#480](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/480) | `1fe6584` | Thêm `interval: Daily`, test contract và runbook | Datasource health `HTTP 200 / status OK` |

## 5. Nhật ký lỗi, root cause và cách xử lý

### Lỗi 1 — Initial image bị Trivy chặn

Workflow:
[run 30199024415](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/actions/runs/30199024415),
job `89785663300`.

**Biểu hiện:** `build-scan (grafana)` fail tại blocking pre-push Trivy gate;
không push image, không mở image-bump PR.

**Root cause:** candidate dựa trên upstream Grafana binaries chứa nhiều Go
dependency findings đã có fixed version.

**Xử lý:** PR #469 rebuild Grafana và plugin Go binaries từ source commit pin,
dùng Go/dependency đã vá. Không thêm Trivy ignore.

**Ảnh hưởng production:** không có; fail xảy ra trước push.

### Lỗi 2 — Multi-platform build vượt timeout một giờ

Workflow:
[run 30206948352](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/actions/runs/30206948352).

**Biểu hiện:** `build-scan (grafana)` chạy `1h0m19s`, vượt timeout 1 giờ và bị
cancel; aggregate/image-bump không chạy.

**Root cause:** builder stages chạy theo target platform dưới QEMU trong khi
đang compile Grafana lớn. Đây là emulation không cần thiết và quá chậm.

**Xử lý:** PR #470 đặt builder stages thành
`FROM --platform=$BUILDPLATFORM`, dùng `TARGETOS/TARGETARCH` để native
cross-compile, thêm BuildKit cache.

**Kết quả:** run `30210176908` build/push thành công.

### Lỗi 3 — Admission policy không nhận `tag@digest`

**Biểu hiện:** production image đã đúng OCI format
`repository:tag@sha256:digest`, nhưng native admission/verifier contract chỉ
nhận một số dạng digest reference và chặn rollout.

**Root cause:** regex giữa policy và image convention không đồng nhất.

**Xử lý:** PR #472 cập nhật contract cho regular/init/ephemeral containers,
chấp nhận optional tag trước `@sha256` nhưng vẫn từ chối tag-only.

**Phạm vi ảnh hưởng:** chỉ image reference validation; không nới quyền hay bỏ
digest enforcement.

### Lỗi 4 — Plugin vẫn được tải lúc runtime

Evidence:
[01-pre-networkpolicy-runtime-test](evidence/pm-176/01-pre-networkpolicy-runtime-test.md).

**Biểu hiện:**

```text
Installing plugin pluginId=grafana-opensearch-datasource
Downloaded and extracted grafana-opensearch-datasource v2.34.0
Plugin successfully installed
```

**Root cause:** image đã chứa plugin nhưng Helm vẫn khai báo
`grafana.plugins`, nên chart tiếp tục tạo runtime install flow.

**Xử lý:** PR #473 xóa declaration, chuyển path sang `/opt/grafana/plugins`
và thêm smoke assertions.

### Lỗi 5 — Grafana 13 tự chạy default plugin catalogue

Evidence:
[02-post-pr473-default-preinstall-failure](evidence/pm-176/02-post-pr473-default-preinstall-failure.md).

**Biểu hiện:** OpenSearch không còn tải, nhưng Grafana thử cài
`grafana-exploretraces-app`, metrics drilldown và các default plugins; immutable
path trả `permission denied`.

**Root cause:** xóa `grafana.plugins` không thay đổi
`preinstall_disabled=false` và `preinstall_auto_update=true` trong Grafana 13
defaults.

**Xử lý:** PR #474 đặt bốn config preinstall/update/admin về fail-closed.
Smoke đổi từ chỉ tìm OpenSearch download sang reject mọi install/download.

### Lỗi 6 — Baked plugin bị invalid signature

Evidence:
[03-post-pr474-plugin-signature-failure](evidence/pm-176/03-post-pr474-plugin-signature-failure.md).

**Biểu hiện:**

```text
Plugin file checksum does not match signature checksum
Skipping loading plugin due to problem with signature
Plugin validation failed
```

**Root cause:** Dockerfile lấy signed catalog archive rồi overlay backend tự
build. Backend nằm trong phạm vi checksum của `MANIFEST.txt`, nên Grafana phát
hiện artifact đã bị thay đổi.

**Xử lý ban đầu:** PR #475 giữ nguyên archive signed và backend upstream.

### Lỗi 7 — Signed upstream backend còn bốn HIGH

Workflow:
[run 30214865296](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/actions/runs/30214865296),
job `89827218482`. Evidence:
[04-post-pr475-trivy-block](evidence/pm-176/04-post-pr475-trivy-block.md).

**Biểu hiện:** OS layer và Grafana binary sạch, nhưng plugin backend có:

| Finding | Version bị phát hiện | Fixed version |
| --- | --- | --- |
| `GHSA-hrxh-6v49-42gf` | gRPC `v1.79.3` | `1.82.1` |
| `CVE-2026-27145` | Go `1.26.3` | `1.26.4` |
| `CVE-2026-39822` | Go `1.26.3` | `1.26.5` |
| `CVE-2026-42504` | Go `1.26.3` | `1.26.4` |

**Quyết định:** không ignore. PR #476 build lại đúng backend từ exact release
commit với Go `1.26.5` và gRPC `1.82.1`, xóa stale signature manifest, ghi
`TF3-PROVENANCE`, allowlist đúng một plugin ID và công bố trust model
`TF3-derived-unsigned`.

**Kết quả:** build/push
[run 30240572310](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/actions/runs/30240572310)
pass pre-push/post-push Trivy, Cosign, SBOM và mở PR #478.

### Lỗi 8 — Datasource wildcard bị health endpoint coi là literal

Evidence:
[05-post-merge-runtime-smoke](evidence/pm-176/05-post-merge-runtime-smoke.md).

**Biểu hiện:**

```json
{"message":"Index not found: otel-logs-*","status":"ERROR"}
```

OpenSearch thực tế có các daily indices, nên lỗi không phải mất log hay mất
connectivity.

**Xử lý:** PR #479 đổi `database` thành
`[otel-logs-]YYYY-MM-DD`.

### Lỗi 9 — Time pattern vẫn bị coi là literal

**Biểu hiện sau PR #479:**

```json
{
  "reason": "no such index [[otel-logs-]YYYY-MM-DD]",
  "index": "[otel-logs-]YYYY-MM-DD"
}
```

**Root cause:** datasource có time-pattern nhưng thiếu `interval: Daily`.
Plugin không biết phải dùng daily expansion trong Save & Test.

**Xử lý:** PR #480 thêm `interval: Daily` và khóa contract bằng test.

**Kết quả cuối:**

```json
{"message":"Index OK. Time field name OK.","status":"OK"}
```

### Lỗi vận hành — SSM tunnel tự đóng và base profile thiếu StartSession

**Biểu hiện:** `localhost:8443` trả timeout/connection refused sau khoảng idle;
cluster checks không chạy được.

**Root cause:** SSM port-forward session đã đóng. `tf3-member-base` có thể lấy
EKS token bằng cách assume readonly role nhưng không có
`ssm:StartSession` trên bastion.

**Xử lý:** operator có quyền mở lại tunnel; tất cả kiểm tra sau đó tiếp tục
read-only. Đây không phải lỗi ứng dụng hoặc rollout.

### Follow-up riêng — scheduled immutable audit phát hiện mutable tag drift

Workflow:
[run 30241332715](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/actions/runs/30241332715).

Audit ghi:

```text
grafana/grafana:nightly-ubuntu-slim
resolved: sha256:0545255...
pin expects: sha256:7dcef0c...
```

Đây là hành vi đúng của drift detector: upstream `nightly` tag đã di chuyển,
trong khi Dockerfile vẫn build bằng digest cũ đã kiểm chứng. Nó không thay đổi
image đang chạy và không làm PM-176 runtime regression, nhưng scheduled audit
sẽ tiếp tục báo đỏ cho tới khi team:

1. review/scan digest mới rồi cập nhật pin qua PR; hoặc
2. chuyển sang một upstream reference có lifecycle ổn định hơn.

Không tự cập nhật digest chỉ để làm audit xanh.

### Cảnh báo CI không chặn

Một số Actions báo Node.js 20 deprecated và bị runner ép sang Node.js 24.
Các job vẫn pass. Đây là maintenance follow-up cho action versions, không phải
PM-176 runtime failure.

## 6. Bằng chứng cuối

Capture read-only lúc `2026-07-27T07:37:10Z`.

### 6.1 Git và CI

- `main` revision: `1fe6584bcdd41b1bcb374d98638e8435309099c0`;
- PR #480: Grafana amd64/arm64, IaC, immutable pins, secret scan, SAST,
  secure delivery, gitleaks và validate đều pass;
- targeted tests: `15 passed, 2 skipped`;
- production `helm template`: pass, render đúng `database` và
  `interval: Daily`.

### 6.2 ArgoCD và workload

```text
sync=Synced
health=Healthy
revision=1fe6584bcdd41b1bcb374d98638e8435309099c0

Pod: grafana-668bb9ccc5-t4kbl
UID: 939fa7d5-7a41-47fe-875f-0ecef34a4107
Created: 2026-07-27T06:12:09Z
Containers: 4/4 Ready
Restarts: 0/0/0/0
```

### 6.3 Startup log

```text
Plugin is unsigned ... could not find a MANIFEST.txt
Permitting unsigned plugin ... pluginId=grafana-opensearch-datasource
Plugin registered ... pluginId=grafana-opensearch-datasource
```

Warning unsigned là expected theo ADR 0014. Không có runtime
install/download, modified signature hay validation failure.

### 6.4 Grafana và datasource API

```json
{
  "database": "ok",
  "version": "13.2.0-30056490933",
  "commit": "5d189285069d02af604bfaeedb21a0b6ec4c4d0a"
}
```

```json
{
  "uid": "webstore-logs",
  "type": "grafana-opensearch-datasource",
  "url": "http://opensearch:9200/",
  "database": "[otel-logs-]YYYY-MM-DD",
  "interval": "Daily",
  "timeField": "observedTimestamp",
  "pplEnabled": true
}
```

```text
HTTP 200
{"message":"Index OK. Time field name OK.","status":"OK"}
```

Plugin settings endpoint báo metadata version `2.34.0`. Trường
`enabled=false` ở endpoint settings là trạng thái plugin-management, không
phải bằng chứng plugin backend bị disable: startup log đã đăng ký plugin và
datasource health thực tế trả `HTTP 200`.

### 6.5 OpenSearch

Cluster có một data node nên health `yellow` do replica shards chưa được
allocate; primary shards hoạt động và không có pending task.

```text
otel-logs-2026-07-24   913015 docs   402.3mb
otel-logs-2026-07-25  3502610 docs     1.4gb
otel-logs-2026-07-26  1486493 docs   638.4mb
otel-logs-2026-07-27  1040942 docs   644.4mb
```

Điều này chứng minh hai lỗi datasource trước đó là pattern configuration,
không phải thiếu daily indices.

## 7. Definition of Done — trạng thái thật

| Gate | Trạng thái | Bằng chứng |
| --- | --- | --- |
| Base image pin digest | PASS | Dockerfile immutable pin |
| Plugin pin exact version | PASS | `2.34.0` |
| Plugin tại `/opt/grafana/plugins` | PASS | CI/startup contract |
| Runtime plugin declaration bị loại bỏ | PASS | Helm render |
| Rendered Pod không có downloader | PASS | static/smoke tests |
| Build qua pipeline chuẩn | PASS | run `30240572310` |
| Trivy gate | PASS | amd64 + arm64, pre/post-push |
| Production image pin digest | PASS | live Deployment |
| Plugin đăng ký | PASS | startup log |
| Datasource tồn tại | PASS | Grafana API |
| Datasource health | PASS | `HTTP 200 / status OK` |
| ArgoCD Synced/Healthy | PASS | revision `1fe6584` |
| Public internet bị block | PENDING | PR #426 chưa merge |
| Internal paths hoạt động dưới egress policy | PENDING | policy live chỉ Ingress |
| Delete Pod dưới PR #426 | PENDING | cần operator approval/quyền |
| Recreation lần hai | PENDING | cần operator approval/quyền |
| Real dashboard query dưới policy | PENDING | chưa capture `POST /api/ds/query` |
| Evidence đầy đủ theo full spec | PARTIAL | core evidence đủ; #426 evidence thiếu |
| Rollback runbook | PASS (documented) | runbook đã có; chưa kích hoạt vì không có outage |

## 8. Rollback

### 8.1 Datasource-only regression

1. Tạo revert PR cho merge #480; nếu cần, revert tiếp #479.
2. Merge qua branch protection.
3. Chờ `techx-corp` trở lại `Synced/Healthy`.
4. Kiểm tra Grafana API, datasource và dashboard.

Không sửa ConfigMap live.

### 8.2 Image/plugin regression

1. Revert production image-bump PR #478 về digest Grafana trước đó.
2. Chờ ArgoCD reconcile.
3. Xác nhận Pod Ready, datasource và startup log.
4. Giữ nguyên failure evidence và sửa candidate trên branch mới.

Không bypass Trivy, digest admission hoặc chữ ký bằng cấu hình toàn cục.

### 8.3 PR #426 integration regression

Nếu chỉ egress policy làm hỏng internal dependency:

1. dừng destructive test;
2. revert riêng thay đổi Grafana egress của #426 qua Git;
3. không mở public plugin repository làm permanent workaround;
4. chờ ArgoCD `Synced/Healthy`;
5. kiểm tra lại customer path và observability.

## 9. Việc cần làm để full PM-176 Done

1. Rebase và review PR #426 trên `main`.
2. Xác nhận rendered/live policy có `Ingress` và `Egress` với allowlist nội bộ
   đúng cho DNS, OpenSearch, Prometheus, Jaeger và Kubernetes API nếu cần.
3. Merge #426 qua GitOps, chờ `techx-infrastructure-app` và `techx-corp`
   `Synced/Healthy`.
4. Trong giờ ít traffic và với operator approval, xóa Pod Grafana.
5. Xác nhận Pod UID mới, image digest không đổi, 4/4 Ready và 0 restart.
6. Chạy smoke với `EXPECT_EGRESS_BLOCK=1`.
7. Chạy một query thật lấy từ dashboard `webstore-logs`.
8. Lặp recreation lần hai bằng rollout/reschedule có kiểm soát.
9. Lưu egress, Pod UID trước/sau, query response và Argo state vào
   `docs/evidence/pm-176/`.
10. Chỉ khi tất cả pass mới đổi trạng thái full PM-176 thành Done.

## 10. Bài học phòng tái diễn

1. CI xanh không thay thế runtime functional test.
2. ArgoCD `Healthy` chỉ chứng minh Kubernetes objects/workload health, không
   chứng minh plugin hoặc datasource hoạt động.
3. Image chứa plugin chưa đủ nếu chart vẫn bật runtime installer.
4. `GF_PLUGINS_PREINSTALL` rỗng không tắt default catalogue của Grafana 13.
5. Không overlay binary lên signed archive rồi giữ `MANIFEST.txt`.
6. Nếu upstream signed artifact còn fixed HIGH, không dùng ignore; phải chọn
   upstream sạch hoặc công bố derived trust model với compensating controls.
7. Multi-architecture Go builder phải chạy trên `$BUILDPLATFORM` và
   cross-compile, không emulation toàn bộ build.
8. OCI `tag@digest` phải được CI verifier và admission policy hiểu giống nhau.
9. Grafana time-pattern cần cả pattern lẫn `interval`.
10. SSM tunnel là dependency vận hành ngắn hạn; kiểm tra tunnel trước mỗi
    chuỗi hậu kiểm và phân biệt access failure với rollout failure.
11. Floating tag kèm digest vẫn có thể làm drift audit đỏ khi tag di chuyển;
    chỉ cập nhật sau review/scan, không update mù.
12. Giữ lại evidence của từng lần fail giúp tránh lặp lại cùng giả thuyết và
    chứng minh gate đã fail-closed đúng cách.

