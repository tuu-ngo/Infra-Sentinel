data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  account_id      = data.aws_caller_identity.current.account_id
  audit_trail_arn = "arn:${data.aws_partition.current.partition}:cloudtrail:${var.region}:${local.account_id}:trail/${var.trail_name}"

  # These controls live with the TF3 workload and audit archive in the primary Region.
  anti_audit_rule_names = {
    trail            = "tf3-m12-audit-trail-changes"
    trail_selectors  = "tf3-m12-audit-trail-selector-changes"
    bucket           = "tf3-m12-audit-bucket-changes"
    event_rule       = "tf3-m12-audit-alert-rule-changes"
    event_target     = "tf3-m12-audit-alert-target-changes"
    sns_topic        = "tf3-m12-audit-alert-topic-changes"
    sns_subscription = "tf3-m12-audit-alert-subscription-changes"
  }

  # IAM global-service events are delivered to us-east-1; these controls are
  # intentionally separate from the primary-region alert resources.
  global_anti_audit_rule_names = {
    iam              = "tf3-m12-audit-iam-tamper"
    event_rule       = "tf3-m12-audit-global-rule-changes"
    event_target     = "tf3-m12-audit-global-target-changes"
    sns_topic        = "tf3-m12-audit-global-topic-changes"
    sns_subscription = "tf3-m12-audit-global-subscription-changes"
  }

  anti_audit_event_patterns = {
    trail = jsonencode({
      source        = ["aws.cloudtrail"]
      "detail-type" = ["AWS API Call via CloudTrail"]
      detail = {
        eventSource = ["cloudtrail.amazonaws.com"]
        eventName   = ["StopLogging", "StartLogging", "DeleteTrail", "UpdateTrail"]
        requestParameters = {
          name = [var.trail_name]
        }
      }
    })

    trail_selectors = jsonencode({
      source        = ["aws.cloudtrail"]
      "detail-type" = ["AWS API Call via CloudTrail"]
      detail = {
        eventSource = ["cloudtrail.amazonaws.com"]
        eventName   = ["PutEventSelectors", "PutInsightSelectors"]
        requestParameters = {
          trailName = [var.trail_name]
        }
      }
    })

    # The source must be aws.s3 for S3 API events delivered through CloudTrail.
    # Object-level matches only receive events if a non-recursive source logs
    # audit-bucket data events; see foundation/README.md before testing them.
    bucket = jsonencode({
      source        = ["aws.s3"]
      "detail-type" = ["AWS API Call via CloudTrail"]
      detail = {
        eventSource = ["s3.amazonaws.com"]
        eventName = [
          "PutBucketPolicy",
          "DeleteBucketPolicy",
          "PutBucketVersioning",
          "PutObjectLockConfiguration",
          "PutBucketLifecycleConfiguration",
          "DeleteBucketLifecycle",
          "PutBucketEncryption",
          "DeleteBucketEncryption",
          "PutPublicAccessBlock",
          "DeletePublicAccessBlock",
          "PutBucketAcl",
          "PutBucketOwnershipControls",
          "DeleteBucketOwnershipControls",
          "PutBucketReplication",
          "DeleteBucketReplication",
          "PutBucketNotification",
          "PutBucketTagging",
          "DeleteBucketTagging",
          "PutObject",
          "CopyObject",
          "CompleteMultipartUpload",
          "AbortMultipartUpload",
          "PutObjectAcl",
          "PutObjectTagging",
          "DeleteObjectTagging",
          "PutObjectRetention",
          "PutObjectLegalHold",
          "RestoreObject",
          "DeleteObject",
          "DeleteObjects",
          "DeleteObjectVersion",
          "DeleteBucket"
        ]
        requestParameters = {
          bucketName = [aws_s3_bucket.audit.id]
        }
      }
    })

    event_rule = jsonencode({
      source        = ["aws.events"]
      "detail-type" = ["AWS API Call via CloudTrail"]
      detail = {
        eventSource = ["events.amazonaws.com"]
        eventName   = ["DisableRule", "DeleteRule", "PutRule"]
        requestParameters = {
          name = values(local.anti_audit_rule_names)
        }
      }
    })

    event_target = jsonencode({
      source        = ["aws.events"]
      "detail-type" = ["AWS API Call via CloudTrail"]
      detail = {
        eventSource = ["events.amazonaws.com"]
        eventName   = ["RemoveTargets", "PutTargets"]
        requestParameters = {
          rule = values(local.anti_audit_rule_names)
        }
      }
    })

    sns_topic = jsonencode({
      source        = ["aws.sns"]
      "detail-type" = ["AWS API Call via CloudTrail"]
      detail = {
        eventSource = ["sns.amazonaws.com"]
        eventName   = ["DeleteTopic", "SetTopicAttributes", "Subscribe", "AddPermission", "RemovePermission"]
        requestParameters = {
          topicArn = [aws_sns_topic.audit_alerts.arn]
        }
      }
    })

    sns_subscription = jsonencode({
      source        = ["aws.sns"]
      "detail-type" = ["AWS API Call via CloudTrail"]
      detail = {
        eventSource = ["sns.amazonaws.com"]
        eventName   = ["Unsubscribe", "SetSubscriptionAttributes"]
        requestParameters = {
          subscriptionArn = [{
            prefix = "${aws_sns_topic.audit_alerts.arn}:"
          }]
        }
      }
    })
  }

  global_anti_audit_event_patterns = {
    iam = jsonencode({
      source        = ["aws.iam"]
      "detail-type" = ["AWS API Call via CloudTrail"]
      detail = {
        eventSource = ["iam.amazonaws.com"]
        eventName = [
          "AttachGroupPolicy",
          "DetachGroupPolicy",
          "PutGroupPolicy",
          "DeleteGroupPolicy",
          "AddUserToGroup",
          "RemoveUserFromGroup",
          "AttachRolePolicy",
          "DetachRolePolicy",
          "PutRolePolicy",
          "DeleteRolePolicy",
          "PutRolePermissionsBoundary",
          "DeleteRolePermissionsBoundary",
          "UpdateAssumeRolePolicy",
          "AttachUserPolicy",
          "DetachUserPolicy",
          "PutUserPolicy",
          "DeleteUserPolicy",
          "PutUserPermissionsBoundary",
          "DeleteUserPermissionsBoundary",
          "CreateUser",
          "DeleteUser",
          "CreateRole",
          "DeleteRole",
          "CreateAccessKey",
          "UpdateAccessKey",
          "DeleteAccessKey",
          "CreateLoginProfile",
          "UpdateLoginProfile",
          "DeleteLoginProfile",
          "CreateVirtualMFADevice",
          "EnableMFADevice",
          "DeactivateMFADevice",
          "DeleteVirtualMFADevice",
          "ResyncMFADevice",
          "CreatePolicyVersion",
          "SetDefaultPolicyVersion",
          "DeletePolicyVersion",
          "DeletePolicy"
        ]
      }
    })

    event_rule = jsonencode({
      source        = ["aws.events"]
      "detail-type" = ["AWS API Call via CloudTrail"]
      detail = {
        eventSource = ["events.amazonaws.com"]
        eventName   = ["DisableRule", "DeleteRule", "PutRule"]
        requestParameters = {
          name = values(local.global_anti_audit_rule_names)
        }
      }
    })

    event_target = jsonencode({
      source        = ["aws.events"]
      "detail-type" = ["AWS API Call via CloudTrail"]
      detail = {
        eventSource = ["events.amazonaws.com"]
        eventName   = ["RemoveTargets", "PutTargets"]
        requestParameters = {
          rule = values(local.global_anti_audit_rule_names)
        }
      }
    })

    sns_topic = jsonencode({
      source        = ["aws.sns"]
      "detail-type" = ["AWS API Call via CloudTrail"]
      detail = {
        eventSource = ["sns.amazonaws.com"]
        eventName   = ["DeleteTopic", "SetTopicAttributes", "Subscribe", "AddPermission", "RemovePermission"]
        requestParameters = {
          topicArn = [aws_sns_topic.audit_alerts_global.arn]
        }
      }
    })

    sns_subscription = jsonencode({
      source        = ["aws.sns"]
      "detail-type" = ["AWS API Call via CloudTrail"]
      detail = {
        eventSource = ["sns.amazonaws.com"]
        eventName   = ["Unsubscribe", "SetSubscriptionAttributes"]
        requestParameters = {
          subscriptionArn = [{
            prefix = "${aws_sns_topic.audit_alerts_global.arn}:"
          }]
        }
      }
    })
  }
}

