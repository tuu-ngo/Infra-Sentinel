#!/usr/bin/env bash
set -euo pipefail

echo "Running SEC - Observability Authentication Static Regression Tests"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="${REPO_ROOT}/phase3 - information"
ES_PATH="${REPO_ROOT}/gitops/secrets/grafana-admin-credentials.yaml"

# Check dependencies (FAIL-CLOSED)
if ! command -v helm &> /dev/null; then
    echo "ERROR: helm is not installed. Static tests cannot run."
    exit 1
fi

if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "ERROR: Python is not installed. Needed for robust YAML parsing."
    exit 1
fi

RENDER_OUT=$(mktemp)
NEGATIVE_OUT_ADMIN=$(mktemp)
NEGATIVE_OUT_EDITOR=$(mktemp)
NEGATIVE_OUT_LOGIN_DISABLED=$(mktemp)
ES_NEG_MISSING="nonexistent-file.yaml"
ES_NEG_NAMESPACE=$(mktemp)
ES_NEG_NO_PASS=$(mktemp)

VALIDATOR=$(mktemp)
trap 'rm -f "$RENDER_OUT" "$NEGATIVE_OUT_ADMIN" "$NEGATIVE_OUT_EDITOR" "$NEGATIVE_OUT_LOGIN_DISABLED" "$ES_NEG_NAMESPACE" "$ES_NEG_NO_PASS" "$VALIDATOR"' EXIT

cat << 'EOF' > "$VALIDATOR"
import sys, yaml
import configparser
import re
import os

def pod_spec(doc):
    if doc.get("kind") == "Pod":
        return doc.get("spec", {})
    return (
        doc.get("spec", {})
           .get("template", {})
           .get("spec", {})
    )

