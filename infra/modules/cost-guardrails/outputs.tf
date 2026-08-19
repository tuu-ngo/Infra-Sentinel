output "sns_topic_arn" {
  description = "ARN of the cost alert SNS topic (budget breaches + anomalies)."
  value       = aws_sns_topic.cost_alerts.arn
}

output "kms_key_arn" {
  description = "CMK encrypting the cost alert topic."
  value       = aws_kms_key.cost_alerts.arn
}

output "budget_name" {
  description = "Name of the monthly hard-ceiling budget."
  value       = aws_budgets_budget.monthly_ceiling.name
}

output "anomaly_monitor_arn" {
  description = "ARN of the Cost Anomaly Detection monitor."
  value       = aws_ce_anomaly_monitor.service.arn
}

output "anomaly_subscription_arn" {
  description = "ARN of the Cost Anomaly Detection subscription."
  value       = aws_ce_anomaly_subscription.this.arn
}
