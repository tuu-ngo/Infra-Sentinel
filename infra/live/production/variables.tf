variable "region" {
  description = "AWS region for the production platform."
  type        = string
  default     = "ap-southeast-1"
}

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "techx-corp-tf3"
}

variable "cluster_version" {
  description = "Kubernetes version for the EKS control plane and managed node group."
  type        = string
  default     = "1.35"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "azs" {
  description = "Availability zones used by production subnets."
  type        = list(string)
  default     = ["ap-southeast-1a", "ap-southeast-1b", "ap-southeast-1c"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private EKS subnets."
  type        = list(string)
  default     = ["10.0.0.0/20", "10.0.16.0/20", "10.0.32.0/20"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets."
  type        = list(string)
  default     = ["10.0.48.0/24", "10.0.49.0/24", "10.0.50.0/24"]
}

variable "node_instance_type" {
  description = "Instance type for the managed node group."
  type        = string
  default     = "t3.large"
}

variable "node_desired_size" {
  type    = number
  default = 4
}

variable "node_min_size" {
  type    = number
  default = 4
}

variable "node_max_size" {
  type    = number
  default = 6
}

variable "stateful_node_availability_zone" {
  description = "Availability zone for the dedicated on-demand stateful node group."
  type        = string
  default     = "ap-southeast-1a"

  validation {
    condition     = can(regex("^ap-southeast-1[a-c]$", var.stateful_node_availability_zone))
    error_message = "stateful_node_availability_zone must be an ap-southeast-1 availability zone."
  }
}

variable "stateful_node_instance_type" {
  description = "Instance type for the dedicated on-demand stateful node group."
  type        = string
  default     = "t3.medium"
}

variable "enable_stateful_node_group" {
  description = "Whether to provision the dedicated on-demand stateful node group."
  type        = bool
  default     = true
}

variable "stateful_node_desired_size" {
  description = "Desired size for the dedicated on-demand stateful node group."
  type        = number
  default     = 1
}

variable "stateful_node_min_size" {
  description = "Minimum size for the dedicated on-demand stateful node group."
  type        = number
  default     = 1
}

variable "stateful_node_max_size" {
  description = "Maximum size for the dedicated on-demand stateful node group."
  type        = number
  default     = 1
}

variable "eks_admin_principal_arns" {
  description = "IAM principal ARNs that receive EKS cluster-admin access."
  type        = list(string)
  default     = []
}

variable "frontend_alb_dns_name" {
  description = "DNS name of the Kubernetes-managed frontend-proxy ALB."
  type        = string
  default     = "k8s-techxtf3-frontend-3153771b08-956551046.ap-southeast-1.elb.amazonaws.com"
}

variable "private_alb_name" {
  description = "Stable AWS Load Balancer Controller name for the private frontend ALB."
  type        = string
  default     = "techx-tf3-frontend-internal"
}

variable "edge_phase" {
  description = "Controlled edge migration phase: public, waf, staging, private, or rollback."
  type        = string
  default     = "public"

  validation {
    condition     = contains(["public", "waf", "staging", "private", "rollback"], var.edge_phase)
    error_message = "edge_phase must be one of: public, waf, staging, private, rollback."
  }
}

variable "cloudfront_staging_selector" {
  description = "Sensitive selector value for header-routed CloudFront staging requests."
  type        = string
  default     = ""
  sensitive   = true
}

# REL-17 (docs/backlog/cdo02-reliability-cost-backlog.md) - SSO-based access to the
# private EKS API via Cloudflare Zero Trust, as an addition to (not replacement of) the
# SSM bastion. Defaults keep this entirely inert until someone deliberately opts in -
# see docs/runbooks/cloudflare-zero-trust-access.md before setting enable = true.
variable "enable_cloudflare_access" {
  description = "Provision the Cloudflare Tunnel + Access application for SSO-based EKS API access. Requires CLOUDFLARE_API_TOKEN env var and the other cloudflare_* variables set."
  type        = bool
  default     = false
}

variable "cloudflare_account_id" {
  description = "Cloudflare account ID. Required when enable_cloudflare_access = true."
  type        = string
  default     = ""
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID for the domain hosting the tunnel hostname. Required when enable_cloudflare_access = true."
  type        = string
  default     = ""
}

variable "cloudflare_zone_name" {
  description = "Domain name matching cloudflare_zone_id, e.g. techx-tf3-ops.com."
  type        = string
  default     = ""
}

variable "cloudflare_tunnel_hostname" {
  description = "Public hostname proxying to the EKS API, e.g. kubectl.techx-tf3-ops.com. Required when enable_cloudflare_access = true."
  type        = string
  default     = ""
}

variable "cloudflare_allowed_email_domain" {
  description = "Email domain allowed to authenticate via SSO (Access policy). Leave empty and use cloudflare_allowed_emails for a short allowlist instead."
  type        = string
  default     = ""
}

variable "cloudflare_allowed_emails" {
  description = "Explicit allowlist of emails permitted to authenticate, used when cloudflare_allowed_email_domain is empty."
  type        = list(string)
  default     = []
}

# ---------- Mandate #8: managed datastores (RDS / ElastiCache / MSK) ----------
variable "enable_managed_datastores" {
  description = "Bật tầng datastore managed (Mandate #8). false = không tạo gì (giữ in-cluster)."
  type        = bool
  default     = false
}

variable "datastores_name_prefix" {
  description = "Prefix ngắn cho tên tài nguyên/secret datastore (vd techx-tf3)."
  type        = string
  default     = "techx-tf3"
}

variable "audit_detection_email_subscriptions" {
  description = "Email recipients for Mandate 11 audit alerts."
  type        = list(string)
  default     = []
}

variable "audit_detection_additional_human_principal_arns" {
  description = "Extra human principal ARNs reviewed by the detector, for example mentor or admin users not already modeled in iam-production-access.tf."
  type        = list(string)
  default     = []
}

variable "audit_detection_additional_allowed_automation_principal_arns" {
  description = "Extra automation principal ARNs allowlisted by the detector."
  type        = list(string)
  default     = []
}

variable "audit_detection_additional_secret_reader_principal_arns" {
  description = "Extra automation principal ARNs that may read watched secrets without paging."
  type        = list(string)
  default     = []
}

variable "audit_detection_additional_sensitive_secret_names" {
  description = "Extra Secrets Manager names that should be watched for human reads."
  type        = list(string)
  default     = []
}

variable "audit_detection_suppressions" {
  description = "Time-bounded suppressions evaluated by the audit alert Lambda."
  type = list(object({
    actor    = string
    resource = string
    start    = string
    end      = string
    reason   = string
  }))
  default = []
}

variable "audit_detection_lambda_log_retention_days" {
  description = "Retention for audit detection Lambda logs."
  type        = number
  default     = 14
}

variable "audit_detection_trail_s3_retention_days" {
  description = "Retention for audit CloudTrail objects in S3."
  type        = number
  default     = 30
}

# --- Cost guardrails (Cost Anomaly Detection + Budgets) --------------------------

variable "enable_cost_guardrails" {
  description = "Provision AWS Cost Anomaly Detection + a hard-ceiling Budget (global services, created via the us-east-1 provider)."
  type        = bool
  default     = false
}

variable "cost_guardrails_email_subscriptions" {
  description = "Email recipients for cost alerts. When empty, falls back to audit_detection_email_subscriptions so cost alerts share the audit alert-plane inboxes."
  type        = list(string)
  default     = []
}

variable "cost_guardrails_monthly_budget_limit_usd" {
  description = "Monthly hard-ceiling budget in USD. Defaults to the $300/week/TF ceiling projected over an average month."
  type        = number
  default     = 1300
}

variable "cost_guardrails_anomaly_impact_threshold_usd" {
  description = "Absolute total-impact (USD) at or above which a detected cost anomaly triggers an alert."
  type        = number
  default     = 30
}
