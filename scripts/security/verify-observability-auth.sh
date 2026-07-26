#!/usr/bin/env bash
set -euo pipefail

echo "Running SEC - Observability Runtime Auth Verification"

GRAFANA_URL="${GRAFANA_URL:-https://grafana.arthur-ngo.org}"
JAEGER_URL="${JAEGER_URL:-https://jaeger.arthur-ngo.org}"
PROMETHEUS_URL="${PROMETHEUS_URL:-https://prometheus.arthur-ngo.org}"
NAMESPACE="${NAMESPACE:-techx-tf3}"
GRAFANA_LOCAL_URL="${GRAFANA_LOCAL_URL:-http://127.0.0.1:13000}"
EXPECTED_GRAFANA_MODE="${EXPECTED_GRAFANA_MODE:-disabled}"
EXTERNAL_ONLY="${EXTERNAL_ONLY:-false}"

declare -i ERRORS=0

trusted_access_redirect() {
  local location="$1"
  local host

  host="$(
    python3 - "$location" <<'PY'
import sys
from urllib.parse import urlparse

parsed = urlparse(sys.argv[1])

if parsed.scheme.lower() != "https":
    raise SystemExit(1)

if parsed.username or parsed.password:
    raise SystemExit(1)

host = (parsed.hostname or "").lower().rstrip(".")
if not host:
    raise SystemExit(1)

print(host)
PY
  )" || return 1

  case "$host" in
    *.cloudflareaccess.com)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

classify_external() {
  local service="$1"
  local url="$2"
  local headers
  local status
  local location
  local curl_exit

  echo "Testing $service external endpoint ($url)..."
  headers="$(mktemp)"

  set +e
  status="$(
    curl \
      --config /dev/null \
      --silent \
      --show-error \
      --cookie '' \
      --header 'Authorization:' \
      --connect-timeout 5 \
      --max-time 15 \
      --request GET \
      --dump-header "$headers" \
      --output /dev/null \
      --write-out '%{http_code}' \
      "$url"
  )"
  curl_exit=$?
  set -e

  if [ "$curl_exit" -ne 0 ]; then
    echo "Classification: QUERY_ERROR ($service)"
    ERRORS+=1
    rm -f "$headers"
    return
  fi

  location="$(
    awk '
      BEGIN { IGNORECASE=1 }
      /^Location:/ {
        sub(/^[^:]+:[[:space:]]*/, "")
        sub(/\r$/, "")
        value=$0
      }
      END { print value }
    ' "$headers"
  )"

  rm -f "$headers"

  case "$status" in
    200)
      echo "Classification: PUBLIC_UNAUTHENTICATED ($service)"
      ERRORS+=1
      ;;

    401|403)
      echo "Classification: AUTHENTICATED ($service)"
      ;;

    302|303|307|308)
      if trusted_access_redirect "$location"; then
        echo "Classification: AUTHENTICATED ($service)"
      else
        echo "Classification: UNTRUSTED_REDIRECT ($service)"
        ERRORS+=1
      fi
      ;;

    404)
      echo "Classification: NOT_PUBLICLY_ROUTED ($service)"
      ;;

    *)
      echo "Classification: QUERY_ERROR status=$status ($service)"
      ERRORS+=1
      ;;
  esac
}

echo "--- 1. Testing External Access Exposure ---"
classify_external "Grafana" "$GRAFANA_URL"
classify_external "Jaeger" "$JAEGER_URL"
classify_external "Prometheus" "$PROMETHEUS_URL"

# Verify we have kubectl
if ! command -v kubectl &> /dev/null; then
    if [ "$EXTERNAL_ONLY" = "true" ]; then
        echo "WARNING: kubectl is not installed. Skipping internal cluster verification because EXTERNAL_ONLY=true."
        if [ $ERRORS -gt 0 ]; then
            exit 1
        fi
        exit 0
    else
        echo "FAIL: kubectl is required but missing. (Set EXTERNAL_ONLY=true to override)"
        exit 1
    fi
fi

if [ "$EXTERNAL_ONLY" = "true" ]; then
    echo "EXTERNAL_ONLY=true. Skipping internal tests."
    if [ $ERRORS -gt 0 ]; then
        exit 1
    fi
    exit 0
fi

echo "--- 2. Testing Internal Unauthenticated Access (Port-Forward Bypass) ---"
echo "Port-forwarding to Grafana to test internal unauthenticated access..."

PF_LOG=$(mktemp)
set +e
kubectl -n "$NAMESPACE" port-forward svc/grafana 13000:80 >"$PF_LOG" 2>&1 &
PF_PID=$!
set -e

cleanup() {
  kill "$PF_PID" 2>/dev/null || true
  wait "$PF_PID" 2>/dev/null || true
  rm -f "$PF_LOG"
}
trap cleanup EXIT

# Readiness loop
ready=false
for _ in $(seq 1 30); do
  if curl -fsS \
    --config /dev/null \
    --max-time 2 \
    "$GRAFANA_LOCAL_URL/api/health" \
    >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done

if [ "$ready" = false ]; then
    echo "QUERY_ERROR: Failed to port-forward to Grafana."
    cat "$PF_LOG"
    ERRORS+=1
