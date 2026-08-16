# AIOps handoff for AI team

Status: repo-declared, cập nhật ngày 2026-07-29.

Tài liệu này là hợp đồng vận hành giữa team AI và team CDO cho `aiops-engine`.
Mục tiêu là để team AI biết cách đưa thay đổi AIOps vào production, hiểu vì sao
nút Slack approval hiện chưa thể dùng như một luồng sửa lỗi thật, và biết CDO
cần những thông tin gì trước khi siết lại security.

## 1. Phạm vi đang thuộc GitOps

AIOps hiện có hai workload trong namespace `techx-tf3`:

- `Deployment/aiops-engine`: engine chạy FastAPI, đọc Prometheus/Jaeger/OpenSearch,
  gọi Bedrock, gửi Slack card và có endpoint nhận approval.
- `CronJob/aiops-anomaly-training`: job huấn luyện lại model anomaly và ghi model
  lên S3.

Desired state nằm ở:

- Source ứng dụng: `aiops-engine/`
- Manifest production: `gitops/aiops-engine/`
- Build image first-party: `.github/workflows/build-push-ecr.yml`
- Auto-bump raw manifest: `scripts/ci/update-image-overrides.py`

Không dùng lại repo/image cũ `tf-2-ai-engine` cho production. Image production
phải đi qua repo ECR first-party `techx-corp`, có digest pin, Cosign signature và
SBOM attestation.

## 2. Quy trình team AI phải đi qua khi muốn sửa AIOps

Không apply tay vào cluster để thay đổi lâu dài. Argo CD đang quản lý manifest,
có `prune` và `selfHeal`; thay đổi tay sẽ bị revert hoặc tạo drift.

Luồng chuẩn cho thay đổi code:

1. Tạo branch từ `origin/main`.
2. Sửa trong `aiops-engine/**`.
3. Chạy test liên quan trong `aiops-engine/tests/`.
4. Mở PR vào `main`.
5. Sau khi PR merge, workflow `build-push-ecr.yml` build image `aiops-engine`.
6. Image phải qua các cổng: build, Trivy, push ECR, Cosign, SBOM attestation,
   post-push scan.
7. Image-bump bot mở PR cập nhật digest trong:
   - `gitops/aiops-engine/deployment.yaml`
   - `gitops/aiops-engine/cronjob.yaml`
8. Merge PR bump digest.
9. Chờ Argo CD reconcile.
10. Verify runtime: pod ready, `/readyz`, logs, Bedrock/Slack/training behavior
    theo đúng thay đổi.

Luồng chuẩn cho thay đổi manifest:

1. Tạo branch từ `origin/main`.
2. Sửa đúng file dưới `gitops/aiops-engine/`.
3. Mở PR, để CI kiểm tra.
4. Merge PR.
5. Chờ Argo CD reconcile.
6. Verify live state bằng read-only check.

Luồng chuẩn cho thay đổi trainer:

1. Sửa code trainer trong `aiops-engine/**`.
2. Test local/unit trước.
3. Sau khi image mới được deploy, cần một lần chạy trainer thành công hoặc bằng
   lịch CronJob, hoặc bằng Job thủ công đã được CDO duyệt.
4. Không coi việc merge code là hoàn tất nếu chưa chứng minh model artifact/S3
   manifest mà engine cần đã được tạo đúng format.

## 3. Vì sao Slack -> AIOps approval hiện không hoạt động như một luồng remediation thật

Có hai luồng Slack khác nhau, không được đánh đồng:

1. AIOps -> Slack: engine gửi Slack incident card qua webhook hoặc bot token.
2. Slack -> AIOps: khi người dùng bấm Approve/Reject/Emergency Stop, Slack phải
   gọi ngược về một endpoint HTTP của AIOps.

Luồng thứ nhất có thể hoạt động nếu secret và egress ra Slack hợp lệ. Luồng thứ
hai hiện chưa thể coi là hoạt động production vì các lý do repo-declared sau:

- `gitops/aiops-engine/service.yaml` khai báo `Service/aiops-engine` là
  `ClusterIP`; Slack bên ngoài cluster không thể gọi trực tiếp endpoint nội bộ.
- Source có endpoint `/slack/interactive`, `/remediation/interactive` và
  `/remediation/approve`, nhưng chưa có cấu hình ingress/callback public hoặc
  private bridge được codify trong GitOps.
- Endpoint approval không thấy lớp xác minh Slack request signature/timestamp.
  Nếu expose thẳng endpoint này ra Internet thì không đạt chuẩn security.
- Code hiện xử lý approval bằng cách lấy command từ incident in-memory rồi gọi
  remediation handler. Nếu pod restart, active incident có thể mất khỏi memory
  và code có fallback tự sinh command theo target service.