resource "aws_s3_bucket" "audit" {
  bucket              = var.audit_bucket_name
  object_lock_enabled = true

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = local.account_id == "197826770971"
      error_message = "Sai AWS account: chỉ được deploy vào account TF3 đã phê duyệt."
    }
  }
}

resource "aws_s3_bucket_versioning" "audit" {
  bucket = aws_s3_bucket.audit.id

  versioning_configuration {
    status = "Enabled"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_object_lock_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.retention_days
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [aws_s3_bucket_versioning.audit]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "audit" {
  bucket = aws_s3_bucket.audit.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true

  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "audit_bucket" {
  statement {
    sid     = "AWSCloudTrailAclCheck"
    effect  = "Allow"
    actions = ["s3:GetBucketAcl"]

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    resources = [aws_s3_bucket.audit.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [local.audit_trail_arn]
    }
  }

  statement {
    sid     = "AWSCloudTrailWrite"
    effect  = "Allow"
    actions = ["s3:PutObject"]

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    resources = ["${aws_s3_bucket.audit.arn}/AWSLogs/${local.account_id}/*"]

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [local.audit_trail_arn]
    }
  }

  # CloudTrail is the only service permitted to mutate archive objects. The
  # preceding Allow remains further constrained to this exact trail ARN.
  statement {
    sid    = "DenyNonCloudTrailObjectMutation"
    effect = "Deny"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:BypassGovernanceRetention",
      "s3:DeleteObject",
      "s3:DeleteObjectTagging",
      "s3:DeleteObjectVersion",
      "s3:DeleteObjectVersionTagging",
      "s3:PutObject",
      "s3:PutObjectAcl",
      "s3:PutObjectLegalHold",
      "s3:PutObjectRetention",
      "s3:PutObjectTagging",
      "s3:PutObjectVersionAcl",
      "s3:PutObjectVersionTagging",
      "s3:RestoreObject"
    ]
    resources = ["${aws_s3_bucket.audit.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotEqualsIfExists"
      variable = "aws:PrincipalServiceName"
      values   = ["cloudtrail.amazonaws.com"]
    }
  }
}

resource "aws_s3_bucket_policy" "audit" {
  bucket = aws_s3_bucket.audit.id
  policy = data.aws_iam_policy_document.audit_bucket.json

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_cloudtrail" "audit" {
  name                          = var.trail_name
  s3_bucket_name                = aws_s3_bucket.audit.id
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  enable_logging                = true

  tags = {
    Project   = "TF3"
    Mandate   = "12"
    Purpose   = "audit-anti-defeat"
    Protected = "true"
  }

  advanced_event_selector {
    name = "ManagementReadWrite"

    field_selector {
      field  = "eventCategory"
      equals = ["Management"]
    }
  }

  advanced_event_selector {
    name = "ApprovedSensitiveS3Objects"

    field_selector {
      field  = "eventCategory"
      equals = ["Data"]
    }

    field_selector {
      field  = "resources.type"
      equals = ["AWS::S3::Object"]
    }

    field_selector {
      field       = "resources.ARN"
      starts_with = var.s3_data_event_arns
    }
  }

  lifecycle {
    prevent_destroy = true

    # Selecting the archive itself would cause CloudTrail to log its own log
    # deliveries. Keep that bucket out of the data selector by construction.
    precondition {
      condition = alltrue([
        for arn in var.s3_data_event_arns : !startswith(arn, "${aws_s3_bucket.audit.arn}/")
      ])
      error_message = "s3_data_event_arns must not include the Mandate 12 audit archive bucket or any of its prefixes."
    }
  }

  # Do not create the trail until immutable retention and all delivery
  # protections are in place on its destination bucket.
  depends_on = [
    aws_s3_bucket_object_lock_configuration.audit,
    aws_s3_bucket_server_side_encryption_configuration.audit,
    aws_s3_bucket_public_access_block.audit,
    aws_s3_bucket_policy.audit
  ]
}

resource "aws_sns_topic" "audit_alerts" {
  name = "tf3-m12-audit-alerts"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_cloudwatch_event_rule" "anti_audit" {
  for_each = local.anti_audit_event_patterns

  name          = local.anti_audit_rule_names[each.key]
  description   = "Alert on changes to TF3 Mandate 12 audit controls: ${each.key}."
  event_pattern = each.value
  state         = "ENABLED"

  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "sns_for_eventbridge" {
  statement {
    sid     = "AllowEventBridgePublish"
    effect  = "Allow"
    actions = ["sns:Publish"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    resources = [aws_sns_topic.audit_alerts.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [for rule in aws_cloudwatch_event_rule.anti_audit : rule.arn]
    }
  }
}

resource "aws_sns_topic_policy" "audit_alerts" {
  arn    = aws_sns_topic.audit_alerts.arn
  policy = data.aws_iam_policy_document.sns_for_eventbridge.json

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_cloudwatch_event_target" "anti_audit_sns" {
  for_each = aws_cloudwatch_event_rule.anti_audit

  rule       = each.value.name
  target_id  = "audit-alerts-sns-${each.key}"
  arn        = aws_sns_topic.audit_alerts.arn
  depends_on = [aws_sns_topic_policy.audit_alerts]

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.audit_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_sns_topic" "audit_alerts_global" {
  provider = aws.global_events
  name     = "tf3-m12-audit-global-alerts"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_cloudwatch_event_rule" "anti_audit_global" {
  provider = aws.global_events
  for_each = local.global_anti_audit_event_patterns

  name          = local.global_anti_audit_rule_names[each.key]
  description   = "Alert on TF3 Mandate 12 global IAM and alert-control changes: ${each.key}."
  event_pattern = each.value
  state         = "ENABLED"

  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "sns_for_eventbridge_global" {
  provider = aws.global_events

  statement {
    sid     = "AllowEventBridgePublish"
    effect  = "Allow"
    actions = ["sns:Publish"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    resources = [aws_sns_topic.audit_alerts_global.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [for rule in aws_cloudwatch_event_rule.anti_audit_global : rule.arn]
    }
  }
}

resource "aws_sns_topic_policy" "audit_alerts_global" {
  provider = aws.global_events
  arn      = aws_sns_topic.audit_alerts_global.arn
  policy   = data.aws_iam_policy_document.sns_for_eventbridge_global.json

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_cloudwatch_event_target" "anti_audit_sns_global" {
  provider = aws.global_events
  for_each = aws_cloudwatch_event_rule.anti_audit_global

  rule       = each.value.name
  target_id  = "audit-alerts-sns-${each.key}"
  arn        = aws_sns_topic.audit_alerts_global.arn
  depends_on = [aws_sns_topic_policy.audit_alerts_global]

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_sns_topic_subscription" "email_global" {
  provider  = aws.global_events
  topic_arn = aws_sns_topic.audit_alerts_global.arn
  protocol  = "email"
  endpoint  = var.alert_email

  lifecycle {
    prevent_destroy = true
  }
}
