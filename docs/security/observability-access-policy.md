# Observability Access Policy

## 1. Goal
To ensure that all internal operational and observability interfaces remain secure by default and prevent unauthorized data exfiltration or administrative access.

## 2. Grafana Access
- **Anonymous Access:** Anonymous access MUST be disabled (`auth.anonymous.enabled: false`) in production unless specifically justified for a public dashboard. If enabled for public dashboards, the `org_role` MUST be strictly limited to `Viewer`. Under no circumstances may an unauthenticated user receive `Editor` or `Admin` roles.
- **Admin Authentication:** The `disable_login_form` setting MUST be `false` if basic authentication is used. Admin credentials must be dynamically injected via a secure SecretStore (e.g., AWS Secrets Manager -> `ExternalSecret`). Plaintext passwords in Git are strictly forbidden.

## 3. Jaeger and Prometheus
- **Exposure:** Jaeger UI/API and Prometheus UI/API MUST NEVER be exposed to the public internet unauthenticated.
- **Protection Mechanism:** These services must either be accessible only via internal Kubernetes networking (e.g., `kubectl port-forward` or internal VPN) or behind a strong identity-aware proxy (e.g., Cloudflare Access) that enforces mandatory employee authentication.

## 4. flagd-ui
- **Production Posture:** `flagd-ui` is an internal development utility and MUST NOT be deployed in the production environment.
- **Enforcement:** The production Helm template (`values-prod.yaml`) must never include the `flagd-ui` sidecar container or expose its routes. CI pipelines will enforce this constraint statically.
