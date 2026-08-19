variable "name_prefix" {
  description = "Prefix for cost-guardrails resources (topic, KMS alias, budget, anomaly monitor). Usually the cluster name."
  type        = string
}

variable "alert_email_subscriptions" {
  description = "Email addresses that receive budget breach and cost-anomaly alerts. Reuse the audit alert-plane recipients so cost alerts land in the same inboxes."
  type        = list(string)
  default     = []
}

# AWS Budgets has no WEEKLY time unit. The team ceiling is $300/week/TF, so the
# monthly budget is that weekly ceiling projected over an average month
# (300 * 52 / 12 ≈ 1300). A monthly budget smooths out the weekly cadence but is
# the only native way to alarm on a hard dollar ceiling; the Cost Anomaly monitor
# below is what catches sudden weekly spikes between month boundaries.
variable "monthly_budget_limit_usd" {
  description = "Monthly hard-ceiling for the COST budget, in USD. Defaults to the $300/week ceiling projected monthly."
  type        = number
  default     = 1300
}

variable "budget_thresholds_percent" {
  description = "Budget notification thresholds. Each entry is a percentage of the limit and whether it fires on ACTUAL or FORECASTED spend."
  type = list(object({
    percent = number
    type    = string # ACTUAL or FORECASTED
  }))
  default = [
    { percent = 80, type = "ACTUAL" },
    { percent = 100, type = "ACTUAL" },
    { percent = 100, type = "FORECASTED" },
  ]
}

# Absolute-dollar impact at which a detected anomaly pages. Scaled to the
# $300/week ceiling: a single anomaly of $30 is ~10% of the weekly budget, large
# enough to matter and rare enough not to be noise. AWS Cost Anomaly Detection
# still learns the per-service baseline; this is only the reporting floor.
variable "anomaly_impact_threshold_usd" {
  description = "Absolute total-impact (USD) at or above which a detected anomaly triggers an alert."
  type        = number
  default     = 30
}

variable "anomaly_subscription_frequency" {
  description = "Cost Anomaly Detection alert frequency. Must be IMMEDIATE when the subscriber is an SNS topic."
  type        = string
  default     = "IMMEDIATE"

  validation {
    condition     = contains(["IMMEDIATE", "DAILY", "WEEKLY"], var.anomaly_subscription_frequency)
    error_message = "anomaly_subscription_frequency must be one of IMMEDIATE, DAILY, WEEKLY."
  }
}

variable "tags" {
  description = "Extra tags merged onto taggable resources."
  type        = map(string)
  default     = {}
}
