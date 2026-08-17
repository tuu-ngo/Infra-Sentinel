import re
from pathlib import Path

import yaml


ENDPOINTS = Path("infra/live/production/ai-runtime-vpc-endpoints.tf").read_text(
    encoding="utf-8"
)
OUTPUTS = Path("infra/live/production/outputs.tf").read_text(encoding="utf-8")
IRSA = Path(
    "infra/modules/eks-platform/product-reviews-bedrock.tf"
).read_text(encoding="utf-8")
RUNTIME_VALUES = yaml.safe_load(
    Path("phase3 - information/deploy/values-aio-llm.yaml").read_text(
        encoding="utf-8"
    )
)
PRODUCTION_VALUES = yaml.safe_load(
    Path("phase3 - information/deploy/values-prod.yaml").read_text(
        encoding="utf-8"
    )
)
EXTERNAL_SECRETS = list(
    yaml.safe_load_all(
        Path("gitops/secrets/product-reviews-ai-endpoints.yaml").read_text(
            encoding="utf-8"
        )
    )
)

EXPECTED_PROFILE_IDS = {
    "apac.amazon.nova-lite-v1:0",
    "apac.amazon.nova-micro-v1:0",
}
EXPECTED_DESTINATION_REGIONS = {
    "ap-northeast-1",
    "ap-northeast-2",
    "ap-northeast-3",
    "ap-south-1",
    "ap-southeast-1",
    "ap-southeast-2",
}
EXPECTED_STS_IPS = {"10.0.15.250", "10.0.31.250", "10.0.47.250"}
EXPECTED_BEDROCK_IPS = {"10.0.15.251", "10.0.31.251", "10.0.47.251"}


def hcl_block(document: str, header: str) -> str:
    start = document.index(header)
    opening_brace = document.index("{", start)
    depth = 0

    for index in range(opening_brace, len(document)):
        if document[index] == "{":
            depth += 1
        elif document[index] == "}":
            depth -= 1
            if depth == 0:
                return document[start : index + 1]

    raise AssertionError(f"Unclosed HCL block: {header}")


def assigned_list(document: str, name: str) -> set[str]:
    match = re.search(rf"{re.escape(name)}\s*=\s*\[(.*?)\]", document, re.DOTALL)
    assert match, f"Missing list assignment: {name}"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def assert_assignment(document: str, name: str, value: str) -> None:
    assert re.search(
        rf"^\s*{re.escape(name)}\s*=\s*{re.escape(value)}\s*$",
        document,
        re.MULTILINE,
    ), f"Missing assignment: {name} = {value}"


def test_private_endpoints_are_ha_without_hijacking_shared_dns():
    expected_services = {
        "product_reviews_sts": "com.amazonaws.${var.region}.sts",
        "product_reviews_bedrock_runtime": (
            "com.amazonaws.${var.region}.bedrock-runtime"
        ),
    }

    for resource_name, service_name in expected_services.items():
        block = hcl_block(
            ENDPOINTS, f'resource "aws_vpc_endpoint" "{resource_name}"'
        )
        assert_assignment(block, "service_name", f'"{service_name}"')
        assert_assignment(block, "vpc_endpoint_type", '"Interface"')
        assert_assignment(block, "ip_address_type", '"ipv4"')
        assert_assignment(block, "private_dns_enabled", "false")
        assert_assignment(
            block,
            "security_group_ids",
            "[aws_security_group.product_reviews_ai_endpoints.id]",
        )
        assert 'dynamic "subnet_configuration"' in block
        assert "endpoint_subnet.subnet_id" in block
        assert "var.private_subnet_cidrs[index(var.azs, az)]" in block


def test_endpoint_enis_use_exact_audited_private_ips():
    for ip in EXPECTED_STS_IPS | EXPECTED_BEDROCK_IPS:
        assert f'"{ip}"' in ENDPOINTS

    sts = hcl_block(
        ENDPOINTS, 'resource "aws_vpc_endpoint" "product_reviews_sts"'
    )
    bedrock = hcl_block(
        ENDPOINTS,
        'resource "aws_vpc_endpoint" "product_reviews_bedrock_runtime"',
    )
    assert "subnet_id = subnet_configuration.value.subnet_id" in sts
    assert "ipv4      = subnet_configuration.value.sts_ipv4" in sts
    assert "subnet_id = subnet_configuration.value.subnet_id" in bedrock
    assert "ipv4      = subnet_configuration.value.bedrock_ipv4" in bedrock


