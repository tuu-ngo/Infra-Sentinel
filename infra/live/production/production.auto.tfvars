eks_admin_principal_arns = [
  "arn:aws:iam::197826770971:user/cdo-2-admin-team",
]

edge_phase       = "private"
private_alb_name = "techx-tf3-frontend-internal"

# Mandate #21 — AZ mục tiêu của experiment FIS az-loss. Đặt 1c CÓ CHỦ ĐÍCH: 1c là AZ
# tệ nhất (giữ RDS primary + frontend + ElastiCache replica + 1 broker), nên drill 1c
# chứng minh được ca khó nhất. Commit ở đây để CODE KHỚP HẠ TẦNG LIVE — trước đó template
# từng bị retarget 1c bằng `terraform apply` local (drift so với default 1b trong biến),
# và chính drift vô hình đó khiến một lần start-experiment tưởng nhắm 1b lại blackhole 1c.
# Mọi thay đổi target từ nay đi qua file này + PR + CI, không apply local.
# ĐỔI AZ = đổi giá trị này qua PR (KHÔNG trỏ 1a nếu chưa có NAT/endpoint đa AZ — xem note ở var).
fis_target_az = "ap-southeast-1c"

enable_cloudflare_access        = true
cloudflare_account_id           = "4903f08491f403370e1a2ae9c8aee84e"
cloudflare_zone_id              = "b711c7ecbcb4efb9d909de520330f0bb"
cloudflare_zone_name            = "arthur-ngo.org"
cloudflare_tunnel_hostname      = "kubectl.arthur-ngo.org"
cloudflare_allowed_email_domain = ""
cloudflare_allowed_emails = [
  "hiimtuu@gmail.com",
  "tutc.work@gmail.com",
  "trongtanaws@gmail.com",
  # CDO02 — chủ trì diễn tập resilience Mandate 17. Không có quyền vào Grafana thì
  # phải xem SLO qua `kubectl port-forward`, tức là người chạy drill lại phụ thuộc
  # đúng đường mạng mà drill có thể làm gãy. Leader đã duyệt 30/07/2026.
  "tainguyenduc2004@gmail.com",
  # Mentors — SSO access tới Grafana/Jaeger/ArgoCD UI qua Cloudflare Zero Trust (REL-17).
  "nghia.huynh@techxcorp.com",
  "toan.le@techxcorp.com",
  "khanh.nguyen@techxcorp.com",
  "namhong.ta@techxcorp.com",
]

# Mandate #8 — bật tầng datastore managed (RDS/ElastiCache/MSK).
# Đặt = true để state khớp hạ tầng thật; nếu để default false, plan sau sẽ đòi XOÁ 3 store.
enable_managed_datastores = true

# Mandate 13: PostgreSQL/Valkey in-cluster da retire o production, nodegroup
# stateful hien khong con pod techx-tf3 nao. Tat han nodegroup nay de bo node
# on-demand rong, tang spot ratio ma khong ep giam headroom observability.
enable_stateful_node_group = false

# Mandate 13: giam day on-demand tu 4 ve 3 de tang ty le Spot nhung van giu
# them 1 lop headroom an toan cho observability va rollout window. Ket hop voi
# right-size request se de dat >50% spot ma khong cat qua sau ngay o buoc dau.
node_desired_size = 3
node_min_size     = 3

audit_detection_email_subscriptions = [
  "dophuc776@gmail.com",
  "huutai.ngo2409@gmail.com",
  "nguyenthimen190504@gmail.com",
  "nvtvlog234@gmail.com",
  "tranduc.357cc@gmail.com",
  "haileab542@gmail.com"
]

audit_detection_additional_human_principal_arns = [
  "arn:aws:iam::197826770971:user/aio2-admin-team",
  "arn:aws:iam::197826770971:user/cdo-2-admin-team",
  "arn:aws:iam::197826770971:user/cdo-admin-team",
  "arn:aws:iam::197826770971:user/hieu-AdminAccess",
  "arn:aws:iam::197826770971:user/KietBE",
  "arn:aws:iam::197826770971:user/mentor-mandate-reviewer",
  "arn:aws:iam::197826770971:user/Thao",
]

