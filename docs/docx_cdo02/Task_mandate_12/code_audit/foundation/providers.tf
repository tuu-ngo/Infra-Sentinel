provider "aws" {
  region              = var.region
  allowed_account_ids = ["197826770971"]

  default_tags {
    tags = {
      project     = "techx-corp-phase3"
      team        = "TF3"
      mandate     = "12"
      managed-by  = "terraform"
      component   = "audit-foundation"
      environment = "production"
    }
  }
}

# IAM, STS, and CloudFront global-service events are recorded in us-east-1.
# This alias owns only the EventBridge/SNS controls that alert on IAM tampering.
provider "aws" {
  alias               = "global_events"
  region              = var.global_event_region
  allowed_account_ids = ["197826770971"]

  default_tags {
    tags = {
      project     = "techx-corp-phase3"
      team        = "TF3"
      mandate     = "12"
      managed-by  = "terraform"
      component   = "audit-global-alerts"
      environment = "production"
    }
  }
}