else
    function check_internal_auth() {
        local path=$1
        local expected=$2
        local result
        
        result=$(curl \
          --config /dev/null \
          --silent \
          --show-error \
          --cookie '' \
          --header 'Authorization:' \
          --header 'Accept: application/json' \
          --connect-timeout 5 \
          --max-time 15 \
          --output /dev/null \
          --write-out '%{http_code}' \
          "$GRAFANA_LOCAL_URL$path")
          
        echo "Internal API Status for $path: $result"
        
        if [[ "$expected" == *"or"* ]]; then
            local exp1=$(echo "$expected" | awk '{print $1}')
            local exp2=$(echo "$expected" | awk '{print $3}')
            if [[ "$result" == "$exp1" ]] || [[ "$result" == "$exp2" ]]; then
                echo "PASS: $path matched expected ($expected)"
            else
                echo "FAIL: $path returned $result, expected $expected"
                ERRORS+=1
            fi
        else
            if [[ "$result" == "$expected" ]]; then
                echo "PASS: $path matched expected ($expected)"
            else
                echo "FAIL: $path returned $result, expected $expected"
                ERRORS+=1
            fi
        fi
    }

    check_internal_auth "/api/health" "200"
    check_internal_auth "/api/user" "401"
    check_internal_auth "/api/org/users" "401 or 403"
    check_internal_auth "/api/admin/settings" "401 or 403"
    check_internal_auth "/login" "200"
fi

echo "--- 3. Testing Kubernetes ServiceAccount RBAC (S1) ---"
set +e
GRAFANA_SA="$(kubectl -n "$NAMESPACE" get deploy grafana -o jsonpath='{.spec.template.spec.serviceAccountName}' 2>/dev/null)"
DEPLOY_EXIT=$?
set -e

if [ $DEPLOY_EXIT -ne 0 ]; then
    echo "QUERY_ERROR: Failed to query Grafana Deployment for ServiceAccount."
    GRAFANA_SA="QUERY_ERROR"
    ERRORS+=1
elif [ -z "$GRAFANA_SA" ]; then
    GRAFANA_SA="default"
fi

if [ "$GRAFANA_SA" != "QUERY_ERROR" ]; then
    echo "Checking RBAC for ServiceAccount: $GRAFANA_SA"
    for verb in get list watch; do
        # Namespace local
        set +e
        can_i_ns=$(kubectl auth can-i \
          --as="system:serviceaccount:${NAMESPACE}:${GRAFANA_SA}" \
          "$verb" secrets \
          -n "$NAMESPACE" 2>/dev/null)
        ns_exit=$?
        set -e
        
        if [ $ns_exit -eq 0 ] && [ "$can_i_ns" = "yes" ]; then
            can_i_ns="yes"
        elif [ $ns_exit -eq 1 ] && [[ "$can_i_ns" == "no"* ]]; then
            can_i_ns="no"
        else
            can_i_ns="QUERY_ERROR"
        fi
          
        # All namespaces (cluster-scoped)
        set +e
        can_i_all=$(kubectl auth can-i \
          --as="system:serviceaccount:${NAMESPACE}:${GRAFANA_SA}" \
          "$verb" secrets \
          --all-namespaces 2>/dev/null)
        all_exit=$?
        set -e
        
        if [ $all_exit -eq 0 ] && [ "$can_i_all" = "yes" ]; then
            can_i_all="yes"
        elif [ $all_exit -eq 1 ] && [[ "$can_i_all" == "no"* ]]; then
            can_i_all="no"
        else
            can_i_all="QUERY_ERROR"
        fi
        
        echo "Verb: $verb, Namespace Local: $can_i_ns, All Namespaces: $can_i_all"
        if [ "$can_i_ns" = "QUERY_ERROR" ] || [ "$can_i_all" = "QUERY_ERROR" ]; then
            echo "FAIL: QUERY_ERROR querying RBAC."
            ERRORS+=1
        elif [ "$can_i_all" = "yes" ]; then
            echo "FAIL: OVERPRIVILEGED_CLUSTER_SECRET_ACCESS. Cluster-wide $verb secrets permission is yes! S1 risk."
            ERRORS+=1
        elif [ "$can_i_ns" = "yes" ]; then
            echo "WARNING: NAMESPACE_SECRET_ACCESS. Namespace-local $verb secrets permission is yes. Need justification."
        fi
    done
fi


echo "--- 4. Verify flagd-ui absence ---"
set +e
PODS_JSON=$(kubectl -n "$NAMESPACE" get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{range .spec.containers[*]}{"  "}{.name}{"\t"}{.image}{"\n"}{end}{range .spec.initContainers[*]}{"  "}{.name}{"\t"}{.image}{"\n"}{end}{end}' 2>/dev/null)
PODS_EXIT=$?
set -e

if [ $PODS_EXIT -ne 0 ]; then
    echo "FAIL: QUERY_ERROR querying pods for flagd-ui."
    ERRORS+=1
else
    FLAGD_CONTAINERS=$(echo "$PODS_JSON" | grep -E 'flagd-ui' || true)
    if [ -n "$FLAGD_CONTAINERS" ]; then
        echo "FAIL: flagd-ui container(s) found in production!"
        echo "$FLAGD_CONTAINERS"
        ERRORS+=1
    else
        echo "PASS: flagd-ui is NOT running."
    fi
fi

if [ $ERRORS -gt 0 ]; then
    echo "VERIFICATION FAILED WITH $ERRORS ERRORS."
    exit 1
fi

echo "ALL RUNTIME VERIFICATIONS COMPLETED SUCCESSFULLY."
exit 0
