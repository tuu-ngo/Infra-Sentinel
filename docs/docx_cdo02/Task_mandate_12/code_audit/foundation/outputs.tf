output "audit_bucket_name" {
  value = aws_s3_bucket.audit.id
}

output "trail_arn" {
  value = aws_cloudtrail.audit.arn
}

output "trail_name" {
  value = aws_cloudtrail.audit.name
}

output "alert_topic_arn" {
  value = aws_sns_topic.audit_alerts.arn
}

output "global_alert_topic_arn" {
  value = aws_sns_topic.audit_alerts_global.arn
}

output "alert_subscription_arn" {
  description = "Primary-region SNS subscription ARN. It can be pending until the recipient confirms and state is refreshed."
  value       = aws_sns_topic_subscription.email.arn
}

output "global_alert_subscription_arn" {
  description = "us-east-1 SNS subscription ARN. It can be pending until the recipient confirms and state is refreshed."
  value       = aws_sns_topic_subscription.email_global.arn
}

output "anti_audit_rule_arns" {
  value = {
    for key, rule in aws_cloudwatch_event_rule.anti_audit : key => rule.arn
  }
}

output "global_anti_audit_rule_arns" {
  value = {
    for key, rule in aws_cloudwatch_event_rule.anti_audit_global : key => rule.arn
  }
}

output "alert_regions" {
  value = {
    primary_region      = var.region
    global_event_region = var.global_event_region
  }
}
