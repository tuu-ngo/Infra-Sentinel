output "audit_admin_role_arn" {
  description = "Insert this ARN into the deny list of the allowlisted operator boundary template."
  value       = aws_iam_role.audit_admin.arn
}

output "breakglass_role_arn" {
  description = "Insert this ARN into the deny list of the allowlisted operator boundary template."
  value       = aws_iam_role.breakglass.arn
}

output "audit_read_policy_arn" {
  description = "Managed policy attached only to the audit-admin role."
  value       = aws_iam_policy.audit_read.arn
}

output "breakglass_recovery_policy_arn" {
  description = "Managed policy attached only to the break-glass role."
  value       = aws_iam_policy.breakglass_recovery.arn
}

output "security_owner_assume_audit_policy_arn" {
  description = "Attach this minimal policy only to the explicit trusted security-owner identities in a separately reviewed IAM change."
  value       = aws_iam_policy.security_owner_assume_audit.arn
}
