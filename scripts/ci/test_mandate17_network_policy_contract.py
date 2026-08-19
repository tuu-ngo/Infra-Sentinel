import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


REPO = Path(__file__).resolve().parents[2]
INFRA = REPO / "gitops/infrastructure"
STAGED = INFRA / "network-policy-staged"
CONNECTIVITY_SCRIPT = REPO / "scripts/network-policy/mandate-17-connectivity-test.sh"
BASH = shutil.which("bash")

EXPECTED_FILES = {
    "00-otel-gateway.yaml",
    "01-grafana.yaml",
    "02-jaeger.yaml",
    "03-prometheus.yaml",
    "04-opensearch.yaml",
    "05-load-generator.yaml",
    "06-cloudflared.yaml",
    "07-aiops-engine.yaml",
    "10-quote.yaml",
    "11-currency.yaml",
    "12-payment.yaml",
    "13-email.yaml",
    "14-ad.yaml",
    "15-image-provider.yaml",
    "16-llm.yaml",
    "20-product-catalog.yaml",
    "21-cart.yaml",
    "22-accounting.yaml",
    "23-fraud-detection.yaml",
    "30-shipping.yaml",
    "31-recommendation.yaml",
    "32-product-reviews.yaml",
    "33-checkout.yaml",
    "34-frontend.yaml",
    "35-frontend-proxy.yaml",
    "40-flagd.yaml",
    "90-default-deny-all.yaml",
}

BUSINESS_COMPONENTS = {
    "10-quote.yaml": "quote",
    "11-currency.yaml": "currency",
    "12-payment.yaml": "payment",
    "13-email.yaml": "email",
    "14-ad.yaml": "ad",
    "15-image-provider.yaml": "image-provider",
    "16-llm.yaml": "llm",
    "20-product-catalog.yaml": "product-catalog",
    "21-cart.yaml": "cart",
    "22-accounting.yaml": "accounting",
    "23-fraud-detection.yaml": "fraud-detection",
    "30-shipping.yaml": "shipping",
    "31-recommendation.yaml": "recommendation",
    "32-product-reviews.yaml": "product-reviews",
    "33-checkout.yaml": "checkout",
    "34-frontend.yaml": "frontend",
    "35-frontend-proxy.yaml": "frontend-proxy",
    "40-flagd.yaml": "flagd",
}

EXPECTED_EGRESS_COMPONENTS = {
    "quote": {"otel-gateway"},
    "currency": {"otel-gateway"},
    "payment": {"flagd", "otel-gateway"},
    "email": {"flagd", "otel-gateway"},
    "ad": {"flagd", "otel-gateway"},
    "image-provider": {"otel-gateway"},
    "llm": {"flagd"},
    "product-catalog": {"flagd", "otel-gateway"},
    "cart": {"flagd", "otel-gateway"},
    "accounting": {"otel-gateway"},
    "fraud-detection": {"flagd", "otel-gateway"},
    "shipping": {"quote", "otel-gateway"},
    "recommendation": {"product-catalog", "flagd", "otel-gateway"},
    "product-reviews": {
        "product-catalog",
        "flagd",
        "otel-gateway",
        "product-reviews-egress-proxy",
    },
    "checkout": {
        "cart",
        "currency",
        "email",
        "payment",
        "product-catalog",
        "shipping",
        "flagd",
        "otel-gateway",
    },
    "frontend": {
        "ad",
        "cart",
        "checkout",
        "currency",
        "product-catalog",
        "product-reviews",
        "recommendation",
        "shipping",
        "flagd",
        "otel-gateway",
    },
    "frontend-proxy": {"frontend", "image-provider", "flagd", "otel-gateway"},
    "flagd": {"otel-gateway"},
}

# Public egress is permitted only on dedicated proxy workloads, never in staged
# business or platform policies.
PUBLIC_EGRESS_FILES = set()


def load_documents(path):
    return [
        document
        for document in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if document
    ]


def load_policy(filename):
    documents = load_documents(STAGED / filename)
    assert len(documents) == 1, f"{filename} must contain exactly one object"
    policy = documents[0]
    assert policy["kind"] == "NetworkPolicy"
    return policy


def load_active_policy(filename, name):
    for document in load_documents(INFRA / filename):
        if (
            document.get("kind") == "NetworkPolicy"
            and document.get("metadata", {}).get("name") == name
        ):
            return document
    raise AssertionError(f"{name} was not found in active {filename}")


def load_policy_from_file(path, name):
    for document in load_documents(path):
        if (
            document.get("kind") == "NetworkPolicy"
            and document.get("metadata", {}).get("name") == name
        ):
            return document
    raise AssertionError(f"{name} was not found in {path}")


def ingress_ports_from_source(policy, source):
    ports = set()
    for rule in policy["spec"].get("ingress", []):
        for peer in rule.get("from", []):
            labels = peer.get("podSelector", {}).get("matchLabels", {})
            if source in labels.values():
                ports.update(port["port"] for port in rule.get("ports", []))
    return ports


def egress_ports_for_pod_label(policy, key, value):
    ports = set()
    for rule in policy["spec"].get("egress", []):
        for peer in rule.get("to", []):
            labels = peer.get("podSelector", {}).get("matchLabels", {})
            if labels.get(key) == value:
                ports.update(port["port"] for port in rule.get("ports", []))
    return ports


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def contains_public_cidr(document):
    return any(
        item.get("ipBlock", {}).get("cidr") == "0.0.0.0/0"
        for item in walk(document)
    )


def selector_components(selector):
    components = set()
    labels = selector.get("matchLabels", {})
    component = labels.get("app.kubernetes.io/component")
    if component:
        components.add(component)
    for expression in selector.get("matchExpressions", []):
        if expression.get("key") == "app.kubernetes.io/component":
            components.update(expression.get("values", []))
    return components


def peer_components(peer):
    return selector_components(peer.get("podSelector", {}))


