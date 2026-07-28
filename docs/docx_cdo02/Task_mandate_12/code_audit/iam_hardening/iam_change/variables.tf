variable "region" {
  description = "AWS region of the existing TF3 production foundation."
  type        = string
  default     = "ap-southeast-1"

  validation {
    condition     = var.region == "ap-southeast-1"
    error_message = "Mandate 12 IAM change executor is approved only for ap-southeast-1."
  }
}

variable "name_prefix" {
  description = "Prefix for the protected IAM change role and policies."
  type        = string
  default     = "tf3-m12"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,40}$", var.name_prefix))
    error_message = "name_prefix must contain only lowercase letters, numbers and hyphens."
  }
}

variable "operator_boundary_policy_arn" {
  description = "ARN of the already rendered and reviewed operator permissions-boundary managed policy."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:iam::197826770971:policy/.+$", var.operator_boundary_policy_arn))
    error_message = "operator_boundary_policy_arn must be a managed-policy ARN in account 197826770971."
  }
}

variable "target_user_arns" {
  description = "Explicit daily-operator IAM user ARNs eligible to receive this exact boundary."
  type        = set(string)
  default     = []

  validation {
    condition     = alltrue([for arn in var.target_user_arns : can(regex("^arn:aws:iam::197826770971:user/.+$", arn))])
    error_message = "target_user_arns must contain only IAM user ARNs from account 197826770971."
  }
}

variable "target_role_arns" {
  description = "Explicit daily-operator IAM role ARNs eligible to receive this exact boundary."
  type        = set(string)
  default     = []

  validation {
    condition     = alltrue([for arn in var.target_role_arns : can(regex("^arn:aws:iam::197826770971:role/.+$", arn))])
    error_message = "target_role_arns must contain only IAM role ARNs from account 197826770971."
  }
}

variable "trusted_change_owner_arns" {
  description = "Named MFA-capable security-owner IAM users/roles allowed to assume the executor; root is deliberately excluded."
  type        = set(string)

  validation {
    condition     = length(var.trusted_change_owner_arns) > 0 && alltrue([for arn in var.trusted_change_owner_arns : can(regex("^arn:aws:iam::197826770971:(user|role)/.+$", arn))])
    error_message = "trusted_change_owner_arns must contain at least one named IAM user or role ARN in account 197826770971, never root."
  }
}

variable "allow_boundary_removal" {
  description = "Emergency rollback only. False by default; set true only in a separately approved, time-boxed change."
  type        = bool
  default     = false
}
