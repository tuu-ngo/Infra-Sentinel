data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_region" "current" {}

locals {
  sns_topic_name = "${var.name_prefix}-cost-alerts"
  budget_name    = "${var.name_prefix}-monthly-ceiling"

  sns_topic_arn = "arn:${data.aws_partition.current.partition}:sns:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:${local.sns_topic_name}"

  # Budgets is a global service; its ARN carries an empty region field. Built as a
  # string so the SNS topic policy can name the budget as a SourceArn without a
  # dependency cycle (the budget's notification references the topic in return).
  budget_arn = "arn:${data.aws_partition.current.partition}:budgets::${data.aws_caller_identity.current.account_id}:budget/${local.budget_name}"

  # Services that publish into the alert topic. Both AWS Budgets and Cost Anomaly
  # Detection call sns:Publish on the topic and, because the topic is CMK-encrypted,
  # must also call kms:GenerateDataKey*/Decrypt on the key — granting sns:Publish
  # alone yields a silent AuthorizationError and the alert never arrives.
  cost_service_principals = [
    "budgets.amazonaws.com",
    "costalerts.amazonaws.com",
  ]
}

# --- KMS key for the alert topic -------------------------------------------------

data "aws_iam_policy_document" "cost_alerts_kms" {
  statement {
    sid    = "EnableAccountRootPermissions"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    actions   = ["kms:*"]
    resources = ["*"]
  }

  statement {
    sid    = "AllowSnsUseOfKey"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }

    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey*",
    ]
    resources = ["*"]

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [local.sns_topic_arn]
    }
  }

  # Budgets and Cost Anomaly Detection are the publishers; the KMS request is made
  # under their service principal, scoped to this account to block confused-deputy.
  statement {
    sid    = "AllowCostServicesUseOfKey"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = local.cost_service_principals
    }

    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey*",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_kms_key" "cost_alerts" {
  description             = "Encryption for ${local.sns_topic_name}"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.cost_alerts_kms.json

  tags = var.tags
}

resource "aws_kms_alias" "cost_alerts" {
  name          = "alias/${var.name_prefix}-cost-alerts"
  target_key_id = aws_kms_key.cost_alerts.key_id
}

# --- Alert topic + subscriptions -------------------------------------------------

resource "aws_sns_topic" "cost_alerts" {
  name              = local.sns_topic_name
  kms_master_key_id = aws_kms_key.cost_alerts.arn

  tags = var.tags
}

resource "aws_sns_topic_subscription" "email" {
  for_each = toset(var.alert_email_subscriptions)

  topic_arn = aws_sns_topic.cost_alerts.arn
  protocol  = "email"
  endpoint  = each.value
}

# Setting an explicit topic policy REPLACES the SNS default policy, so the account
# owner statement must be restated alongside the two service-publish grants.
data "aws_iam_policy_document" "cost_alerts_topic" {
  statement {
    sid    = "AllowAccountOwnerManage"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    actions = [
      "sns:GetTopicAttributes",
      "sns:SetTopicAttributes",
      "sns:AddPermission",
      "sns:RemovePermission",
      "sns:DeleteTopic",
      "sns:Subscribe",
      "sns:ListSubscriptionsByTopic",
      "sns:Publish",
    ]
    resources = [aws_sns_topic.cost_alerts.arn]
  }

  statement {
    sid    = "AllowBudgetsPublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }

    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.cost_alerts.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [local.budget_arn]
    }
  }

  statement {
    sid    = "AllowCostAnomalyPublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["costalerts.amazonaws.com"]
    }

    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.cost_alerts.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "cost_alerts" {
  arn    = aws_sns_topic.cost_alerts.arn
  policy = data.aws_iam_policy_document.cost_alerts_topic.json
}

# --- Layer 2: hard-ceiling budget ------------------------------------------------

resource "aws_budgets_budget" "monthly_ceiling" {
  name         = local.budget_name
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Match the manual RECORD_TYPE=Usage measurement: the account is 100% credit-
  # covered, so counting credits/refunds/tax would show ~$0 and mask real usage.
  # include_credit = false is the load-bearing setting here.
  cost_types {
    include_credit             = false
    include_refund             = false
    include_tax                = false
    include_upfront            = true
    include_recurring          = true
    include_subscription       = true
    include_support            = true
    include_other_subscription = true
    include_discount           = true
    use_amortized              = false
    use_blended                = false
  }

  dynamic "notification" {
    for_each = var.budget_thresholds_percent

    content {
      comparison_operator       = "GREATER_THAN"
      threshold                 = notification.value.percent
      threshold_type            = "PERCENTAGE"
      notification_type         = notification.value.type
      subscriber_sns_topic_arns = [aws_sns_topic.cost_alerts.arn]
    }
  }

  depends_on = [aws_sns_topic_policy.cost_alerts]
}

# --- Layer 1: Cost Anomaly Detection ---------------------------------------------

# DIMENSIONAL/SERVICE covers every service in the account with AWS's own learned
# baseline — it catches the orphaned-resource class of spike (e.g. an idle
# OpenSearch Serverless OCU) without an explicit per-service rule. It is account-
# wide, so it also sees the out-of-Phase-3 Tokyo workload; if that becomes noise,
# switch to a CUSTOM monitor filtered on the `project` cost-allocation tag once
# that tag is activated in the billing console (see ADR 0017).
resource "aws_ce_anomaly_monitor" "service" {
  name              = "${var.name_prefix}-service-monitor"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"

  tags = var.tags
}

resource "aws_ce_anomaly_subscription" "this" {
  name             = "${var.name_prefix}-anomaly-subscription"
  frequency        = var.anomaly_subscription_frequency
  monitor_arn_list = [aws_ce_anomaly_monitor.service.arn]

  subscriber {
    type    = "SNS"
    address = aws_sns_topic.cost_alerts.arn
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      match_options = ["GREATER_THAN_OR_EQUAL"]
      values        = [tostring(var.anomaly_impact_threshold_usd)]
    }
  }

  tags = var.tags

  # AWS test-publishes to the topic when the subscription is created, so the
  # topic policy granting costalerts.amazonaws.com must already exist.
  depends_on = [aws_sns_topic_policy.cost_alerts]
}