def egress_components(policy):
    components = set()
    for rule in policy["spec"].get("egress", []):
        for peer in rule.get("to", []):
            components.update(peer_components(peer))
    return components


def ports_for_egress_destination(policy, destination):
    ports = set()
    for rule in policy["spec"].get("egress", []):
        if any(destination in peer_components(peer) for peer in rule.get("to", [])):
            ports.update(port["port"] for port in rule.get("ports", []))
    return ports


def ipblocks_for_egress_port(policy, port):
    cidrs = set()
    for rule in policy["spec"].get("egress", []):
        if any(item["port"] == port for item in rule.get("ports", [])):
            cidrs.update(
                peer["ipBlock"]["cidr"]
                for peer in rule.get("to", [])
                if "ipBlock" in peer
            )
    return cidrs


def aiops_egress_proxy_authority_matchers():
    documents = load_documents(REPO / "gitops/aiops-engine/egress-proxy.yaml")
    config_map = next(
        document
        for document in documents
        if document["kind"] == "ConfigMap"
        and document["metadata"]["name"] == "aiops-egress-proxy-config"
    )
    envoy_config = yaml.safe_load(config_map["data"]["egress-proxy.yaml"])
    hcm_config = envoy_config["static_resources"]["listeners"][0]["filter_chains"][0][
        "filters"
    ][0]["typed_config"]
    rbac_filter = next(
        item
        for item in hcm_config["http_filters"]
        if item["name"] == "envoy.filters.http.rbac"
    )
    permissions = rbac_filter["typed_config"]["rules"]["policies"][
        "aiops_reviewed_external_https"
    ]["permissions"]

    matchers = []
    for permission in permissions:
        for rule in permission["and_rules"]["rules"]:
            header = rule.get("header")
            if header and header["name"] == ":authority":
                matchers.append(header["string_match"])
    return matchers


def test_grafana_policy_uses_post_dnat_pod_peers_and_private_api_subnets():
    active = load_active_policy(
        "network-policy-grafana.yaml", "grafana-network-policy"
    )
    staged = load_policy("01-grafana.yaml")
    api_subnets = {
        "172.20.0.1/32",
        "10.0.0.0/20",
        "10.0.16.0/20",
        "10.0.32.0/20",
    }

    assert ingress_ports_from_source(active, "cloudflared") == {3000}
    for policy in (active, staged):
        assert not contains_public_cidr(policy)
        assert policy["spec"]["podSelector"]["matchLabels"] == {
            "app.kubernetes.io/instance": "techx-corp",
            "app.kubernetes.io/name": "grafana",
        }
        assert egress_ports_for_pod_label(
            policy, "app.kubernetes.io/name", "prometheus"
        ) == {9090}
        assert egress_ports_for_pod_label(
            policy, "app.kubernetes.io/name", "jaeger"
        ) == {16685, 16686}
        assert egress_ports_for_pod_label(
            policy, "app.kubernetes.io/name", "opensearch"
        ) == {9200}
        for service_port in (53, 9090, 16685, 16686, 9200):
            assert ipblocks_for_egress_port(policy, service_port) == set()
        assert ipblocks_for_egress_port(policy, 443) == api_subnets
        assert policy["metadata"]["annotations"][
            "mandate-17.techx.io/cni-path-evidence"
        ] == (
            "2026-07-27:aws-vpc-cni-v1.22.4,standard,"
            "policyendpoint-pod-ip-resolution"
        )
        assert policy["metadata"]["annotations"][
            "mandate-17.techx.io/kubernetes-api-endpoint-evidence"
        ] == "2026-07-27:10.0.23.132,10.0.8.89"
        assert policy["metadata"]["annotations"][
            "mandate-17.techx.io/kubernetes-api-service-evidence"
        ] == "2026-07-27:kubernetes.default.svc=172.20.0.1"


def test_staged_inventory_is_one_policy_per_file():
    actual = {path.name for path in STAGED.glob("*.yaml")}
    assert actual == EXPECTED_FILES
    for filename in actual:
        policy = load_policy(filename)
        assert policy["metadata"]["namespace"] == "techx-tf3"


def test_all_business_components_are_selected_once():
    selected = {}
    for filename, expected_component in BUSINESS_COMPONENTS.items():
        policy = load_policy(filename)
        selector = policy["spec"]["podSelector"]
        assert selector_components(selector) == {expected_component}
        selected[filename] = expected_component
    assert set(selected.values()) == set(EXPECTED_EGRESS_COMPONENTS)


def test_business_egress_dependency_graph_is_exact():
    for filename, component in BUSINESS_COMPONENTS.items():
        policy = load_policy(filename)
        assert egress_components(policy) == EXPECTED_EGRESS_COMPONENTS[component]


def test_checkout_ports_and_indirect_quote_path_are_exact():
    checkout = load_policy("33-checkout.yaml")
    for destination in {
        "cart",
        "currency",
        "email",
        "payment",
        "product-catalog",
        "shipping",
    }:
        assert ports_for_egress_destination(checkout, destination) == {8080}
    assert ports_for_egress_destination(checkout, "flagd") == {8013}
    assert ports_for_egress_destination(checkout, "otel-gateway") == {4317}
    assert "quote" not in egress_components(checkout)


