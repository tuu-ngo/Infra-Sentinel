# Mandate #20 - backup deletion protection for restore-proven RDS recovery path.
#
# AWS Backup supports RDS in this region, but not ElastiCache/MSK. This root
# therefore protects the RDS AWS Backup recovery points only; Valkey/MSK remain
# documented limitations in the Mandate #20 evidence.

locals {
  mandate20_backup_enabled = var.enable_mandate20_backup_vault_lock && var.enable_managed_datastores
}

resource "aws_backup_vault" "mandate20" {
  count = local.mandate20_backup_enabled ? 1 : 0

  name = "${var.datastores_name_prefix}-m20-vault"
}

resource "aws_backup_vault_lock_configuration" "mandate20_compliance" {
  count = local.mandate20_backup_enabled ? 1 : 0

  backup_vault_name   = aws_backup_vault.mandate20[0].name
  changeable_for_days = var.mandate20_backup_vault_changeable_for_days
  min_retention_days  = var.mandate20_backup_vault_min_retention_days
  max_retention_days  = var.mandate20_backup_vault_max_retention_days

  lifecycle {
    precondition {
      condition     = var.mandate20_backup_retention_days >= var.mandate20_backup_vault_min_retention_days && var.mandate20_backup_retention_days <= var.mandate20_backup_vault_max_retention_days
      error_message = "Mandate #20 backup retention must fit within the Vault Lock min/max retention window."
    }
  }
}

resource "aws_backup_plan" "mandate20_rds" {
  count = local.mandate20_backup_enabled ? 1 : 0

  name = "${var.datastores_name_prefix}-m20-rds-backup"

  rule {
    rule_name         = "daily-rds-backup"
    target_vault_name = aws_backup_vault.mandate20[0].name
    schedule          = "cron(0 18 * * ? *)"

    lifecycle {
      delete_after = var.mandate20_backup_retention_days
    }
  }
}

resource "aws_iam_role" "mandate20_aws_backup" {
  count = local.mandate20_backup_enabled ? 1 : 0

  name = "${var.datastores_name_prefix}-m20-aws-backup"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRole"
      Principal = {
        Service = "backup.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "mandate20_aws_backup_service" {
  count = local.mandate20_backup_enabled ? 1 : 0

  role       = aws_iam_role.mandate20_aws_backup[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_backup_selection" "mandate20_rds" {
  count = local.mandate20_backup_enabled ? 1 : 0

  name         = "${var.datastores_name_prefix}-m20-rds-selection"
  iam_role_arn = aws_iam_role.mandate20_aws_backup[0].arn
  plan_id      = aws_backup_plan.mandate20_rds[0].id
  resources    = [module.datastores.rds_instance_arn]

  depends_on = [aws_iam_role_policy_attachment.mandate20_aws_backup_service]
}