def main():
    if len(sys.argv) < 3:
        print("FAIL: Validator requires 2 arguments: rendered_helm_path and external_secret_path")
        sys.exit(1)

    helm_path = sys.argv[1]
    es_path = sys.argv[2]

    # Validate ExternalSecret
    if not os.path.isfile(es_path):
        print("FAIL: ExternalSecret file not found")
        sys.exit(1)

    try:
        with open(es_path, encoding='utf-8') as f:
            es_docs = list(yaml.safe_load_all(f))
            es_doc = es_docs[0] if es_docs else None
    except Exception as e:
        print(f"FAIL: could not parse ES YAML: {e}")
        sys.exit(1)

    if not es_doc:
        print("FAIL: ExternalSecret file empty")
        sys.exit(1)
    
    if es_doc.get('apiVersion') != 'external-secrets.io/v1':
        print("FAIL: apiVersion != external-secrets.io/v1")
        sys.exit(1)
    if es_doc.get('kind') != 'ExternalSecret':
        print("FAIL: kind != ExternalSecret")
        sys.exit(1)
    if es_doc.get('metadata', {}).get('namespace') != 'techx-tf3':
        print("FAIL: metadata.namespace != techx-tf3")
        sys.exit(1)
        
    spec = es_doc.get('spec', {})
    store_ref = spec.get('secretStoreRef', {})
    if store_ref.get('kind') != 'ClusterSecretStore':
        print("FAIL: spec.secretStoreRef.kind != ClusterSecretStore")
        sys.exit(1)
    if store_ref.get('name') != 'aws-secrets-manager':
        print("FAIL: spec.secretStoreRef.name != aws-secrets-manager")
        sys.exit(1)
        
    target = spec.get('target', {})
    if target.get('name') != 'grafana-admin-credentials':
        print("FAIL: spec.target.name != grafana-admin-credentials")
        sys.exit(1)
    if target.get('creationPolicy') != 'Owner':
        print("FAIL: spec.target.creationPolicy != Owner")
        sys.exit(1)
    if target.get('deletionPolicy') != 'Retain':
        print("FAIL: spec.target.deletionPolicy != Retain")
        sys.exit(1)

    if 'template' in target and 'data' in target['template']:
        print("FAIL: spec.target.template.data found")
        sys.exit(1)
    if 'data' in spec and isinstance(spec['data'], dict): # data dictionary literal
        print("FAIL: literal spec.data dictionary found")
        sys.exit(1)
    if 'stringData' in spec:
        print("FAIL: stringData literal found")
        sys.exit(1)
        
    data_entries = spec.get('data', [])
    if not isinstance(data_entries, list) or len(data_entries) != 2:
        print("FAIL: spec.data does not contain exactly two entries")
        sys.exit(1)
        
    has_user = False
    has_pass = False
    for entry in data_entries:
        sk = entry.get('secretKey')
        rr = entry.get('remoteRef', {})
        if not rr.get('property'):
            print("FAIL: remoteRef missing property")
            sys.exit(1)
        if rr.get('key') != 'techx-corp-tf3/grafana-admin-credentials':
            print("FAIL: wrong remote key")
            sys.exit(1)
        
        if sk == 'admin-user' and rr.get('property') == 'admin-user':
            has_user = True
        if sk == 'admin-password' and rr.get('property') == 'admin-password':
            has_pass = True
    
    if not has_user or not has_pass:
        print("FAIL: spec.data does not contain admin-user and admin-password remoteRefs correctly")
        sys.exit(1)

    # Validate Helm Render
    try:
        with open(helm_path, encoding='utf-8') as f:
            docs = list(yaml.safe_load_all(f))
    except Exception as e:
        print(f"FAIL: could not parse HELM YAML: {e}")
        sys.exit(1)

    cm = next((d for d in docs if d and d.get('kind') == 'ConfigMap' and d['metadata']['name'] == 'grafana'), None)
    deploy = next((d for d in docs if d and d.get('kind') == 'Deployment' and d['metadata']['name'] == 'grafana'), None)
    
    if not cm:
        print("FAIL: no Grafana ConfigMap is found")
        sys.exit(1)
    if not deploy:
        print("FAIL: no Grafana Deployment is found")
        sys.exit(1)

    ini_str = cm.get('data', {}).get('grafana.ini')
    if not ini_str:
        print("FAIL: no grafana.ini key is found")
        sys.exit(1)

    config = configparser.ConfigParser()
    try:
        config.read_string(ini_str)
    except Exception as e:
        print(f"FAIL: INI sections cannot be parsed: {e}")
        sys.exit(1)

    try:
        anon_enabled = config.get('auth.anonymous', 'enabled', fallback='false').lower()
        org_role = config.get('auth.anonymous', 'org_role', fallback='Viewer')
        disable_login_form = config.get('auth', 'disable_login_form', fallback='false').lower()
    except Exception as e:
        print(f"FAIL: Error reading INI keys: {e}")
        sys.exit(1)

    if disable_login_form == 'true':
        print(f"FAIL: disable_login_form is true")
        sys.exit(1)
    if anon_enabled == 'true':
        print(f"FAIL: auth.anonymous.enabled is true")
        sys.exit(1)
    if org_role in ['Admin', 'Editor']:
        print(f"FAIL: org_role is {org_role}")
        sys.exit(1)

    # Check Secret refs
    containers = deploy.get('spec', {}).get('template', {}).get('spec', {}).get('containers', [])
    grafana_container = next((c for c in containers if c['name'] == 'grafana'), None)
    if not grafana_container:
        print("FAIL: grafana container not found in deployment")
        sys.exit(1)

    has_admin_user_secret = False
    has_admin_pass_secret = False
    
    for env in grafana_container.get('env', []):
        if env['name'] == 'GF_SECURITY_ADMIN_USER':
            sr = env.get('valueFrom', {}).get('secretKeyRef', {})
            if sr.get('name') == 'grafana-admin-credentials' and sr.get('key') == 'admin-user':
                has_admin_user_secret = True
            else:
                print(f"FAIL: Secret name differs unexpectedly for admin-user: {sr}")
                sys.exit(1)
        if env['name'] == 'GF_SECURITY_ADMIN_PASSWORD':
            if 'valueFrom' not in env and 'value' in env:
                print("FAIL: literal admin password is rendered")
                sys.exit(1)
            sr = env.get('valueFrom', {}).get('secretKeyRef', {})
            if sr.get('name') == 'grafana-admin-credentials' and sr.get('key') == 'admin-password':
                has_admin_pass_secret = True
            else:
                print(f"FAIL: Secret name differs unexpectedly for admin-password: {sr}")
                sys.exit(1)

    if not has_admin_user_secret or not has_admin_pass_secret:
        print("FAIL: either key is absent in env mapping")
        sys.exit(1)

    # Check chart generated secret
    secret = next((d for d in docs if d and d.get('kind') == 'Secret' and d['metadata']['name'] == 'grafana'), None)
    if secret:
        import base64
        data = secret.get('data', {})
        admin_pass = data.get('admin-password', '')
        if admin_pass:
            try:
                decoded = base64.b64decode(admin_pass).decode('utf-8')
                if decoded == 'admin':
                    print("FAIL: chart-generated Secret contains admin as the password")
                    sys.exit(1)
            except:
                pass

    # flagd-ui static absence
    for doc in docs:
        if not doc: continue
        
        spec = pod_spec(doc)
        if spec:
            conts = spec.get("containers", []) + spec.get("initContainers", [])
            for c in conts:
                if c.get('name') == 'flagd-ui':
                    print("FAIL: container name: flagd-ui found")
                    sys.exit(1)
                for port in c.get('ports', []):
                    if port.get('containerPort') == 4000:
                        print("FAIL: containerPort: 4000 found")
                        sys.exit(1)
                for env in c.get('env', []):
                    if env.get('name') == 'SECRET_KEY_BASE':
                        print("FAIL: SECRET_KEY_BASE found")
                        sys.exit(1)
        
        if doc.get('kind') == 'ConfigMap' and doc['metadata']['name'] == 'frontend-proxy-config':
            envoy_yaml = doc.get('data', {}).get('envoy.yaml', '')
            if re.search(r'prefix:\s*["\']?/(feature|flagd-ui)\b', envoy_yaml):
                print("FAIL: active /feature or /flagd-ui route")
                sys.exit(1)

    print("PASS: valid render")
    sys.exit(0)