def test_endpoint_security_group_only_accepts_eks_node_https():
    security_group = hcl_block(
        ENDPOINTS,
        'resource "aws_security_group" "product_reviews_ai_endpoints"',
    )
    ingress = hcl_block(
        ENDPOINTS,
        'resource "aws_vpc_security_group_ingress_rule" '
        '"product_reviews_ai_endpoints_https"',
    )

    assert "egress = []" in security_group
    assert_assignment(
        ingress,
        "referenced_security_group_id",
        "module.eks_platform.node_security_group_id",
    )
    assert_assignment(ingress, "ip_protocol", '"tcp"')
    assert_assignment(ingress, "from_port", "443")
    assert_assignment(ingress, "to_port", "443")
    assert "var.vpc_cidr" not in ingress
    assert "cidr_ipv4" not in ingress


def test_sts_endpoint_is_limited_to_product_reviews_irsa():
    policy = hcl_block(
        ENDPOINTS,
        'data "aws_iam_policy_document" "product_reviews_sts_endpoint"',
    )

    assert 'actions = ["sts:AssumeRoleWithWebIdentity"]' in policy
    assert (
        "resources = [module.eks_platform.product_reviews_bedrock_role_arn]"
        in policy
    )
    assert 'type        = "*"' in policy
    assert 'identifiers = ["*"]' in policy
    assert '"sts:AssumeRole"' not in policy


def test_bedrock_endpoint_is_limited_to_profiles_and_product_reviews_role():
    policy = hcl_block(
        ENDPOINTS,
        'data "aws_iam_policy_document" '
        '"product_reviews_bedrock_runtime_endpoint"',
    )

    assert policy.count(
        "identifiers = [module.eks_platform.product_reviews_bedrock_role_arn]"
    ) == 2
    assert policy.count('"bedrock:InvokeModel"') == 2
    assert policy.count('"bedrock:InvokeModelWithResponseStream"') == 2
    assert "resources = local.product_reviews_ai_inference_profile_arns" in policy
    assert "resources = local.product_reviews_ai_foundation_model_arns" in policy
    assert 'variable = "bedrock:InferenceProfileArn"' in policy
    assert '"bedrock:*"' not in policy
    assert 'resources = ["*"]' not in policy


def test_apac_profiles_include_every_verified_destination_region():
    assert (
        assigned_list(ENDPOINTS, "product_reviews_ai_inference_profile_ids")
        == EXPECTED_PROFILE_IDS
    )
    assert (
        assigned_list(ENDPOINTS, "product_reviews_ai_destination_regions")
        == EXPECTED_DESTINATION_REGIONS
    )
    assert (
        assigned_list(IRSA, "bedrock_inference_profile_ids")
        == EXPECTED_PROFILE_IDS
    )
    assert (
        assigned_list(IRSA, "bedrock_inference_destination_regions")
        == EXPECTED_DESTINATION_REGIONS
    )


def test_irsa_requires_inference_profile_for_apac_foundation_models():
    assert_assignment(IRSA, "bedrock_inference_region", '"ap-southeast-1"')
    assert 'Sid    = "InvokeProductReviewsInferenceProfiles"' in IRSA
    assert 'Sid    = "InvokeProductReviewsModelsViaProfiles"' in IRSA
    assert (
        '"bedrock:InferenceProfileArn" = local.bedrock_inference_profile_arns'
        in IRSA
    )
    assert '"arn:aws:bedrock:*::foundation-model/' not in IRSA
    assert '"bedrock:*"' not in IRSA


def test_legacy_model_route_remains_only_for_runtime_migration():
    assert 'Sid    = "InvokeLegacyUsEast1ModelsDuringMigration"' in IRSA
    assert_assignment(IRSA, "bedrock_legacy_region", '"us-east-1"')
    assert "rollback path working while the APAC" in IRSA


