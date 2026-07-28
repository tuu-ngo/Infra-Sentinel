provider "aws" {
  region              = var.region
  allowed_account_ids = ["197826770971"]

  default_tags {
    tags = {
      Project     = "TF3"
      Mandate     = "12"
      Environment = "production"
      ManagedBy   = "Terraform"
    }
  }
}
