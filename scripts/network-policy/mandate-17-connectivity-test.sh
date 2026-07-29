#!/usr/bin/env bash

# Read-only connectivity checks for Mandate 17.
# This script never applies, patches, edits, deletes, or syncs resources.

set -uo pipefail

NS="${NAMESPACE:-techx-tf3}"
ARGO_NS="${ARGO_NAMESPACE:-argocd}"
URL="${STOREFRONT_URL:-https://d2tn71186d7ilz.cloudfront.net/}"
TIMEOUT="${TIMEOUT_SECONDS:-5}"
PRODUCT_REVIEWS_RDS_HOST="${PRODUCT_REVIEWS_RDS_HOST:-techx-tf3-postgres.czwcs2ocww3q.ap-southeast-1.rds.amazonaws.com}"
PRODUCT_REVIEWS_VALKEY_HOST="${PRODUCT_REVIEWS_VALKEY_HOST:-master.techx-tf3-valkey.pkeslh.apse1.cache.amazonaws.com}"
MODE="${1:-}"
POLICY="${2:-}"
POLICY="$(printf '%s' "$POLICY" | sed 's/\.yaml$//')"

usage() {
  printf '%s\n' \
    'Usage:' \
    '  mandate-17-connectivity-test.sh baseline' \
    '  mandate-17-connectivity-test.sh policy <policy-id>' \
    '  mandate-17-connectivity-test.sh full'
}

failures=0
blocked=0

check() {
  local label="$1"
  shift
  if "$@"; then
    echo "PASS $label"
  else
    echo "FAIL $label"
    failures=$((failures + 1))
  fi
}

is_timeout_output() {
  local output="$1"
  grep -Eqi \
    '(^|[^[:alpha:]])((operation|connection)[[:space:]]+)?timed[[:space:]]+out([^[:alpha:]]|$)' \
    <<<"$output"
}

tcp_deny_confirmed() {
  local rc="$1" output="$2"
  [[ "$rc" -ne 0 ]] && is_timeout_output "$output"
}

https_deny_confirmed() {
  local rc="$1" output="$2"
  [[ "$rc" -eq 28 ]] && is_timeout_output "$output"
}

exec_or_tool_unavailable() {
  local output="$1"
  grep -Eqi \
    'forbidden|unauthorized|executable file not found|command not found|no such file or directory' \
    <<<"$output"
}

pod_for() {
  local service="$1"
  local selector
  case "$service" in
    grafana|jaeger|prometheus|opensearch|cloudflared)
      selector="app.kubernetes.io/name=$service"
      ;;
    aiops-engine|shopping-copilot)
      selector="app=$service"
      ;;
    *)
      selector="app.kubernetes.io/component=$service"
      ;;
  esac
  kubectl get pods -n "$NS" -l "$selector" \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
}

should_run() {
  [[ "$MODE" != policy || "$POLICY" == "$1" || "$POLICY" == 90-default-deny-all ]]
}

tcp() {
  local policy="$1" name="$2" source="$3" destination="$4" port="$5" expected="$6"
  should_run "$policy" || return
  local pod output rc
  pod="$(pod_for "$source")"
  if [[ -z "$pod" ]]; then
    echo "BLOCKED [$policy] $name: no running pod for $source"
    blocked=$((blocked + 1))
    return
  fi
  output="$(kubectl exec -n "$NS" "$pod" -- nc -z -v -w "$TIMEOUT" \
    "$destination" "$port" 2>&1)"
  rc=$?
  if exec_or_tool_unavailable "$output"; then
    echo "BLOCKED [$policy] $name: exec or nc unavailable"
    blocked=$((blocked + 1))
  elif [[ "$MODE" == baseline && "$expected" == deny ]]; then
    echo "OBSERVE [$policy] $name: baseline rc=$rc output=$output"
  elif [[ "$expected" == allow && $rc -eq 0 ]]; then
    echo "PASS [$policy] $name"
  elif [[ "$expected" == deny ]] && tcp_deny_confirmed "$rc" "$output"; then
    echo "PASS [$policy] $name: denied by timeout"
  else
    echo "FAIL [$policy] $name: expected=$expected rc=$rc output=$output"
    failures=$((failures + 1))
  fi
}