def test_endpoint_urls_are_published_through_least_privilege_ssm_handoff():
    for resource_name in (
        "product_reviews_sts_endpoint_url",
        "product_reviews_bedrock_runtime_endpoint_url",
    ):
        parameter = hcl_block(
            ENDPOINTS, f'resource "aws_ssm_parameter" "{resource_name}"'
        )
        assert_assignment(parameter, "type", '"SecureString"')
        assert_assignment(parameter, "key_id", "module.eks_platform.eks_kms_key_arn")

    policy = hcl_block(
        ENDPOINTS,
        'data "aws_iam_policy_document" '
        '"external_secrets_product_reviews_ai_endpoints"',
    )
    assert '"ssm:GetParameter"' in policy
    assert '"ssm:GetParameters"' in policy
    assert '"ssm:GetParametersByPath"' not in policy
    assert 'actions   = ["kms:Decrypt"]' in policy
    assert 'variable = "kms:ViaService"' in policy
    assert 'variable = "kms:EncryptionContext:PARAMETER_ARN"' in policy
    assert 'resources = ["*"]' not in policy


def test_external_secret_reads_only_the_two_endpoint_parameters():
    store = next(document for document in EXTERNAL_SECRETS if document["kind"] == "ClusterSecretStore")
    external_secret = next(
        document for document in EXTERNAL_SECRETS if document["kind"] == "ExternalSecret"
    )

    assert store["metadata"]["name"] == "aws-parameter-store"
    assert store["spec"]["provider"]["aws"]["service"] == "ParameterStore"
    assert external_secret["spec"]["target"]["name"] == "product-reviews-ai-endpoints"
    assert {
        item["remoteRef"]["key"] for item in external_secret["spec"]["data"]
    } == {
        "/techx-corp-tf3/product-reviews/ai-endpoints/sts-url",
        "/techx-corp-tf3/product-reviews/ai-endpoints/bedrock-runtime-url",
    }


def test_runtime_uses_apac_profiles_and_private_service_endpoints():
    overrides = {
        item["name"]: item
        for item in RUNTIME_VALUES["components"]["product-reviews"]["envOverrides"]
    }

    assert overrides["AWS_REGION"]["value"] == "ap-southeast-1"
    assert overrides["LLM_MODEL"]["value"] == "apac.amazon.nova-lite-v1:0"
    assert overrides["JUDGE_REGION"]["value"] == "ap-southeast-1"
    assert overrides["JUDGE_MODEL"]["value"] == "apac.amazon.nova-micro-v1:0"
    assert overrides["AWS_ENDPOINT_URL_STS"]["valueFrom"]["secretKeyRef"] == {
        "name": "product-reviews-ai-endpoints",
        "key": "sts_url",
    }
    assert overrides["AWS_ENDPOINT_URL_BEDROCK_RUNTIME"]["valueFrom"][
        "secretKeyRef"
    ] == {
        "name": "product-reviews-ai-endpoints",
        "key": "bedrock_runtime_url",
    }


def test_rollout_keeps_old_product_reviews_pods_available_during_handoff():
    product_reviews = PRODUCTION_VALUES["components"]["product-reviews"]
    rolling_update = product_reviews["strategy"]["rollingUpdate"]

    assert product_reviews["strategy"]["type"] == "RollingUpdate"
    assert rolling_update["maxUnavailable"] == 0
    assert rolling_update["maxSurge"] >= 1


def test_endpoint_outputs_support_runtime_and_network_policy_evidence():
    for output_name in (
        "product_reviews_sts_vpc_endpoint_id",
        "product_reviews_sts_vpc_endpoint_network_interface_ids",
        "product_reviews_sts_vpc_endpoint_dns_entries",
        "product_reviews_sts_vpc_endpoint_private_ips",
        "product_reviews_sts_endpoint_url_parameter_name",
        "product_reviews_bedrock_runtime_vpc_endpoint_id",
        "product_reviews_bedrock_runtime_vpc_endpoint_network_interface_ids",
        "product_reviews_bedrock_runtime_vpc_endpoint_dns_entries",
        "product_reviews_bedrock_runtime_vpc_endpoint_private_ips",
        "product_reviews_bedrock_runtime_endpoint_url_parameter_name",
    ):
        assert f'output "{output_name}"' in OUTPUTS