# CẢNH BÁO (Mandate 12): principal trong danh sách này được router bỏ qua ở các
# nhóm KHÔNG critical. Sau M12, critical_group_numbers = [1,2,3,4,7,8] nên
# StopLogging, leo thang quyền IAM, tamper alert plane và boundary/OIDC vẫn luôn
# cảnh báo kể cả với principal ở đây. Phần còn bị bỏ qua là group 5 (đọc secret)
# và group 6 (hành động huỷ hoại).
#
# `gitlab-ci-deployer` là IAM user admin, chưa MFA, còn access key dài hạn đang
# hoạt động, và không xoá được vì pipeline GitLab đang dùng. Quyết định: áp cùng
# permissions boundary với CI role (attach thủ công vì user nằm ngoài Terraform
# state — xem docs/mandate-12-execution-plan.md §9.5). Sau khi bounded, nó không
# còn đường tắt tắt audit; phần còn bị suppress ở đây chỉ là group 5 (đọc secret)
# và group 6 (xoá cluster/RDS/bucket).
#
# Hai việc còn lại thuộc PR IAM hardening: bật MFA (team AI sở hữu identity) và
# rotate/vô hiệu 2 access key (cần owner pipeline xác nhận downtime).
audit_detection_additional_allowed_automation_principal_arns = [
  "arn:aws:iam::197826770971:user/gitlab-ci-deployer",
]

# Mandate 12 — retention. Bài tập kết thúc 31/07/2026, account của owner cá nhân,
# nên cả hai con số đặt theo vòng đời bài tập: Object Lock COMPLIANCE 14 ngày
# (xem m12-variables.tf), lifecycle 30 ngày — đúng giá trị M11 đang chạy.
#
# Lifecycle phải DÀI HƠN Object Lock: object còn bị lock thì lifecycle không xoá
# được và S3 để rule fail âm thầm. Module có precondition chặn cấu hình sai.
#
# KHÔNG bỏ lifecycle. Lifecycle chính là thứ xoá object; bỏ nó đi thì log giữ
# vĩnh viễn và hoá đơn tăng chứ không giảm. Nó cũng là đường dọn dẹp duy nhất:
# hết 14 ngày lock, object hết hạn ở ngày 30, bucket rỗng rồi mới xoá được.
# Heartbeat cũng đọc lifecycle như một invariant, không có là FAIL.
audit_detection_trail_s3_retention_days = 30

# Mandate 12 — S3 data events.
#
# Scope hiện tại: NGUYÊN bucket Terraform state. TF3 sở hữu rõ ràng bucket này
# (backend của cả hai root), nên đủ thẩm quyền duyệt mà không cần đội khác ký.
#
# Dùng nguyên bucket chứ không phải prefix "eks-baseline/": bucket chứa HAI
# state key, và key thứ hai mới là file nhạy cảm nhất với Mandate 12 —
#   eks-baseline/terraform.tfstate          → EKS, network, edge, audit-detection
#   bootstrap/github-oidc/terraform.tfstate → CI OIDC roles + chính ci-audit-boundary
# Đọc được file thứ hai là biết boundary audit deny những gì và sót chỗ nào.
# Prefix hẹp sẽ bỏ lọt đúng thứ cần bảo vệ nhất.
#
# Volume thấp: state chỉ được đọc khi terraform chạy (vài lần/ngày), nên không
# cần lọc readOnly và chi phí data events không đáng kể.
#
# Ba bucket từng được cân nhắc nhưng KHÔNG đưa vào lần này vì TF3 không phải
# data owner — xem docs/mandate-12-execution-plan.md §8.1:
#   techx-aiops-playbooks-f6230446    → AIO02
#   tf3-aiops-models-197826770971     → AIO02
#   sosflow-alb-logs-197826770971     → dự án SOSFlow
#
# Không đưa audit archive vào đây (vòng lặp logging; module có precondition chặn).
audit_detection_s3_data_event_arns = [
  "arn:aws:s3:::techx-tf3-197826770971-tfstate/",
]

# Cost guardrails — Layer 1 (Cost Anomaly Detection) + Layer 2 (Budget hard ceiling).
# Global services provisioned via the us-east-1 provider. Recipients fall back to
# audit_detection_email_subscriptions above. Monthly ceiling 1300 USD = the
# $300/week/TF ceiling projected monthly; anomaly reporting floor 30 USD.
enable_cost_guardrails = true
