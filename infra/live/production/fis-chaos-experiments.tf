# AWS Fault Injection Service (FIS) — controlled failure injection for Mandate 17 req#2.
#
# WHY FIS AND NOT `kubectl cordon/drain`:
# Directive #17 explicitly separates itself from Directive #3 — "#3 is PLANNED
# maintenance; this one is an UNEXPECTED death". `cordon`+`drain` is the planned path:
# pods are evicted politely, PDBs are honoured, preStop hooks run. It proves Directive
# #3, not #17. FIS `aws:network:disrupt-connectivity` cuts traffic in and out of an AZ
# the way a real AZ event does, so it is the faithful test for req#2.
#
# SAFETY MODEL (do not weaken any of these):
#   1. Trust policy is scoped to this account AND to FIS experiment ARNs
#      (confused-deputy protection).
#   2. Every template MUST carry a stop_condition. FIS aborts the experiment and rolls
#      the fault back automatically when the alarm fires.
#   3. Durations stay short (PT5M). An operator must be on the call with
#      `aws fis stop-experiment` ready.
#   4. Default target AZ is 1b, NOT 1a — see the note on var.fis_target_az.

variable "fis_target_az" {
  description = <<-EOT
    Availability Zone that the AZ-loss experiment disrupts.

    Defaults to ap-southeast-1b on purpose. The VPC currently has a SINGLE NAT Gateway,
    and it lives in the 1a public subnet, while all three private subnets share one route
    table pointing at it. Disrupting 1a therefore kills outbound internet for the WHOLE
    cluster: the cloudflared tunnel drops (public storefront becomes unreachable) and ECR
    pulls fail (no pod can start anywhere, so the cluster cannot self-heal). 1b carries
    revenue-path replicas too, so it is still a meaningful req#2 test, but it does not
    take the egress path down with it.

    Only point this at 1a as a deliberate, announced demonstration of that finding.
  EOT
  type        = string
  default     = "ap-southeast-1b"
}

locals {
  fis_private_subnet_name = "techx-corp-tf3-vpc-private-${var.fis_target_az}"
}

# The VPC is looked up by tag rather than read from module.network.vpc_id ON PURPOSE.
# terraform-apply runs scoped applies with -target, and -target pulls in the target's
# dependencies: taking the module output would drag all of module.network into an
# FIS-scoped apply, which is exactly the unrelated pending drift the scope mechanism
# exists to avoid. A tag lookup keeps this file self-contained.
data "aws_vpc" "fis_target" {
  filter {
    name   = "tag:Name"
    values = ["${var.cluster_name}-vpc"]
  }
}

# Scoped by vpc-id as well as the Name tag: aws_subnet errors out unless the filters match
# exactly one subnet, and the VPC bound keeps that true even if another VPC in this account
# ever reuses the naming convention.
data "aws_subnet" "fis_target" {
  vpc_id = data.aws_vpc.fis_target.id

  filter {
    name   = "tag:Name"
    values = [local.fis_private_subnet_name]
  }

  # Cái tên trên tag KHÔNG phải là bằng chứng subnet nằm ở AZ nào — tag do người đặt,
  # AZ do AWS quyết. Khớp lại hai thứ ngay ở bước plan để một subnet bị đặt tên sai
  # không thể lặng lẽ trở thành mục tiêu của bài chaos.
  lifecycle {
    postcondition {
      condition     = self.availability_zone == var.fis_target_az
      error_message = "Subnet ${self.id} tên '${local.fis_private_subnet_name}' nhưng thực tế nằm ở AZ ${self.availability_zone}, không phải ${var.fis_target_az}."
    }
  }
}

data "aws_lb" "fis_stop_condition_source" {
  name = var.private_alb_name
}

# ---------------------------------------------------------------------------
# IAM role assumed by the FIS service while an experiment runs
# ---------------------------------------------------------------------------

resource "aws_iam_role" "fis_experiment" {
  name        = "tf3-fis-experiment"
  description = "Assumed by AWS FIS to run Mandate 17 resilience experiments."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "fis.amazonaws.com" }
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.production_access.account_id
        }
        ArnLike = {
          "aws:SourceArn" = "arn:aws:fis:${var.region}:${data.aws_caller_identity.production_access.account_id}:experiment/*"
        }
      }
    }]
  })
}