def test_accounting_has_observed_service_and_managed_datastore_peers():
    accounting = load_policy("22-accounting.yaml")
    assert ipblocks_for_egress_port(accounting, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(accounting, 4318) == {"172.20.117.175/32"}
    private_subnets = {"10.0.0.0/20", "10.0.16.0/20", "10.0.32.0/20"}
    assert ipblocks_for_egress_port(accounting, 5432) == private_subnets
    assert ipblocks_for_egress_port(accounting, 9096) == private_subnets
    assert accounting["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == "2026-07-25:kube-dns=172.20.0.10,otel-gateway=172.20.117.175"
def test_payment_has_observed_service_clusterip_peers():
    payment = load_policy("12-payment.yaml")
    assert ipblocks_for_egress_port(payment, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(payment, 8013) == {"172.20.213.30/32"}
    assert ipblocks_for_egress_port(payment, 4317) == {"172.20.117.175/32"}
    assert payment["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == (
        "2026-07-25:kube-dns=172.20.0.10,flagd=172.20.213.30,"
        "otel-gateway=172.20.117.175"
    )


def test_llm_has_observed_service_clusterip_peers():
    llm = load_policy("16-llm.yaml")
    assert ipblocks_for_egress_port(llm, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(llm, 8013) == {"172.20.213.30/32"}
    assert llm["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == "2026-07-25:kube-dns=172.20.0.10,flagd=172.20.213.30"


def test_fraud_detection_has_observed_service_and_msk_peers():
    fraud_detection = load_policy("23-fraud-detection.yaml")
    assert ipblocks_for_egress_port(fraud_detection, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(fraud_detection, 8013) == {"172.20.213.30/32"}
    assert ipblocks_for_egress_port(fraud_detection, 4318) == {"172.20.117.175/32"}
    assert ipblocks_for_egress_port(fraud_detection, 9096) == {
        "10.0.0.0/20",
        "10.0.16.0/20",
        "10.0.32.0/20",
    }
    assert fraud_detection["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == (
        "2026-07-25:kube-dns=172.20.0.10,flagd=172.20.213.30,"
        "otel-gateway=172.20.117.175"
    )


def test_image_provider_has_observed_service_clusterip_peers():
    image_provider = load_policy("15-image-provider.yaml")
    assert ipblocks_for_egress_port(image_provider, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(image_provider, 4317) == {"172.20.117.175/32"}
    assert image_provider["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == "2026-07-25:kube-dns=172.20.0.10,otel-gateway=172.20.117.175"


def test_email_has_observed_service_clusterip_peers():
    email = load_policy("13-email.yaml")
    assert ipblocks_for_egress_port(email, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(email, 8013) == {"172.20.213.30/32"}
    assert ipblocks_for_egress_port(email, 4318) == {"172.20.117.175/32"}
    assert email["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == (
        "2026-07-25:kube-dns=172.20.0.10,flagd=172.20.213.30,"
        "otel-gateway=172.20.117.175"
    )


def test_currency_has_observed_service_clusterip_peers():
    currency = load_policy("11-currency.yaml")
    assert ipblocks_for_egress_port(currency, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(currency, 4317) == {"172.20.117.175/32"}
    assert currency["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == "2026-07-25:kube-dns=172.20.0.10,otel-gateway=172.20.117.175"


def test_quote_has_observed_service_clusterip_peers():
    quote = load_policy("10-quote.yaml")
    assert ipblocks_for_egress_port(quote, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(quote, 4318) == {"172.20.117.175/32"}
    assert quote["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == "2026-07-25:kube-dns=172.20.0.10,otel-gateway=172.20.117.175"


def test_checkout_has_observed_service_and_msk_peers():
    checkout = load_policy("33-checkout.yaml")
    assert ipblocks_for_egress_port(checkout, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(checkout, 8080) == {
        "172.20.2.10/32",
        "172.20.58.251/32",
        "172.20.98.73/32",
        "172.20.105.214/32",
        "172.20.145.185/32",
        "172.20.165.232/32",
    }
    assert ipblocks_for_egress_port(checkout, 8013) == {"172.20.213.30/32"}
    assert ipblocks_for_egress_port(checkout, 4317) == {"172.20.117.175/32"}
    assert ipblocks_for_egress_port(checkout, 9096) == {
        "10.0.0.0/20",
        "10.0.16.0/20",
        "10.0.32.0/20",
    }
    assert checkout["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == (
        "2026-07-25:kube-dns=172.20.0.10,cart=172.20.165.232,"
        "currency=172.20.98.73,email=172.20.2.10,payment=172.20.105.214,"
        "product-catalog=172.20.145.185,shipping=172.20.58.251,"
        "flagd=172.20.213.30,otel-gateway=172.20.117.175"
    )


def test_frontend_has_observed_service_clusterip_peers():
    frontend = load_policy("34-frontend.yaml")
    assert ipblocks_for_egress_port(frontend, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(frontend, 8080) == {
        "172.20.21.19/32",
        "172.20.58.251/32",
        "172.20.65.25/32",
        "172.20.98.73/32",
        "172.20.109.11/32",
        "172.20.145.185/32",
        "172.20.165.232/32",
    }
    assert ipblocks_for_egress_port(frontend, 3551) == {"172.20.242.200/32"}
    assert ipblocks_for_egress_port(frontend, 8013) == {"172.20.213.30/32"}
    assert ipblocks_for_egress_port(frontend, 4317) == {"172.20.117.175/32"}
    assert frontend["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == (
        "2026-07-25:kube-dns=172.20.0.10,ad=172.20.65.25,"
        "cart=172.20.165.232,checkout=172.20.21.19,currency=172.20.98.73,"
        "product-catalog=172.20.145.185,recommendation=172.20.109.11,"
        "shipping=172.20.58.251,product-reviews=172.20.242.200,"
        "flagd=172.20.213.30,otel-gateway=172.20.117.175"
    )


def test_recommendation_has_observed_service_clusterip_peers():
    recommendation = load_policy("31-recommendation.yaml")
    assert ipblocks_for_egress_port(recommendation, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(recommendation, 8080) == {"172.20.145.185/32"}
    assert ipblocks_for_egress_port(recommendation, 8013) == {"172.20.213.30/32"}
    assert ipblocks_for_egress_port(recommendation, 4317) == {"172.20.117.175/32"}
    assert recommendation["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == (
        "2026-07-25:kube-dns=172.20.0.10,product-catalog=172.20.145.185,"
        "flagd=172.20.213.30,otel-gateway=172.20.117.175"
    )


def test_shipping_has_observed_service_clusterip_peers():
    shipping = load_policy("30-shipping.yaml")
    assert ipblocks_for_egress_port(shipping, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(shipping, 8080) == {"172.20.233.86/32"}
    assert ipblocks_for_egress_port(shipping, 4317) == {"172.20.117.175/32"}
    assert shipping["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == (
        "2026-07-25:kube-dns=172.20.0.10,quote=172.20.233.86,"
        "otel-gateway=172.20.117.175"
    )


def test_cart_has_observed_service_and_elasticache_peers():
    cart = load_policy("21-cart.yaml")
    assert ipblocks_for_egress_port(cart, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(cart, 8013) == {"172.20.213.30/32"}
    assert ipblocks_for_egress_port(cart, 4317) == {"172.20.117.175/32"}
    assert ipblocks_for_egress_port(cart, 6379) == {
        "10.0.0.0/20",
        "10.0.16.0/20",
        "10.0.32.0/20",
    }
    assert cart["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == (
        "2026-07-25:kube-dns=172.20.0.10,flagd=172.20.213.30,"
        "otel-gateway=172.20.117.175"
    )


def test_product_catalog_has_observed_service_and_rds_peers():
    product_catalog = load_policy("20-product-catalog.yaml")
    assert ipblocks_for_egress_port(product_catalog, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(product_catalog, 8013) == {"172.20.213.30/32"}
    assert ipblocks_for_egress_port(product_catalog, 4317) == {"172.20.117.175/32"}
    assert ipblocks_for_egress_port(product_catalog, 5432) == {
        "10.0.0.0/20",
        "10.0.16.0/20",
        "10.0.32.0/20",
    }
    assert product_catalog["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == (
        "2026-07-25:kube-dns=172.20.0.10,flagd=172.20.213.30,"
        "otel-gateway=172.20.117.175"
    )


def test_product_reviews_has_observed_callers_and_runtime_dependencies():
    product_reviews = load_policy("32-product-reviews.yaml")
    private_subnets = {"10.0.0.0/20", "10.0.16.0/20", "10.0.32.0/20"}

    assert ingress_ports_from_source(product_reviews, "frontend") == {3551}
    assert ingress_ports_from_source(product_reviews, "shopping-copilot") == {3551}
    assert ipblocks_for_egress_port(product_reviews, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(product_reviews, 8080) == {
        "172.20.145.185/32"
    }
    assert ipblocks_for_egress_port(product_reviews, 8013) == {
        "172.20.213.30/32"
    }
    assert ipblocks_for_egress_port(product_reviews, 4317) == {
        "172.20.117.175/32"
    }
    assert ipblocks_for_egress_port(product_reviews, 5432) == private_subnets
    assert ipblocks_for_egress_port(product_reviews, 6379) == private_subnets
    assert ports_for_egress_destination(
        product_reviews, "product-reviews-egress-proxy"
    ) == {3128}
    assert ipblocks_for_egress_port(product_reviews, 3128) == {
        "172.20.255.151/32"
    }
    assert not contains_public_cidr(product_reviews)
    assert product_reviews["metadata"]["annotations"][
        "mandate-17.techx.io/ingress-caller-evidence"
    ] == "2026-07-29:frontend-and-shopping-copilot-to-product-reviews:3551"
    assert product_reviews["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == (
        "2026-07-29:kube-dns=172.20.0.10,"
        "product-catalog=172.20.145.185,flagd=172.20.213.30,"
        "otel-gateway=172.20.117.175,"
        "product-reviews-egress-proxy=172.20.255.151"
    )


def test_product_reviews_uses_a_dedicated_least_privilege_fqdn_proxy():
    chart_values = yaml.safe_load(
        (REPO / "phase3 - information/techx-corp-chart/values.yaml").read_text(
            encoding="utf-8"
        )
    )
    runtime_values = yaml.safe_load(
        (REPO / "phase3 - information/deploy/values-aio-llm.yaml").read_text(
            encoding="utf-8"
        )
    )
    template = (
        REPO
        / "phase3 - information/techx-corp-chart/templates/product-reviews-egress-proxy.yaml"
    ).read_text(encoding="utf-8")
    chart_schema = yaml.safe_load(
        (REPO / "phase3 - information/techx-corp-chart/values.schema.json").read_text(
            encoding="utf-8"
        )
    )

    proxy_defaults = chart_values["productReviewsEgressProxy"]
    assert proxy_defaults["enabled"] is False
    assert proxy_defaults["replicas"] == 2
    assert proxy_defaults["maxActiveConnections"] == 1024
    assert set(proxy_defaults["allowedAuthorities"]) == {
        "sts.us-east-1.amazonaws.com:443",
        "bedrock-runtime.us-east-1.amazonaws.com:443",
    }

    proxy_schema = chart_schema["definitions"]["ProductReviewsEgressProxy"]
    assert proxy_schema["additionalProperties"] is False
    assert proxy_schema["properties"]["replicas"]["minimum"] == 2
    assert proxy_schema["properties"]["allowedAuthorities"]["uniqueItems"] is True

    proxy_runtime = runtime_values["productReviewsEgressProxy"]
    assert proxy_runtime["enabled"] is True
    assert proxy_runtime["service"]["clusterIP"] == "172.20.255.151"

    overrides = {
        item["name"]: item
        for item in runtime_values["components"]["product-reviews"]["envOverrides"]
    }
    proxy_url = "http://product-reviews-egress-proxy.techx-tf3.svc.cluster.local:3128"
    assert overrides["HTTPS_PROXY"]["value"] == proxy_url
    assert overrides["https_proxy"]["value"] == proxy_url
    assert overrides["NO_PROXY"]["value"] == overrides["no_proxy"]["value"]
    no_proxy = set(overrides["NO_PROXY"]["value"].split(","))
    assert {"product-catalog", "flagd", "otel-gateway"} <= no_proxy
    assert ".svc.cluster.local" in no_proxy
    assert "techx-tf3-postgres" in overrides["NO_PROXY"]["value"]
    assert "techx-tf3-valkey" in overrides["NO_PROXY"]["value"]
    no_grpc_proxy = set(overrides["no_grpc_proxy"]["value"].split(","))
    assert {"product-catalog", "flagd", "otel-gateway"} <= no_grpc_proxy
    assert {
        "product-catalog.techx-tf3.svc.cluster.local",
        "flagd.techx-tf3.svc.cluster.local",
        "otel-gateway.techx-tf3.svc.cluster.local",
    } <= no_grpc_proxy

    assert "kind: PodDisruptionBudget" in template
    assert "minAvailable: 1" in template
    assert "accept_http_10: true" in template
    assert "upgrade_type: CONNECT" in template
    assert "envoy.filters.http.rbac" in template
    assert "global_downstream_max_connections" in template
    assert "app.kubernetes.io/component: product-reviews" in template
    assert "automountServiceAccountToken: false" in template
    assert "readOnlyRootFilesystem: true" in template


def test_jaeger_accepts_otel_gateway_grpc_ingest():
    jaeger = load_policy("02-jaeger.yaml")
    matching_ports = set()
    for rule in jaeger["spec"]["ingress"]:
        if any("otel-gateway" in peer_components(peer) for peer in rule.get("from", [])):
            matching_ports.update(port["port"] for port in rule.get("ports", []))
    assert 4317 in matching_ports


def test_active_jaeger_replaces_broad_legacy_ingress_in_place():
    jaeger = load_active_policy("network-policy-jaeger.yaml", "jaeger-access")
    assert set(jaeger["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    assert all(
        peer.get("podSelector") != {}
        for rule in jaeger["spec"].get("ingress", [])
        for peer in rule.get("from", [])
    )

    otel_ports = set()
    for rule in jaeger["spec"]["ingress"]:
        if any(
            peer.get("podSelector", {})
            .get("matchLabels", {})
            .get("app.kubernetes.io/component")
            == "otel-gateway"
            for peer in rule.get("from", [])
        ):
            otel_ports.update(port["port"] for port in rule.get("ports", []))
    assert otel_ports == {4317}


def test_active_jaeger_has_observed_service_clusterip_fallbacks():
    jaeger = load_active_policy("network-policy-jaeger.yaml", "jaeger-access")
    assert ipblocks_for_egress_port(jaeger, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(jaeger, 9090) == {"172.20.123.8/32"}
    assert ipblocks_for_egress_port(jaeger, 4318) == {"172.20.117.175/32"}
    assert jaeger["metadata"]["annotations"][
        "mandate-17.techx.io/service-clusterip-evidence"
    ] == (
        "2026-07-25:kube-dns=172.20.0.10,prometheus=172.20.123.8,"
        "otel-gateway=172.20.117.175"
    )


FRONTEND_PROXY_ACTIVE = "network-policy-frontend-proxy.yaml"
FRONTEND_PROXY_STAGED = "35-frontend-proxy.yaml"
FRONTEND_PROXY_NAME = "frontend-proxy-business-policy"


def test_active_frontend_proxy_matches_staged_copy_exactly():
    active = (INFRA / FRONTEND_PROXY_ACTIVE).read_text()
    staged = (INFRA / "network-policy-staged" / FRONTEND_PROXY_STAGED).read_text()
    assert active == staged, (
        "promoted frontend-proxy policy drifted from its staged source"
    )


def test_active_frontend_proxy_egress_is_exactly_the_observed_dependencies():
    policy = load_active_policy(FRONTEND_PROXY_ACTIVE, FRONTEND_PROXY_NAME)
    assert set(policy["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    assert egress_components(policy) == {"frontend", "image-provider", "flagd", "otel-gateway"}

    assert ports_for_egress_destination(policy, "frontend") == {8080}
    assert ports_for_egress_destination(policy, "image-provider") == {8081}
    assert ports_for_egress_destination(policy, "otel-gateway") == {4317, 4318}

    # /flagservice must stay reachable; flagd-ui (4000) is an orphaned cluster and
    # stays closed, so this assertion is deliberately exact rather than a superset.
    assert ports_for_egress_destination(policy, "flagd") == {8013}

    assert ipblocks_for_egress_port(policy, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(policy, 8080) == {"172.20.212.8/32"}
    assert ipblocks_for_egress_port(policy, 8081) == {"172.20.1.116/32"}
    assert ipblocks_for_egress_port(policy, 8013) == {"172.20.213.30/32"}
    assert ipblocks_for_egress_port(policy, 4317) == {"172.20.117.175/32"}


def test_active_frontend_proxy_never_exposes_envoy_admin():
    policy = load_active_policy(FRONTEND_PROXY_ACTIVE, FRONTEND_PROXY_NAME)
    ingress_ports = {
        port["port"]
        for rule in policy["spec"].get("ingress", [])
        for port in rule.get("ports", [])
    }
    assert ingress_ports == {8080}, "only the Envoy data plane port may be reachable"
    assert 10000 not in ingress_ports, "Envoy admin interface must never be allowed"


def test_active_frontend_proxy_ingress_sources_are_the_alb_subnets_and_named_peers():
    policy = load_active_policy(FRONTEND_PROXY_ACTIVE, FRONTEND_PROXY_NAME)
    cidrs = set()
    components = set()
    for rule in policy["spec"].get("ingress", []):
        for peer in rule.get("from", []):
            if "ipBlock" in peer:
                cidrs.add(peer["ipBlock"]["cidr"])
            selector = peer.get("podSelector", {})
            labels = selector.get("matchLabels", {})
            components.update(
                v
                for k, v in labels.items()
                if k in ("app.kubernetes.io/component", "app.kubernetes.io/name")
            )
    # The internal ALB places one ENI in each production private subnet. This is a
    # CIDR constraint, not a Security Group match - NetworkPolicy cannot express the
    # latter, so any workload in these subnets also matches.
    assert cidrs == {"10.0.0.0/20", "10.0.16.0/20", "10.0.32.0/20"}
    assert components == {"cloudflared", "load-generator"}


CLOUDFLARED_ACTIVE = "network-policy-cloudflared.yaml"
CLOUDFLARED_STAGED = "06-cloudflared.yaml"
CLOUDFLARED_NAME = "cloudflared-platform-policy"

# https://www.cloudflare.com/ips-v4, read 2026-07-26. cloudflared dials the Tunnel edge
# (region1/region2.v2.argotunnel.com, observed inside 198.41.128.0/17) and the Cloudflare
# API, both of which stay inside this list.
CLOUDFLARE_EDGE_RANGES = {
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
}


def test_active_cloudflared_matches_staged_copy_exactly():
    active = (INFRA / CLOUDFLARED_ACTIVE).read_text()
    staged = (INFRA / "network-policy-staged" / CLOUDFLARED_STAGED).read_text()
    assert active == staged, (
        "promoted cloudflared policy drifted from its staged source"
    )


def test_active_cloudflared_accepts_no_ingress():
    policy = load_active_policy(CLOUDFLARED_ACTIVE, CLOUDFLARED_NAME)
    assert set(policy["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    # cloudflared publishes no Service and is dialled by nobody. The kubelet probe on
    # :2000 is node-sourced and is not evaluated by the VPC CNI policy agent.
    assert policy["spec"]["ingress"] == []


def test_active_cloudflared_egress_reaches_only_cloudflare_and_the_four_tunnel_routes():
    policy = load_active_policy(CLOUDFLARED_ACTIVE, CLOUDFLARED_NAME)

    # Tunnel transport is pinned to Cloudflare's published ranges, never 0.0.0.0/0.
    for port in (443, 7844):
        assert CLOUDFLARE_EDGE_RANGES <= ipblocks_for_egress_port(policy, port)

    # QUIC runs on 7844, and cloudflared's Go HTTP client does not speak HTTP/3, so
    # 443/udp has no caller and must stay closed.
    protocol_ports = {
        (item.get("protocol", "TCP"), item["port"])
        for rule in policy["spec"].get("egress", [])
        for item in rule.get("ports", [])
    }
    assert ("UDP", 7844) in protocol_ports
    assert ("TCP", 7844) in protocol_ports
    assert ("UDP", 443) not in protocol_ports

    # Route 1 - kubectl.arthur-ngo.org reaches the private EKS endpoint ENIs, which EKS
    # rotates on its own, so the three production private subnets are the stable unit.
    assert ipblocks_for_egress_port(policy, 443) == CLOUDFLARE_EDGE_RANGES | {
        "10.0.0.0/20",
        "10.0.16.0/20",
        "10.0.32.0/20",
        "172.20.60.48/32",
    }

    # Routes 2-4 are split across pre-DNAT (ClusterIP) and post-DNAT (pod) ports wherever
    # the Service remaps the port: grafana 80 -> 3000 and argocd-server 443 -> 8080.
    assert ipblocks_for_egress_port(policy, 80) == {"172.20.79.132/32"}
    assert ipblocks_for_egress_port(policy, 16686) == {"172.20.93.48/32"}
    assert ipblocks_for_egress_port(policy, 53) == {"172.20.0.10/32"}

    names = set()
    for rule in policy["spec"].get("egress", []):
        for peer in rule.get("to", []):
            names.update(
                peer.get("podSelector", {}).get("matchLabels", {}).get(key)
                for key in ("app.kubernetes.io/name", "app.kubernetes.io/component")
            )
    names.discard(None)
    # CoreDNS is matched on k8s-app and is asserted by the shared CoreDNS test above.
    # The storefront is served through CloudFront, never through this tunnel, so
    # frontend-proxy must not appear here.
    assert names == {"grafana", "jaeger", "argocd-server"}


def test_every_non_default_egress_policy_has_exact_coredns_rule():
    for filename in EXPECTED_FILES - {"90-default-deny-all.yaml"}:
        policy = load_policy(filename)
        if "Egress" not in policy["spec"].get("policyTypes", []):
            continue
        found = False
        for rule in policy["spec"].get("egress", []):
            for peer in rule.get("to", []):
                namespace = peer.get("namespaceSelector", {}).get("matchLabels", {})
                pod = peer.get("podSelector", {}).get("matchLabels", {})
                if (
                    namespace.get("kubernetes.io/metadata.name") == "kube-system"
                    and pod.get("k8s-app") == "kube-dns"
                ):
                    ports = {
                        (item.get("protocol", "TCP"), item["port"])
                        for item in rule.get("ports", [])
                    }
                    if ports == {("TCP", 53), ("UDP", 53)}:
                        found = True
        assert found, f"{filename} is missing the exact CoreDNS rule"


def test_prometheus_allows_coredns_metrics_scrape():
    for path in [
        INFRA / "network-policy-prometheus.yaml",
        STAGED / "03-prometheus.yaml",
    ]:
        policy = load_documents(path)[0]
        found = False
        for rule in policy["spec"].get("egress", []):
            peers = rule.get("to", [])
            ports = {
                (item.get("protocol", "TCP"), item["port"])
                for item in rule.get("ports", [])
            }
            for peer in peers:
                namespace = peer.get("namespaceSelector", {}).get("matchLabels", {})
                pod = peer.get("podSelector", {}).get("matchLabels", {})
                if (
                    namespace.get("kubernetes.io/metadata.name") == "kube-system"
                    and pod.get("k8s-app") == "kube-dns"
                    and ("TCP", 9153) in ports
                ):
                    found = True
        assert found, f"{path.name} must allow Prometheus to scrape CoreDNS metrics"


def test_opensearch_dns_uses_observed_clusterip_fallback():
    for path in [
        INFRA / "network-policy-opensearch.yaml",
        STAGED / "04-opensearch.yaml",
    ]:
        policy = load_documents(path)[0]
        assert ipblocks_for_egress_port(policy, 53) == {"172.20.0.10/32"}


def test_public_egress_is_blocked_from_promotion_and_never_active():
    staged_public = {
        filename
        for filename in EXPECTED_FILES
        if contains_public_cidr(load_policy(filename))
    }
    assert staged_public == PUBLIC_EGRESS_FILES
    for filename in staged_public:
        annotations = load_policy(filename)["metadata"].get("annotations", {})
        assert annotations.get("mandate-17.techx.io/promotion-blocked") == "true"
        assert annotations.get("mandate-17.techx.io/promotion-blocker")

    allowed_active_public = {
        (
            REPO / "gitops/aiops-engine/networkpolicy.yaml",
            "aiops-egress-proxy-policy",
        ),
        # shopping-copilot's egress proxy, same role as the aiops one: it is the single
        # chokepoint that replaces public egress from the workload. The proxy's Envoy RBAC
        # only permits CONNECT to an explicit authority allowlist
        # (gitops/shopping-copilot/egress-proxy.yaml), and the copilot pod's own policy has
        # no public rule - it can only reach the proxy on 3128.
        (
            INFRA / "network-policy-shopping-copilot-egress-proxy.yaml",
            "shopping-copilot-egress-proxy-policy",
        ),
    }

    for path in list(INFRA.glob("*.yaml")) + [
        REPO / "gitops/aiops-engine/networkpolicy.yaml"
    ]:
        for document in load_documents(path):
            if document.get("kind") == "NetworkPolicy":
                identity = (path, document.get("metadata", {}).get("name"))
                if identity in allowed_active_public:
                    continue
                assert not contains_public_cidr(document), (
                    f"active policy {path.name} must not allow 0.0.0.0/0"
                )


def test_ad_is_the_clusterip_canary_and_aiops_api_use_is_verified():
    ad = load_policy("14-ad.yaml")
    ad_annotations = ad["metadata"]["annotations"]
    assert ad_annotations["mandate-17.techx.io/rollout-role"] == "first-canary"
    assert ad_annotations["mandate-17.techx.io/clusterip-proof"] == (
        "required-before-wider-promotion"
    )
    assert ad_annotations["mandate-17.techx.io/service-clusterip-evidence"] == (
        "2026-07-25:kube-dns=172.20.0.10,flagd=172.20.213.30,"
        "otel-gateway=172.20.117.175"
    )
    assert ipblocks_for_egress_port(ad, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(ad, 8013) == {"172.20.213.30/32"}
    assert ipblocks_for_egress_port(ad, 4318) == {"172.20.117.175/32"}
    aiops_annotations = load_policy("07-aiops-engine.yaml")["metadata"]["annotations"]
    assert aiops_annotations["mandate-17.techx.io/kubernetes-api-dependency"].startswith(
        "verified:"
    )


def test_aiops_active_policies_force_public_https_through_fqdn_proxy():
    policies = REPO / "gitops/aiops-engine/networkpolicy.yaml"
    proxy = load_policy_from_file(policies, "aiops-egress-proxy-policy")
    engine = load_policy_from_file(policies, "aiops-engine-platform-policy")
    trainer = load_policy_from_file(policies, "aiops-trainer-platform-policy")

    assert proxy["spec"]["podSelector"]["matchLabels"] == {
        "app.kubernetes.io/name": "aiops-egress-proxy"
    }
    assert engine["spec"]["podSelector"]["matchLabels"] == {
        "app.kubernetes.io/name": "aiops-engine"
    }
    assert trainer["spec"]["podSelector"]["matchLabels"] == {
        "app": "aiops-engine",
        "component": "trainer",
    }

    assert contains_public_cidr(proxy)
    assert not contains_public_cidr(engine)
    assert not contains_public_cidr(trainer)
    assert ipblocks_for_egress_port(proxy, 443) == {"0.0.0.0/0"}

    assert ipblocks_for_egress_port(engine, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(engine, 9090) == {"172.20.123.8/32"}
    assert ipblocks_for_egress_port(engine, 16686) == {"172.20.93.48/32"}
    assert ipblocks_for_egress_port(engine, 9200) == {"172.20.106.195/32"}
    assert ipblocks_for_egress_port(engine, 443) == {
        "172.20.0.1/32",
        "10.0.0.0/20",
        "10.0.16.0/20",
        "10.0.32.0/20",
    }
    assert ports_for_egress_destination(engine, "aiops-egress-proxy") == {3128}
    assert ipblocks_for_egress_port(engine, 3128) == {"172.20.255.150/32"}

    assert ipblocks_for_egress_port(trainer, 53) == {"172.20.0.10/32"}
    assert ipblocks_for_egress_port(trainer, 9090) == {"172.20.123.8/32"}
    assert ports_for_egress_destination(trainer, "aiops-egress-proxy") == {3128}
    assert ipblocks_for_egress_port(trainer, 3128) == {"172.20.255.150/32"}

    proxy_annotations = proxy["metadata"]["annotations"]
    assert proxy_annotations["mandate-17.techx.io/public-egress-control"] == (
        "envoy-forward-proxy-fqdn-rbac"
    )
    assert "bedrock-runtime.us-east-1.amazonaws.com:443" in proxy_annotations[
        "mandate-17.techx.io/allowed-external-authorities"
    ]


def test_aiops_egress_proxy_enables_connect_upgrades_on_connection_manager():
    documents = load_documents(REPO / "gitops/aiops-engine/egress-proxy.yaml")
    config_map = next(
        document
        for document in documents
        if document["kind"] == "ConfigMap"
        and document["metadata"]["name"] == "aiops-egress-proxy-config"
    )
    envoy_config = yaml.safe_load(config_map["data"]["egress-proxy.yaml"])
    hcm_config = envoy_config["static_resources"]["listeners"][0]["filter_chains"][0][
        "filters"
    ][0]["typed_config"]

    assert {"upgrade_type": "CONNECT"} in hcm_config["upgrade_configs"]


def test_aiops_egress_proxy_accepts_http10_connect_clients():
    documents = load_documents(REPO / "gitops/aiops-engine/egress-proxy.yaml")
    config_map = next(
        document
        for document in documents
        if document["kind"] == "ConfigMap"
        and document["metadata"]["name"] == "aiops-egress-proxy-config"
    )
    envoy_config = yaml.safe_load(config_map["data"]["egress-proxy.yaml"])
    hcm_config = envoy_config["static_resources"]["listeners"][0]["filter_chains"][0][
        "filters"
    ][0]["typed_config"]

    assert hcm_config["http_protocol_options"]["accept_http_10"] is True


def test_aiops_egress_proxy_allows_aws_authorities_with_optional_default_https_port():
    matchers = aiops_egress_proxy_authority_matchers()
    required_hosts = {
        "sts.amazonaws.com",
        "sts.ap-southeast-1.amazonaws.com",
        "s3.ap-southeast-1.amazonaws.com",
        "tf3-aiops-models-197826770971.s3.amazonaws.com",
        "tf3-aiops-models-197826770971.s3.ap-southeast-1.amazonaws.com",
        "bedrock-runtime.us-east-1.amazonaws.com",
        "bedrock-agent-runtime.us-east-1.amazonaws.com",
    }

    for host in required_hosts:
        escaped_host = host.replace(".", "\\.")
        assert {
            "safe_regex": {
                "google_re2": {},
                "regex": f"^{escaped_host}(?::443)?$",
            }
        } in matchers


def test_aiops_engine_pins_irsa_regional_sts_and_model_bucket():
    deployment = next(
        document
        for document in load_documents(REPO / "gitops/aiops-engine/deployment.yaml")
        if document["kind"] == "Deployment"
        and document["metadata"]["name"] == "aiops-engine"
    )
    env = {
        item["name"]: item["value"]
        for item in deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        if "value" in item
    }

    assert env["AWS_STS_REGIONAL_ENDPOINTS"] == "regional"
    assert env["AIOPS_S3_BUCKET"] == "tf3-aiops-models-197826770971"


def test_default_deny_is_empty_and_marked_last():
    policy = load_policy("90-default-deny-all.yaml")
    assert policy["spec"]["podSelector"] == {}
    assert set(policy["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    assert "ingress" not in policy["spec"]
    assert "egress" not in policy["spec"]
    assert policy["metadata"]["annotations"][
        "mandate-17.techx.io/activation-order"
    ] == "last"


def test_argocd_does_not_recurse_into_staging():
    application = yaml.safe_load(
        (REPO / "gitops/apps/infrastructure-app.yaml").read_text(encoding="utf-8")
    )
    source = application["spec"]["source"]
    assert source["path"] == "gitops/infrastructure"
    assert source.get("directory", {}).get("recurse") is not True


def test_rollout_runbook_requires_canary_owner_and_last_default_deny():
    runbook = (STAGED / "README.md").read_text(encoding="utf-8")
    assert runbook.index("14-ad.yaml") < runbook.index("remaining leaf services")
    assert runbook.rindex("90-default-deny-all.yaml") > runbook.index("platform policies")
    assert "ownerReferences" in runbook
    assert "bare Pod is not accepted" in runbook
    assert "promotion-blocked" in runbook


def test_rollout_runbook_requires_active_policy_inventory_and_replacement():
    runbook = (STAGED / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(runbook.split())
    required_markers = {
        "NetworkPolicy rules are additive",
        "networkpolicies-before.yaml",
        "update-in-place",
        "overlapping policy has no documented disposition",
        "jaeger-access",
        "Adding `jaeger-platform-policy` beside the old policy is not a valid restriction",
        "replaced object was pruned",
    }
    for marker in required_markers:
        assert marker in normalized


def run_deny_classifier(function, rc, output):
    completed = subprocess.run(
        [
            BASH,
            "-c",
            'source "$1"; "$2" "$3" "$4"',
            "bash",
            str(CONNECTIVITY_SCRIPT),
            function,
            str(rc),
            output,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


@pytest.mark.skipif(
    os.name == "nt" or BASH is None,
    reason="deny classifier contract requires a native Bash runtime",
)
@pytest.mark.parametrize(
    ("rc", "output", "expected"),
    [
        (1, "nc: connect to payment port 8080 (tcp) timed out", True),
        (1, "nc: connect to payment port 8080 (tcp) failed: Connection refused", False),
        (1, "nc: bad address 'payment'", False),
        (1, "nc: connect to payment port 8080 (tcp) failed: No route to host", False),
        (1, "nc: invalid timeout value", False),
        (0, "Connection to payment 8080 port [tcp/*] succeeded!", False),
    ],
)
def test_tcp_deny_classifier_only_accepts_timeouts(rc, output, expected):
    assert run_deny_classifier("tcp_deny_confirmed", rc, output) is expected


@pytest.mark.skipif(
    os.name == "nt" or BASH is None,
    reason="deny classifier contract requires a native Bash runtime",
)
@pytest.mark.parametrize(
    ("rc", "output", "expected"),
    [
        (28, "curl: (28) Connection timed out after 5001 milliseconds", True),
        (7, "curl: (7) Failed to connect: Connection refused", False),
        (6, "curl: (6) Could not resolve host: example.com", False),
        (28, "curl exited without expected evidence", False),
        (28, "curl: invalid timeout option", False),
        (0, "HTTP/2 403", False),
    ],
)
def test_https_deny_classifier_requires_curl_timeout(rc, output, expected):
    assert run_deny_classifier("https_deny_confirmed", rc, output) is expected
