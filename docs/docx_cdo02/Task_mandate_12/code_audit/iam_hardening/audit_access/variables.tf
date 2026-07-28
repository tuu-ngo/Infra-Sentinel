variable "name_prefix" {
  description = "Prefix for the two protected audit-access roles and policies."
  type        = string
  default     = "tf3-m12"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,40}$", var.name_prefix))
    error_message = "name_prefix must contain only lowercase letters, numbers and hyphens."
  }
}

variable "region" {
  description = "AWS region of the existing TF3 production foundation."
  type        = string
  default     = "ap-southeast-1"

  validation {
    condition     = var.region == "ap-southeast-1"
    error_message = "Mandate 12 audit access is approved only for ap-southeast-1."
  }
}

variable "audit_bucket_arn" {
  description = "ARN of the Object-Lock audit archive bucket created by the foundation."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:s3:::[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.audit_bucket_arn))
    error_message = "audit_bucket_arn must be a valid S3 bucket ARN."
  }
}

variable "audit_trail_arn" {
  description = "ARN of the protected CloudTrail trail created by the foundation."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:cloudtrail:[a-z0-9-]+:[0-9]{12}:trail/.+$", var.audit_trail_arn))
    error_message = "audit_trail_arn must be a valid CloudTrail trail ARN."
  }
}

variable "alert_topic_arns" {
  description = "All protected SNS alert-topic ARNs created by the foundation; the current foundation emits primary and global topics."
  type        = set(string)

  validation {
    condition     = length(var.alert_topic_arns) == 2 && alltrue([for arn in var.alert_topic_arns : can(regex("^arn:aws:sns:[a-z0-9-]+:[0-9]{12}:.+$", arn))])
    error_message = "alert_topic_arns must contain exactly the two valid SNS topic ARNs emitted by the current foundation."
  }
}

variable "audit_rule_arns" {
  description = "All EventBridge anti-tamper rule ARNs emitted by the foundation; the current foundation emits twelve rules."
  type        = set(string)

  validation {
    condition     = length(var.audit_rule_arns) == 12 && alltrue([for arn in var.audit_rule_arns : can(regex("^arn:aws:events:[a-z0-9-]+:[0-9]{12}:rule/.+$", arn))])
    error_message = "audit_rule_arns must contain exactly the twelve valid EventBridge rule ARNs emitted by the current foundation."
  }
}

variable "trusted_principal_arns" {
  description = "Named, MFA-capable IAM users or roles of approved security owners; root is deliberately not accepted."
  type        = set(string)

  validation {
    condition     = length(var.trusted_principal_arns) > 0 && alltrue([for arn in var.trusted_principal_arns : can(regex("^arn:aws:iam::[0-9]{12}:(user|role)/.+$", arn))])
    error_message = "trusted_principal_arns must contain at least one IAM user or role ARN, never an account root ARN."
  }
}

variable "require_mfa" {
  description = "Require AWS MFA context when a trusted principal assumes either protected audit role."
  type        = bool
  default     = true
}