if __name__ == '__main__':
    main()
EOF

python_cmd="python3"
if ! command -v python3 &> /dev/null; then python_cmd="python"; fi

validate_render() {
  local rendered="$1"
  local es="$2"
  $python_cmd "$VALIDATOR" "$rendered" "$es"
}

echo "Building Helm dependencies..."
helm dependency build "${WORK_DIR}/techx-corp-chart" >/dev/null

echo "Rendering Helm template for PRODUCTION..."
helm template techx-corp "${WORK_DIR}/techx-corp-chart" \
  --namespace techx-tf3 \
  -f "${WORK_DIR}/techx-corp-chart/values.yaml" \
  -f "${WORK_DIR}/deploy/values-flagd-sync.yaml" \
  -f "${WORK_DIR}/deploy/values-prod.yaml" > "$RENDER_OUT" || {
    echo "ERROR: Helm template rendering failed."
    exit 1
}

echo "Generating temporary NEGATIVE fixtures (testing fail-closed logic)..."

helm template techx-corp "${WORK_DIR}/techx-corp-chart" \
  --namespace techx-tf3 \
  -f "${WORK_DIR}/techx-corp-chart/values.yaml" \
  -f "${WORK_DIR}/deploy/values-flagd-sync.yaml" \
  -f "${WORK_DIR}/deploy/values-prod.yaml" \
  --set grafana.grafana\\.ini.auth\\.anonymous.enabled=true \
  --set grafana.grafana\\.ini.auth\\.anonymous.org_role=Admin > "$NEGATIVE_OUT_ADMIN" 2>/dev/null || true

