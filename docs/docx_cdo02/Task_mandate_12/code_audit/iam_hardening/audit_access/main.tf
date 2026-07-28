data "aws_iam_policy_document" "audit_access_trust" {
  statement {
    sid     = "AllowApprovedSecurityOwners"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = var.trusted_principal_arns
    }

    dynamic "condition" {
      for_each = var.require_mfa ? [true] : []

      content {
        test     = "Bool"
        variable = "aws:MultiFactorAuthPresent"
        values   = ["true"]
      }
    }
  }
}

data "aws_iam_policy_document" "audit_read" {
  statement {
    sid = "ReadAuditArchiveBucketMetadata"
    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket"
    ]
    resources = [var.audit_bucket_arn]
  }

  statement {
    sid = "ReadAuditArchiveObjects"
    actions = [
      "s3:GetObject",
      "s3:GetObjectLegalHold",
      "s3:GetObjectRetention",
      "s3:GetObjectVersion"
    ]
    resources = ["${var.audit_bucket_arn}/*"]
  }

  # DescribeTrails is an account-level list/read API and must use "*".
  statement {
    sid       = "ListTrailConfigurations"
    actions   = ["cloudtrail:DescribeTrails"]
    resources = ["*"]
  }

  statement {
    sid = "ReadProtectedTrailConfiguration"
    actions = [
      "cloudtrail:GetEventSelectors",
      "cloudtrail:GetInsightSelectors",
      "cloudtrail:GetTrailStatus"
    ]
    resources = [var.audit_trail_arn]
  }

  statement {
    sid       = "LookupManagementEvents"
    actions   = ["cloudtrail:LookupEvents"]
    resources = ["*"]
  }

  statement {
    sid = "ReadAntiTamperRules"
    actions = [
      "events:DescribeRule",
      "events:ListTargetsByRule"
    ]
    resources = tolist(var.audit_rule_arns)
  }

  statement {
    sid = "ReadAlertTopics"
    actions = [
      "sns:GetTopicAttributes",
      "sns:ListSubscriptionsByTopic"
    ]
    resources = tolist(var.alert_topic_arns)
  }
}

data "aws_iam_policy_document" "breakglass_recovery" {
  statement {
    sid = "RestartOnlyProtectedTrail"
    actions = [
      "cloudtrail:GetTrailStatus",
      "cloudtrail:StartLogging"
    ]
    resources = [var.audit_trail_arn]
  }

  statement {
    sid = "EnableOnlyAntiTamperRules"
    actions = [
      "events:DescribeRule",
      "events:EnableRule",
      "events:ListTargetsByRule"
    ]
    resources = tolist(var.audit_rule_arns)
  }

  statement {
    sid = "ReadAndTestAlertTopics"
    actions = [
      "sns:GetTopicAttributes",
      "sns:Publish"
    ]
    resources = tolist(var.alert_topic_arns)
  }
}

data "aws_iam_policy_document" "security_owner_assume_audit" {
  statement {
    sid       = "AssumeProtectedAuditRoles"
    actions   = ["sts:AssumeRole"]
    resources = [aws_iam_role.audit_admin.arn, aws_iam_role.breakglass.arn]
  }
}

resource "aws_iam_role" "audit_admin" {
  name                 = "${var.name_prefix}-audit-admin"
  description          = "Mandate 12 read-only evidence access; no audit-control mutation."
  assume_role_policy   = data.aws_iam_policy_document.audit_access_trust.json
  max_session_duration = 3600

  tags = {
    Project   = "TF3"
    Mandate   = "12"
    Purpose   = "audit-evidence-read-only"
    Protected = "true"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role" "breakglass" {
  name                 = "${var.name_prefix}-audit-breakglass"
  description          = "Mandate 12 narrowly scoped recovery for StartLogging and EnableRule only."
  assume_role_policy   = data.aws_iam_policy_document.audit_access_trust.json
  max_session_duration = 3600

  tags = {
    Project   = "TF3"
    Mandate   = "12"
    Purpose   = "audit-recovery-only"
    Protected = "true"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_policy" "audit_read" {
  name        = "${var.name_prefix}-audit-read"
  description = "Mandate 12 read-only evidence policy for the protected audit archive and controls."
  policy      = data.aws_iam_policy_document.audit_read.json

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_policy" "breakglass_recovery" {
  name        = "${var.name_prefix}-audit-breakglass-recovery"
  description = "Mandate 12 minimal recovery policy; it cannot delete or reconfigure audit controls."
  policy      = data.aws_iam_policy_document.breakglass_recovery.json

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_policy" "security_owner_assume_audit" {
  name        = "${var.name_prefix}-security-owner-assume-audit"
  description = "Mandate 12 minimal policy allowing approved security owners to assume protected audit roles."
  policy      = data.aws_iam_policy_document.security_owner_assume_audit.json

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy_attachment" "audit_admin_read" {
  role       = aws_iam_role.audit_admin.name
  policy_arn = aws_iam_policy.audit_read.arn
}

resource "aws_iam_role_policy_attachment" "breakglass_recovery" {
  role       = aws_iam_role.breakglass.name
  policy_arn = aws_iam_policy.breakglass_recovery.arn
}
