module "network" {
  source = "../../modules/network"

  region               = var.region
  cluster_name         = var.cluster_name
  vpc_cidr             = var.vpc_cidr
  azs                  = var.azs
  private_subnet_cidrs = var.private_subnet_cidrs
  public_subnet_cidrs  = var.public_subnet_cidrs
}

module "eks_platform" {
  source = "../../modules/eks-platform"

  cluster_name                = var.cluster_name
  cluster_version             = var.cluster_version
  vpc_id                      = module.network.vpc_id
  private_subnet_ids          = module.network.private_subnet_ids
  node_instance_type          = var.node_instance_type
  node_desired_size           = var.node_desired_size
  node_min_size               = var.node_min_size
  node_max_size               = var.node_max_size
  enable_stateful_node_group  = var.enable_stateful_node_group
  stateful_node_subnet_id     = module.network.private_subnet_ids[index(var.azs, var.stateful_node_availability_zone)]
  stateful_node_instance_type = var.stateful_node_instance_type
  stateful_node_desired_size  = var.stateful_node_desired_size
  stateful_node_min_size      = var.stateful_node_min_size
  stateful_node_max_size      = var.stateful_node_max_size
  eks_admin_principal_arns    = var.eks_admin_principal_arns
  eks_kubernetes_group_principals = {
    operator = {
      principal_arn     = aws_iam_role.tf3_production_operator.arn
      kubernetes_groups = ["tf3-production-operators"]
    }
    readonly = {
      principal_arn     = aws_iam_role.tf3_production_readonly.arn
      kubernetes_groups = ["tf3-production-readers"]
    }
  }
}

module "access" {
  source = "../../modules/access"

  region                    = var.region
  cluster_name              = var.cluster_name
  vpc_id                    = module.network.vpc_id
  vpc_cidr                  = var.vpc_cidr
  private_subnet_ids        = module.network.private_subnet_ids
  cluster_security_group_id = module.eks_platform.cluster_security_group_id
  cluster_endpoint          = module.eks_platform.cluster_endpoint
}

module "datastores" {
  source = "../../modules/datastores"

  enabled      = var.enable_managed_datastores
  cluster_name = var.cluster_name
  name_prefix  = var.datastores_name_prefix

  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids

  # Pod EKS đi ra qua NODE security group (VPC CNI gắn SG này lên ENI của node/pod) — đây mới là
  # SG traffic pod thực sự dùng. Cluster SG (aws_security_group.cluster) KHÔNG nằm trên node ENI nên
  # allow mình nó thì pod timeout khi nối datastore. Giữ cả 2 cho đủ (cluster SG dùng cho control-plane).
  allowed_client_security_group_ids = [
    module.eks_platform.node_security_group_id,
    module.eks_platform.cluster_security_group_id,
  ]
  bastion_security_group_id  = module.access.bastion_security_group_id
  external_secrets_role_name = module.eks_platform.external_secrets_role_name

  # Thông số right-size + Multi-AZ mặc định trong module (ADR 0009). Override qua tfvars nếu cần.
}

module "edge" {
  source = "../../modules/edge"

  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  cluster_name                = var.cluster_name
  frontend_alb_dns_name       = var.frontend_alb_dns_name
  vpc_id                      = module.network.vpc_id
  private_alb_name            = var.private_alb_name
  edge_phase                  = var.edge_phase
  cloudfront_staging_selector = var.cloudfront_staging_selector
}

resource "aws_security_group_rule" "bad_ssh" {
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.frontend.id # Hoặc bất kỳ biến SG ID nào có sẵn
}