helm template techx-corp "${WORK_DIR}/techx-corp-chart" \
  --namespace techx-tf3 \
  -f "${WORK_DIR}/techx-corp-chart/values.yaml" \
  -f "${WORK_DIR}/deploy/values-flagd-sync.yaml" \
  -f "${WORK_DIR}/deploy/values-prod.yaml" \
  --set grafana.grafana\\.ini.auth\\.anonymous.enabled=true \
  --set grafana.grafana\\.ini.auth\\.anonymous.org_role=Editor > "$NEGATIVE_OUT_EDITOR" 2>/dev/null || true

helm template techx-corp "${WORK_DIR}/techx-corp-chart" \
  --namespace techx-tf3 \
  -f "${WORK_DIR}/techx-corp-chart/values.yaml" \
  -f "${WORK_DIR}/deploy/values-flagd-sync.yaml" \
  -f "${WORK_DIR}/deploy/values-prod.yaml" \
  --set grafana.grafana\\.ini.auth.disable_login_form=true \
  --set grafana.grafana\\.ini.auth\\.anonymous.enabled=false > "$NEGATIVE_OUT_LOGIN_DISABLED" 2>/dev/null || true

# ExternalSecret negative fixtures
sed 's/namespace: techx-tf3/namespace: techx-tf4/' "$ES_PATH" > "$ES_NEG_NAMESPACE"
sed '/secretKey: admin-password/,+4d' "$ES_PATH" > "$ES_NEG_NO_PASS"

echo "Testing negative fixture (Admin)..."
if validate_render "$NEGATIVE_OUT_ADMIN" "$ES_PATH"; then
  echo "FAIL: insecure anonymous Admin fixture was accepted" >&2
  exit 1
fi
echo "PASS: insecure anonymous Admin fixture was rejected"

echo "Testing negative fixture (Editor)..."
if validate_render "$NEGATIVE_OUT_EDITOR" "$ES_PATH"; then
  echo "FAIL: insecure anonymous Editor fixture was accepted" >&2
  exit 1
fi
echo "PASS: insecure anonymous Editor fixture was rejected"

echo "Testing negative fixture (Login Disabled)..."
if validate_render "$NEGATIVE_OUT_LOGIN_DISABLED" "$ES_PATH"; then
  echo "FAIL: insecure login disabled fixture was accepted" >&2
  exit 1
fi
echo "PASS: insecure login disabled fixture was rejected"

echo "Testing negative fixture (ES Missing)..."
if validate_render "$RENDER_OUT" "$ES_NEG_MISSING"; then
  echo "FAIL: missing ES file was accepted" >&2
  exit 1
fi
echo "PASS: missing ES file was rejected"

echo "Testing negative fixture (ES Wrong Namespace)..."
if validate_render "$RENDER_OUT" "$ES_NEG_NAMESPACE"; then
  echo "FAIL: ES wrong namespace was accepted" >&2
  exit 1
fi
echo "PASS: ES wrong namespace was rejected"

echo "Testing negative fixture (ES Missing Password Ref)..."
if validate_render "$RENDER_OUT" "$ES_NEG_NO_PASS"; then
  echo "FAIL: ES missing admin-password ref was accepted" >&2
  exit 1
fi
echo "PASS: ES missing admin-password ref was rejected"

echo "Testing positive production render..."
if ! validate_render "$RENDER_OUT" "$ES_PATH"; then
    echo "FAIL: positive render failed"
    exit 1
fi

echo "Testing Plaintext Admin Credentials via git grep..."
if git grep -n -I -E 'adminPassword:[[:space:]]*admin|admin-password:[[:space:]]*[^${[:space:]]' -- 'phase3 - information/' 'gitops/'; then
    echo "FAIL: Plaintext admin credential found in repository!"
    exit 1
fi

echo "PASS: All static observability security constraints verified successfully."
exit 0