- Remediation handler hiện chạy `kubectl` qua shell. Dù có whitelist và blacklist,
  đây không phải boundary đủ chặt để cấp quyền production rộng.

Kết luận: Slack card hiện chỉ nên xem là notification/recommendation. Nút Approve
không được xem là security boundary và không nên là đường thực thi remediation
production cho tới khi team AI cung cấp contract đầy đủ và CDO codify lại luồng
inbound an toàn.

Luồng security chuẩn CDO đề xuất cho Slack approval:

1. Không expose trực tiếp pod `aiops-engine` ra Internet. Slack chỉ gọi vào một
   edge endpoint hẹp, ví dụ API Gateway/Lambda hoặc một Slack bridge chuyên dụng.
2. Edge endpoint phải xác minh `X-Slack-Signature`,
   `X-Slack-Request-Timestamp`, chống replay và reject mọi request quá hạn.
3. Payload Slack không được chứa raw command. Payload chỉ chứa `incident_id`,
   `action_id`, `decision`, Slack `user_id` và metadata audit.
4. Edge endpoint map Slack user/group sang quyền duyệt hợp lệ. Người bấm nút
   không thuộc nhóm được duyệt thì request bị reject trước khi vào cluster.
5. Sau khi validate, edge endpoint ghi một approval event có idempotency key vào
   queue/store nội bộ. Executor trong cluster đọc event này hoặc nhận internal
   call đã xác thực.
6. Executor chỉ nhận typed action từ remediation contract, ví dụ
   `restart_deployment` hoặc `scale_deployment`; không nhận shell command do
   Slack, LLM hoặc user gửi vào.
7. Executor dùng ServiceAccount/RBAC tối thiểu theo từng action. Không cấp
   `pods/exec`, không cấp wildcard, không bind vào ServiceAccount `default`.
8. Mọi quyết định phải có audit log: incident ID, Slack user, action, target,
   thời gian, dry-run result, execution result, rollback/escalation result.
9. Emergency Stop phải là đường riêng có quyền cao hơn Approve, idempotent, và
   không phụ thuộc vào incident còn nằm trong memory của pod.

Mô hình này giữ Slack là lớp phê duyệt của con người, nhưng không biến Slack
payload hoặc endpoint public thành quyền chạy lệnh Kubernetes trực tiếp.

## 4. CDO cần team AI cung cấp những gì để siết security

Team AI cần bàn giao thông tin theo dạng contract cụ thể, không chỉ mô tả chung.

### 4.1 Ownership và release

- Owner kỹ thuật của `aiops-engine`.
- Người duyệt thay đổi production phía AI.
- Lệnh test chuẩn cho engine và trainer.
- SLA kỳ vọng khi AIOps degrade: ai chịu trách nhiệm, thời gian phản hồi, cách
  rollback.

### 4.2 Dependency matrix runtime

Cần liệt kê endpoint, protocol, port, namespace và mục đích cho từng dependency:

- Prometheus queries engine/trainer cần đọc.
- Jaeger endpoint và path cần đọc.
- OpenSearch index/API cần đọc.
- S3 bucket/prefix cần đọc và ghi.
- Bedrock model ID, Knowledge Base ID, region và ARN nếu có.
- Slack API endpoint hoặc webhook mode.
- Kubernetes objects engine cần đọc/ghi.

Thông tin này là đầu vào để CDO viết NetworkPolicy, IAM/IRSA và RBAC tối thiểu.

### 4.3 Slack approval bridge contract

Nếu team AI vẫn muốn dùng nút Slack để duyệt remediation, hướng được CDO chấp
nhận là edge bridge đã nêu ở section 3. Team AI cần cung cấp thông tin để CDO
thiết kế/codify bridge đó, không yêu cầu expose trực tiếp `aiops-engine` ra
Internet.

Cần bàn giao:

- Slack app ID/workspace/channel và nhóm user được phép approve/reject.
- Slack interactivity endpoint path cho edge bridge, không phải URL trực tiếp vào
  Service `aiops-engine`.
- Cách team AI muốn map Slack action sang typed action nội bộ, ví dụ
  `approve_restart_deployment` -> `restart_deployment`.
- Payload schema tối thiểu: `incident_id`, `action_id`, `decision`, Slack
  `user_id`, `channel_id`, `team_id`, timestamp.
- Quy tắc idempotency và retry: request trùng xử lý ra sao, timeout bao lâu,
  Slack retry có được chạy lại remediation không.
- Audit fields bắt buộc: user, channel, incident ID, typed action, target,
  timestamp, dry-run result, execution result, rollback/escalation result.
- Nơi lưu Slack signing secret theo chuẩn platform. Không gửi secret value trong
  PR hoặc tài liệu.

CDO sẽ chịu trách nhiệm codify edge bridge, signature verification, internal
auth, NetworkPolicy và RBAC executor sau khi team AI cung cấp đủ contract ở trên.