# Network access covers aws:network:disrupt-connectivity. FIS implements the fault by
# swapping the subnet's network ACL for a deny-all one and restoring it afterwards.
resource "aws_iam_role_policy_attachment" "fis_network" {
  role       = aws_iam_role.fis_experiment.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSFaultInjectionSimulatorNetworkAccess"
}

# EC2 access covers aws:ec2:send-spot-instance-interruptions — the REAL spot reclaim
# (with the 2-minute warning). Attached now because Mandate 13 req#3 asks for exactly
# that and the current evidence uses cordon/drain instead. No template here yet; add one
# in a separate PR owned by whoever presents Mandate 13.
resource "aws_iam_role_policy_attachment" "fis_ec2" {
  role       = aws_iam_role.fis_experiment.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSFaultInjectionSimulatorEC2Access"
}

# NOT attached: AWSFaultInjectionSimulatorEKSAccess.
# The aws:eks:pod-* actions additionally need an in-cluster ServiceAccount plus RBAC that
# FIS impersonates. Granting the AWS-side policy without that wiring buys nothing and
# widens the role, so it stays out until someone actually builds the pod-level experiment.

# No CloudWatch permissions are attached on purpose. The experiment role only needs to
# reach the resources an action mutates; stop conditions are evaluated by the FIS service
# itself, not through this role (AWS "IAM roles for AWS FIS experiments" lists no
# CloudWatch permission). Granting cloudwatch:DescribeAlarms would also force a
# Resource = "*" wildcard, because that API does not support resource-level permissions —
# a needless tfsec AVD-AWS-0057 exception for a permission nothing uses.

# ---------------------------------------------------------------------------
# Stop condition — abort the experiment if customers start seeing errors
# ---------------------------------------------------------------------------
#
# The SLO metrics themselves live in Prometheus, which FIS cannot read. The private
# frontend ALB does publish to CloudWatch, and a 5xx burst there is the earliest
# CloudWatch-visible signal that the storefront is failing, so it is what guards the run.
# Deliberately sensitive: one evaluation period of 60s, threshold 5. A false abort costs
# nothing; a missed abort costs customer traffic.

resource "aws_cloudwatch_metric_alarm" "fis_storefront_5xx" {
  alarm_name          = "tf3-fis-stop-storefront-5xx"
  alarm_description   = "FIS stop condition: aborts a running resilience experiment when the frontend ALB starts returning 5xx."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = data.aws_lb.fis_stop_condition_source.arn_suffix
  }
}

# ---------------------------------------------------------------------------
# Experiment template — Mandate 17 req#2: lose one Availability Zone
# ---------------------------------------------------------------------------
#
# Creating the template does NOT run anything. Start it explicitly with:
#   aws fis start-experiment --experiment-template-id <id> --region ap-southeast-1
# and stop early with:
#   aws fis stop-experiment --id <experiment-id> --region ap-southeast-1

resource "aws_fis_experiment_template" "az_connectivity_loss" {
  description = "Mandate 17 req#2 — disrupt connectivity for one AZ and prove the revenue path keeps serving."
  role_arn    = aws_iam_role.fis_experiment.arn

  stop_condition {
    source = "aws:cloudwatch:alarm"
    value  = aws_cloudwatch_metric_alarm.fis_storefront_5xx.arn
  }

  target {
    name           = "target-az-subnet"
    resource_type  = "aws:ec2:subnet"
    selection_mode = "ALL"
    resource_arns = [
      "arn:aws:ec2:${var.region}:${data.aws_caller_identity.production_access.account_id}:subnet/${data.aws_subnet.fis_target.id}"
    ]
  }

  action {
    name        = "disrupt-az-connectivity"
    description = "Blackhole traffic in and out of the target AZ subnet."
    action_id   = "aws:network:disrupt-connectivity"

    target {
      key   = "Subnets"
      value = "target-az-subnet"
    }

    parameter {
      key   = "scope"
      value = "availability-zone"
    }

    # Long enough for Karpenter/kubelet to react and for Grafana to show a clean
    # before/during/after, short enough to bound the blast radius.
    parameter {
      key   = "duration"
      value = "PT5M"
    }
  }

  tags = {
    Name    = "tf3-m17-az-connectivity-loss"
    mandate = "mandate-17"
  }
}

output "fis_az_experiment_template_id" {
  description = "Experiment template id for the Mandate 17 req#2 AZ-loss drill."
  value       = aws_fis_experiment_template.az_connectivity_loss.id
}
