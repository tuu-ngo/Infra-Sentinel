# Cost guardrails — Layer 1 (Cost Anomaly Detection) + Layer 2 (Budgets).
#
# Both are global AWS services whose API endpoint lives in us-east-1, so the
# module is instantiated with the aws.us_east_1 provider. The alert SNS topic and
# its CMK are created in us-east-1 as well — Budgets and Cost Anomaly Detection
# can only publish to a us-east-1 topic.
#
# Recipients default to the audit alert-plane inboxes so cost alerts land in the
# same mailboxes teams already watch; override with cost_guardrails_email_subscriptions.
locals {
  cost_guardrails_email_subscriptions = length(var.cost_guardrails_email_subscriptions) > 0 ? var.cost_guardrails_email_subscriptions : var.audit_detection_email_subscriptions
}

module "cost_guardrails" {
  count  = var.enable_cost_guardrails ? 1 : 0
  source = "../../modules/cost-guardrails"

  providers = {
    aws = aws.us_east_1
  }

  name_prefix                  = var.cluster_name
  alert_email_subscriptions    = local.cost_guardrails_email_subscriptions
  monthly_budget_limit_usd     = var.cost_guardrails_monthly_budget_limit_usd
  anomaly_impact_threshold_usd = var.cost_guardrails_anomaly_impact_threshold_usd
}