https_test() {
  local policy="$1" name="$2" source="$3" destination="$4" expected="$5"
  should_run "$policy" || return
  local pod output rc
  pod="$(pod_for "$source")"
  if [[ -z "$pod" ]]; then
    echo "BLOCKED [$policy] $name: no running pod for $source"
    blocked=$((blocked + 1))
    return
  fi
  output="$(kubectl exec -n "$NS" "$pod" -- curl -sS -I \
    --connect-timeout "$TIMEOUT" "$destination" 2>&1)"
  rc=$?
  if exec_or_tool_unavailable "$output"; then
    echo "BLOCKED [$policy] $name: exec or curl unavailable"
    blocked=$((blocked + 1))
  elif [[ "$MODE" == baseline && "$expected" == deny ]]; then
    echo "OBSERVE [$policy] $name: baseline rc=$rc output=$output"
  elif [[ "$expected" == allow && $rc -eq 0 && "$output" == *HTTP/* ]]; then
    echo "PASS [$policy] $name"
  elif [[ "$expected" == deny ]] && https_deny_confirmed "$rc" "$output"; then
    echo "PASS [$policy] $name: denied by connect timeout"
  else
    echo "FAIL [$policy] $name: expected=$expected rc=$rc output=$output"
    failures=$((failures + 1))
  fi
}

main() {
  if [[ "$MODE" != baseline && "$MODE" != policy && "$MODE" != full ]]; then
    usage
    return 64
  fi
  if [[ "$MODE" == policy && -z "$POLICY" ]]; then
    usage
    return 64
  fi

  command -v kubectl >/dev/null 2>&1 || return 69
  command -v curl >/dev/null 2>&1 || return 69

  OUT=outputs/mandate-17/$(date -u +%Y%m%dT%H%M%SZ)-$MODE
  mkdir -p "$OUT"
  exec > >(tee "$OUT/run.log") 2>&1

echo "Mandate 17 mode=$MODE policy=$POLICY namespace=$NS"
check 'exec permission' kubectl auth can-i create pods/exec -n "$NS"
check 'Argo applications' kubectl get applications.argoproj.io -n "$ARGO_NS" \
  techx-infrastructure-app techx-corp
check 'pods' kubectl get pods -n "$NS" -o wide
check 'events' kubectl get events -n "$NS" --sort-by=.lastTimestamp
check 'network policies' kubectl get networkpolicies -n "$NS"
check 'PolicyEndpoints' kubectl get policyendpoints.networking.k8s.aws -n "$NS"
check 'storefront HTTP 200' curl -fsS -o /dev/null -w '%{http_code}\n' "$URL"

tcp 10-quote shipping-to-quote shipping quote 8080 allow
tcp 10-quote frontend-to-quote frontend quote 8080 deny
tcp 11-currency frontend-to-currency frontend currency 8080 allow
tcp 11-currency checkout-to-currency checkout currency 8080 allow
tcp 11-currency cart-to-currency cart currency 8080 deny
tcp 12-payment checkout-to-payment checkout payment 8080 allow
tcp 12-payment cart-to-payment cart payment 8080 deny
tcp 12-payment payment-to-flagd payment flagd 8013 allow
tcp 12-payment payment-to-cart payment cart 8080 deny
tcp 13-email checkout-to-email checkout email 8080 allow
tcp 13-email cart-to-email cart email 8080 deny
tcp 13-email email-to-flagd email flagd 8013 allow
tcp 14-ad frontend-to-ad frontend ad 8080 allow
tcp 14-ad checkout-to-ad checkout ad 8080 deny
tcp 14-ad ad-to-flagd ad flagd 8013 allow
tcp 15-image-provider proxy-to-image frontend-proxy image-provider 8081 allow
tcp 15-image-provider frontend-to-image frontend image-provider 8081 deny
tcp 16-llm reviews-to-local-llm product-reviews llm 8080 deny
tcp 16-llm llm-to-flagd llm flagd 8013 allow
tcp 20-product-catalog frontend-to-catalog frontend product-catalog 8080 allow
tcp 20-product-catalog cart-to-catalog cart product-catalog 8080 deny
tcp 21-cart frontend-to-cart frontend cart 8080 allow
tcp 21-cart cart-to-payment cart payment 8080 deny
tcp 22-accounting accounting-to-otel accounting otel-gateway 4318 allow
tcp 22-accounting accounting-to-payment accounting payment 8080 deny
tcp 23-fraud-detection fraud-to-flagd fraud-detection flagd 8013 allow
tcp 23-fraud-detection fraud-to-payment fraud-detection payment 8080 deny
tcp 30-shipping checkout-to-shipping checkout shipping 8080 allow
tcp 30-shipping shipping-to-quote shipping quote 8080 allow
tcp 30-shipping checkout-to-quote checkout quote 8080 deny
tcp 31-recommendation frontend-to-recommendation frontend recommendation 8080 allow
tcp 31-recommendation recommendation-to-catalog recommendation product-catalog 8080 allow
tcp 31-recommendation checkout-to-recommendation checkout recommendation 8080 deny
tcp 33-checkout frontend-to-checkout frontend checkout 8080 allow
tcp 33-checkout checkout-to-payment checkout payment 8080 allow
tcp 33-checkout checkout-to-quote checkout quote 8080 deny
tcp 34-frontend proxy-to-frontend frontend-proxy frontend 8080 allow
tcp 34-frontend frontend-to-payment frontend payment 8080 deny
tcp 35-frontend-proxy proxy-to-flagd frontend-proxy flagd 8013 allow
tcp 35-frontend-proxy proxy-to-payment frontend-proxy payment 8080 deny
tcp 40-flagd checkout-to-flagd checkout flagd 8013 allow
tcp 40-flagd shipping-to-flagd shipping flagd 8013 deny
tcp 00-otel-gateway checkout-to-otel checkout otel-gateway 4317 allow
tcp 00-otel-gateway otel-to-jaeger otel-gateway jaeger 4317 allow
tcp 00-otel-gateway otel-to-payment otel-gateway payment 8080 deny
tcp 01-grafana grafana-to-prometheus grafana prometheus 9090 allow
tcp 01-grafana grafana-to-payment grafana payment 8080 deny
tcp 02-jaeger jaeger-to-prometheus jaeger prometheus 9090 allow
tcp 02-jaeger jaeger-to-payment jaeger payment 8080 deny
tcp 03-prometheus prometheus-to-api prometheus kubernetes.default.svc 443 allow
tcp 03-prometheus prometheus-to-payment prometheus payment 8080 deny
tcp 04-opensearch opensearch-to-dns opensearch kube-dns.kube-system.svc.cluster.local 53 allow
tcp 04-opensearch opensearch-to-payment opensearch payment 8080 deny
tcp 05-load-generator loadgen-to-proxy load-generator frontend-proxy 8080 allow
tcp 05-load-generator loadgen-to-payment load-generator payment 8080 deny
tcp 06-cloudflared cloudflared-to-proxy cloudflared frontend-proxy 8080 allow
tcp 06-cloudflared cloudflared-to-payment cloudflared payment 8080 deny
tcp 07-aiops-engine aiops-to-prometheus aiops-engine prometheus 9090 allow
tcp 07-aiops-engine aiops-to-payment aiops-engine payment 8080 deny
tcp 32-product-reviews frontend-to-reviews frontend product-reviews 3551 allow
tcp 32-product-reviews copilot-to-reviews shopping-copilot product-reviews 3551 allow
tcp 32-product-reviews checkout-to-reviews checkout product-reviews 3551 deny
tcp 32-product-reviews reviews-to-catalog product-reviews product-catalog 8080 allow
tcp 32-product-reviews reviews-to-flagd product-reviews flagd 8013 allow
tcp 32-product-reviews reviews-to-otel product-reviews otel-gateway 4317 allow
tcp 32-product-reviews reviews-to-rds product-reviews "$PRODUCT_REVIEWS_RDS_HOST" 5432 allow
tcp 32-product-reviews reviews-to-valkey product-reviews "$PRODUCT_REVIEWS_VALKEY_HOST" 6379 allow
https_test 32-product-reviews reviews-to-bedrock product-reviews https://bedrock-runtime.us-east-1.amazonaws.com allow
https_test 33-checkout checkout-to-internet checkout https://example.com deny
https_test 90-default-deny-all cart-to-internet cart https://example.com deny

echo 'Manual smoke required: browse -> add-to-cart -> checkout'
echo 'Manual protected path required: frontend-proxy -> /flagservice'
echo "failures=$failures blocked=$blocked output=$OUT"

  (( failures > 0 )) && return 1
  (( blocked > 0 )) && return 2
  return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
