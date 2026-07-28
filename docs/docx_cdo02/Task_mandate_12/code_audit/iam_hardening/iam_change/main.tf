locals {
  target_identity_arns = concat(tolist(var.target_user_arns), tolist(var.target_role_arns))
}

data "aws_iam_policy_document" "iam_change_trust" {
  statement {
    sid     = "AllowMfaProtectedSecurityOwners"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = var.trusted_change_owner_arns
    }

    condition {
      test     = "Bool"
      variable = "aws:MultiFactorAuthPresent"
      values   = ["true"]
    }
  }
}

data "aws_iam_policy_document" "iam_change_executor" {
  statement {
    sid = "ReadAndSimulateIamState"
    actions = [
      "iam:GetPolicy",
      "iam:GetPolicyVersion",
      "iam:GetRole",
      "iam:GetUser",
      "iam:ListAttachedRolePolicies",
      "iam:ListAttachedUserPolicies",
      "iam:ListPolicyVersions",
      "iam:SimulatePrincipalPolicy"
    ]
    resources = ["*"]
  }

  statement {
    sid = "UpdateOnlyRenderedBoundaryPolicy"
    actions = [
      "iam:CreatePolicyVersion",
      "iam:DeletePolicyVersion",
      "iam:SetDefaultPolicyVersion"
    ]
    resources = [var.operator_boundary_policy_arn]
  }

  dynamic "statement" {
    for_each = length(var.target_user_arns) > 0 ? [true] : []

    content {
      sid       = "AttachExactBoundaryToApprovedUsers"
      actions   = ["iam:PutUserPermissionsBoundary"]
      resources = tolist(var.target_user_arns)

      condition {
        test     = "StringEquals"
        variable = "iam:PermissionsBoundary"
        values   = [var.operator_boundary_policy_arn]
      }
    }
  }

  dynamic "statement" {
    for_each = length(var.target_role_arns) > 0 ? [true] : []

    content {
      sid       = "AttachExactBoundaryToApprovedRoles"
      actions   = ["iam:PutRolePermissionsBoundary"]
      resources = tolist(var.target_role_arns)

      condition {
        test     = "StringEquals"
        variable = "iam:PermissionsBoundary"
        values   = [var.operator_boundary_policy_arn]
      }
    }
  }

  dynamic "statement" {
    for_each = var.allow_boundary_removal ? [true] : []

    content {
      sid = "EmergencyRollbackApprovedBoundaries"
      actions = [
        "iam:DeleteRolePermissionsBoundary",
        "iam:DeleteUserPermissionsBoundary"
      ]
      resources = local.target_identity_arns
    }
  }
}

resource "aws_iam_role" "iam_change" {
  name                 = "${var.name_prefix}-iam-change"
  description          = "Mandate 12 MFA-protected executor for one reviewed operator boundary and explicit targets only."
  assume_role_policy   = data.aws_iam_policy_document.iam_change_trust.json
  max_session_duration = 3600

  tags = {
    Project   = "TF3"
    Mandate   = "12"
    Purpose   = "boundary-change-executor"
    Protected = "true"
  }

  lifecycle {
    precondition {
      condition     = length(local.target_identity_arns) > 0
      error_message = "At least one explicit target user or role ARN is required."
    }

    prevent_destroy = true
  }
}

resource "aws_iam_policy" "iam_change_executor" {
  name        = "${var.name_prefix}-iam-change-executor"
  description = "Mandate 12 least-privilege policy for boundary versioning and attachment only."
  policy      = data.aws_iam_policy_document.iam_change_executor.json

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_iam_role_policy_attachment" "iam_change_executor" {
  role       = aws_iam_role.iam_change.name
  policy_arn = aws_iam_policy.iam_change_executor.arn
}

data "aws_iam_policy_document" "security_owner_assume_iam_change" {
  statement {
    sid       = "AssumeProtectedIamChangeExecutor"
    actions   = ["sts:AssumeRole"]
    resources = [aws_iam_role.iam_change.arn]
  }
}

resource "aws_iam_policy" "security_owner_assume_iam_change" {
  name        = "${var.name_prefix}-security-owner-assume-iam-change"
  description = "Mandate 12 minimal policy allowing approved security owners to assume the IAM change executor."
  policy      = data.aws_iam_policy_document.security_owner_assume_iam_change.json

  lifecycle {
    prevent_destroy = true
  }
}