### 4.4 Remediation contract

Team AI cần liệt kê chính xác từng hành động muốn engine được phép làm:

- Tên action ổn định, ví dụ `restart_deployment`, `scale_deployment`,
  `restart_rollout`.
- Resource Kubernetes được phép đụng: apiGroup, kind, namespace, tên object hoặc
  selector.
- Verb cần dùng: `get`, `patch`, `update`, `watch`, v.v.
- Tham số hợp lệ và giới hạn: replica min/max, service allowlist, cooldown,
  số lần retry.
- Điều kiện được phép chạy: alert nào, SLO nào, confidence ngưỡng nào.
- Điều kiện rollback.
- Điều kiện escalate cho SRE/CDO.

Không yêu cầu các quyền sau nếu không có bằng chứng bắt buộc:

- `pods/exec`
- `pods/delete`
- wildcard `*`
- arbitrary `kubectl`
- shell command do LLM sinh trực tiếp
- quyền ghi ra ngoài namespace `techx-tf3`

### 4.5 IAM/IRSA contract

Hiện manifest còn ghi chú static AWS key trong Secret và IRSA role chưa chứng minh
tồn tại. Để CDO chuyển sang IRSA tối thiểu, team AI cần cung cấp:

- S3 bucket và prefix cần đọc.
- S3 bucket và prefix cần ghi.
- Bedrock model ARN hoặc model ID/region.
- Bedrock Knowledge Base ARN hoặc ID/region.
- KMS key nếu S3/Bedrock cần decrypt/encrypt.
- CloudWatch/OpenSearch permissions nếu code thật sự cần AWS API, không chỉ HTTP
  nội bộ.

Mục tiêu CDO: bỏ static AWS key khỏi Kubernetes Secret, dùng IRSA role riêng cho
engine/trainer, và tách quyền read/write theo nhu cầu thật.

### 4.6 NetworkPolicy contract

Team AI cần xác nhận traffic cần thiết:

- Egress nội bộ: Prometheus, Jaeger, OpenSearch, Kubernetes API nếu còn dùng,
  service nào, port nào.
- Egress AWS: S3, Bedrock, STS/KMS nếu cần; đi qua VPC endpoint/NAT/proxy nào.
- Egress Slack: endpoint/domain nào, webhook hay `chat.postMessage`.
- Ingress vào AIOps: chỉ nội bộ, hay cần callback Slack/bridge.

Nếu không có danh sách này, CDO chỉ có thể giữ policy rộng hoặc chặn nhầm luồng
thật. Muốn siết security thì phải có dependency matrix có thể test được.

## 5. Baseline security CDO sẽ áp sau khi có contract

Sau khi team AI cung cấp đủ thông tin, CDO sẽ siết theo hướng:

- Tách detector/recommender khỏi executor nếu có thể.
- ServiceAccount engine chỉ nhận token nếu thật sự cần Kubernetes API.
- Executor dùng RBAC tối thiểu theo remediation contract, không dùng wildcard.
- Không cấp `pods/exec`, không cấp delete pod, không bind vào ServiceAccount
  `default`.
- Bỏ static AWS key, thay bằng IRSA role tối thiểu.
- NetworkPolicy deny-by-default, chỉ mở egress đã chứng minh.
- Slack callback phải có signature verification, idempotency và audit log trước
  khi được phép mutate production.
- Remediation nên chuyển từ shell/kubectl sang Kubernetes Python client hoặc một
  executor API typed-command để tránh command injection.

## 6. Trạng thái cần theo dõi sau migration

- Image build và digest bump chỉ đưa code mới vào ECR/GitOps; chưa đủ để kết luận
  AIOps healthy.
- AIOps có thể vẫn `Degraded` nếu trainer Job cũ fail hoặc trainer mới chưa chạy
  thành công.
- Bedrock Knowledge Base fix chỉ live sau khi image chứa fix được build, digest
  bump PR được merge và Argo CD reconcile xong.
- Slack Approve vẫn chưa được coi là functional production path cho tới khi có
  callback route + signature verification + remediation contract.

## 7. Quy tắc bàn giao PR từ team AI sang CDO

Mỗi PR AIOps nên có tối thiểu:

- Mục đích thay đổi.
- File/code path bị ảnh hưởng.
- Test đã chạy.
- Runtime dependency thay đổi hay không.
- Quyền Kubernetes/AWS mới cần thêm hay không.
- Network egress/ingress mới cần thêm hay không.
- Nếu thay đổi remediation: action contract, rollback contract và blast radius.
- Nếu thay đổi Slack: callback/security contract.

Nếu PR yêu cầu thêm quyền nhưng không có contract ở trên, CDO sẽ giữ ở trạng thái
review/block thay vì tự đoán quyền.
