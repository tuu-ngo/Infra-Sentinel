output "iam_change_role_arn" {
  description = "MFA-protected role used only for reviewed boundary version/attachment changes."
  value       = aws_iam_role.iam_change.arn
}

output "iam_change_executor_policy_arn" {
  description = "Least-privilege policy attached only to the IAM change role."
  value       = aws_iam_policy.iam_change_executor.arn
}

output "security_owner_assume_iam_change_policy_arn" {
  description = "Attach manually and only to the named trusted change owners in a separately reviewed IAM change."
  value       = aws_iam_policy.security_owner_assume_iam_change.arn
}
