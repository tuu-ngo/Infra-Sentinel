# Output cho gitops/runbook dùng. Endpoint không nhạy cảm; credential KHÔNG output ra
# (đọc qua ESO/Secrets Manager). Mọi output an toàn khi count=0 (try trả null).

# ---------- RDS ----------
output "rds_endpoint_address" {
  description = "Host RDS PostgreSQL (không nhạy cảm) — gitops render conn string 3 format."
  value       = try(aws_db_instance.postgres[0].address, null)
}

output "rds_port" {
  value = try(aws_db_instance.postgres[0].port, null)
}

output "rds_instance_arn" {
  description = "ARN RDS PostgreSQL production instance, used by Mandate #20 AWS Backup selection."
  value       = try(aws_db_instance.postgres[0].arn, null)
}

output "rds_database_name" {
  value = try(aws_db_instance.postgres[0].db_name, null)
}

output "rds_master_user_secret_arn" {
  description = "ARN secret master do RDS tự quản (username/password) — ESO đọc từ đây."
  value       = try(aws_db_instance.postgres[0].master_user_secret[0].secret_arn, null)
}

# ---------- ElastiCache ----------
output "elasticache_primary_endpoint" {
  value = try(aws_elasticache_replication_group.valkey[0].primary_endpoint_address, null)
}

output "elasticache_reader_endpoint" {
  value = try(aws_elasticache_replication_group.valkey[0].reader_endpoint_address, null)
}

output "elasticache_auth_secret_arn" {
  value = try(aws_secretsmanager_secret.elasticache_auth[0].arn, null)
}

# ---------- MSK ----------
output "msk_cluster_arn" {
  value = try(aws_msk_cluster.kafka[0].arn, null)
}

output "msk_bootstrap_brokers_sasl_scram" {
  description = "Bootstrap SASL/SCRAM (cổng 9096) — dùng cho client checkout/accounting/fraud-detection."
  value       = try(aws_msk_cluster.kafka[0].bootstrap_brokers_sasl_scram, null)
}

output "msk_scram_secret_arn" {
  value = try(aws_secretsmanager_secret.msk_scram[0].arn, null)
}

# ---------- Chung ----------
output "datastores_kms_key_arn" {
  value = try(aws_kms_key.datastores[0].arn, null)
}
