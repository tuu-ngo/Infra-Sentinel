# Mandate 17 manual NetworkPolicy test scenarios

This is the manual handoff matrix for the authorized tester. Run the common
checks before and after each GitOps promotion. Record the result, command
output, tester, timestamp, and evidence location for every row.

ALLOW means the connection must succeed after the policy is active. DENY means
the connection must time out after the policy is active. An immediate
connection refusal does not prove NetworkPolicy enforcement.

## Common checks

~~~bash
kubectl auth can-i create pods/exec -n techx-tf3
kubectl -n argocd get application techx-infrastructure-app techx-corp
kubectl -n techx-tf3 get pods -o wide
kubectl -n techx-tf3 get events --sort-by=.lastTimestamp | tail -40
kubectl -n techx-tf3 get networkpolicies
kubectl -n techx-tf3 get policyendpoints.networking.k8s.aws
curl -fsS -o /dev/null -w 'storefront=%{http_code} total=%{time_total}s\n' \
  https://d2tn71186d7ilz.cloudfront.net/
~~~

Expected common result: pods/exec is yes, Argo is Synced/Healthy, pods are
Ready, no new abnormal events exist, PolicyEndpoints are present, and
storefront returns HTTP 200.

Use the existing Deployment-owned workload pods for these checks. If a
dedicated attacker probe is required because an application image has no
network test tool, it must be introduced as a temporary GitOps-managed
Deployment with ReplicaSet/Deployment ownerReferences and an approved image.
A bare Pod is not valid AWS VPC CNI enforcement evidence.

## Business service matrix

| Policy | Source | Destination | Port | Expected | Reason |
|---|---|---|---:|---|---|
| 10-quote | shipping | quote | 8080 | ALLOW | Real checkout quote path |
| 10-quote | frontend | quote | 8080 | DENY | No direct frontend quote dependency |
| 10-quote | quote | otel-gateway | 4318 | ALLOW | Telemetry |
| 10-quote | quote | payment | 8080 | DENY | Unapproved east-west access |
| 11-currency | frontend | currency | 8080 | ALLOW | Browse conversion |
| 11-currency | checkout | currency | 8080 | ALLOW | Checkout conversion |
| 11-currency | cart | currency | 8080 | DENY | Unapproved access |
| 11-currency | currency | payment | 8080 | DENY | Unapproved egress |
| 12-payment | checkout | payment | 8080 | ALLOW | Required money path |
| 12-payment | cart | payment | 8080 | DENY | Lateral movement |
| 12-payment | payment | flagd | 8013 | ALLOW | Runtime flag read |
| 12-payment | payment | otel-gateway | 4317 | ALLOW | Telemetry |
| 12-payment | payment | cart | 8080 | DENY | Unapproved reverse call |
| 13-email | checkout | email | 8080 | ALLOW | Order notification |
| 13-email | cart | email | 8080 | DENY | Unapproved access |
| 13-email | email | flagd | 8013 | ALLOW | Runtime flag read |
| 14-ad | frontend | ad | 8080 | ALLOW | Advertisement request |
| 14-ad | checkout | ad | 8080 | DENY | Unapproved access |
| 14-ad | ad | flagd | 8013 | ALLOW | Runtime flag read |
| 15-image-provider | frontend-proxy | image-provider | 8081 | ALLOW | Image route |
| 15-image-provider | frontend | image-provider | 8081 | DENY | Must use proxy |
| 16-llm | product-reviews | llm | 8080 | DENY | Production uses Bedrock |
| 16-llm | llm | flagd | 8013 | ALLOW | Runtime flag read |
| 20-product-catalog | frontend | product-catalog | 8080 | ALLOW | Browse products |
| 20-product-catalog | checkout | product-catalog | 8080 | ALLOW | Product lookup |
| 20-product-catalog | cart | product-catalog | 8080 | DENY | Unapproved access |
| 21-cart | frontend | cart | 8080 | ALLOW | Add/read cart |
| 21-cart | checkout | cart | 8080 | ALLOW | Checkout cart access |
| 21-cart | accounting | cart | 8080 | DENY | Unapproved access |
| 21-cart | cart | payment | 8080 | DENY | Lateral movement |
| 22-accounting | accounting | otel-gateway | 4318 | ALLOW | Telemetry |
| 22-accounting | accounting | payment | 8080 | DENY | Unapproved egress |
| 23-fraud-detection | fraud-detection | flagd | 8013 | ALLOW | Runtime flag read |
| 23-fraud-detection | fraud-detection | otel-gateway | 4318 | ALLOW | Telemetry |
| 23-fraud-detection | fraud-detection | payment | 8080 | DENY | Unapproved egress |
| 30-shipping | checkout | shipping | 8080 | ALLOW | Checkout shipping |
| 30-shipping | shipping | quote | 8080 | ALLOW | Real quote path |
| 30-shipping | cart | shipping | 8080 | DENY | Unapproved access |
| 31-recommendation | frontend | recommendation | 8080 | ALLOW | Recommendation |
| 31-recommendation | recommendation | product-catalog | 8080 | ALLOW | Catalog lookup |
| 31-recommendation | checkout | recommendation | 8080 | DENY | Unapproved access |
| 32-product-reviews | frontend | product-reviews | 3551 | ALLOW | Reviews |
| 32-product-reviews | shopping-copilot | product-reviews | 3551 | ALLOW | Copilot review lookup |
| 32-product-reviews | checkout | product-reviews | 3551 | DENY | Unapproved access |
| 32-product-reviews | product-reviews | product-catalog | 8080 | ALLOW | Catalog lookup |
| 32-product-reviews | product-reviews | flagd | 8013 | ALLOW | Runtime flag read |
| 32-product-reviews | product-reviews | otel-gateway | 4317 | ALLOW | Telemetry |
| 32-product-reviews | product-reviews | RDS PostgreSQL | 5432 | ALLOW | Review datastore |
| 32-product-reviews | product-reviews | ElastiCache Valkey | 6379 | ALLOW | Guardrail cache |
| 32-product-reviews | product-reviews | Bedrock | 443 | ALLOW | Approved HTTPS exception |

## Checkout and payment scenario

### Checkout policy: 33-checkout

| Source | Destination | Port | Expected | Reason |
|---|---|---:|---|---|
| frontend | checkout | 8080 | ALLOW | Checkout entry |
| cart | checkout | 8080 | DENY | Unapproved checkout ingress |
| checkout | cart | 8080 | ALLOW | Cart dependency |
| checkout | currency | 8080 | ALLOW | Currency dependency |
| checkout | email | 8080 | ALLOW | Email dependency |
| checkout | payment | 8080 | ALLOW | Required money path |
| checkout | product-catalog | 8080 | ALLOW | Product lookup |
| checkout | shipping | 8080 | ALLOW | Shipping dependency |
| checkout | quote | 8080 | DENY | Quote is reached through shipping |
| checkout | public Internet | 443 | DENY | Business Internet egress is blocked |

~~~bash
# Required money path: ALLOW
kubectl exec -n techx-tf3 deploy/checkout -- nc -z -v -w 5 payment 8080

# Lateral movement: DENY
kubectl exec -n techx-tf3 deploy/cart -- nc -z -v -w 5 payment 8080

# Real quote path: shipping ALLOW, checkout direct quote DENY
kubectl exec -n techx-tf3 deploy/shipping -- nc -z -v -w 5 quote 8080
kubectl exec -n techx-tf3 deploy/checkout -- nc -z -v -w 5 quote 8080
~~~

For checkout, also test ALLOW to cart, currency, email, product-catalog, and
shipping. Complete one real browse -> add-to-cart -> checkout transaction.

## Frontend, proxy, and flagd

| Policy | Source | Destination | Port | Expected | Reason |
|---|---|---|---:|---|---|
| 34-frontend | frontend-proxy | frontend | 8080 | ALLOW | Storefront entry |
| 34-frontend | frontend | cart | 8080 | ALLOW | Cart route |
| 34-frontend | frontend | checkout | 8080 | ALLOW | Checkout route |
| 34-frontend | frontend | product-catalog | 8080 | ALLOW | Browse route |
| 34-frontend | cart | frontend | 8080 | DENY | Unapproved reverse call |
| 34-frontend | frontend | payment | 8080 | DENY | Payment goes through checkout |
| 35-frontend-proxy | load-generator | frontend-proxy | 8080 | ALLOW | Approved caller |
| 35-frontend-proxy | frontend-proxy | frontend | 8080 | ALLOW | Application route |
| 35-frontend-proxy | frontend-proxy | image-provider | 8081 | ALLOW | Image route |
| 35-frontend-proxy | frontend-proxy | flagd | 8013 | ALLOW | /flagservice |
| 35-frontend-proxy | frontend-proxy | flagd | 4000 | ALLOW | Flag UI |
| 35-frontend-proxy | frontend-proxy | payment | 8080 | DENY | Unapproved egress |
| 40-flagd | checkout | flagd | 8013 | ALLOW | Runtime flag channel |
| 40-flagd | shipping | flagd | 8013 | DENY | No shipping dependency |
| 40-flagd | flagd | 122.248.223.194 | 443 | ALLOW | Exact sync source |
| 40-flagd | flagd | payment | 8080 | DENY | Unapproved egress |

Do not remove, bypass, or repoint /flagservice during this test.

## Platform and egress matrix

| Policy | Source | Destination | Port | Expected |
|---|---|---|---:|---|
| 00-otel-gateway | checkout | otel-gateway | 4317 | ALLOW |
| 00-otel-gateway | otel-gateway | jaeger | 4317 | ALLOW |
| 00-otel-gateway | otel-gateway | prometheus | 9090 | ALLOW |
| 00-otel-gateway | otel-gateway | opensearch | 9200 | ALLOW |
| 00-otel-gateway | otel-gateway | payment | 8080 | DENY |
| 01-grafana | grafana | prometheus | 9090 | ALLOW |
| 01-grafana | grafana | jaeger | 16686 | ALLOW |
| 01-grafana | grafana | opensearch | 9200 | ALLOW |
| 01-grafana | grafana | payment | 8080 | DENY |
| 02-jaeger | jaeger | prometheus | 9090 | ALLOW |
| 02-jaeger | jaeger | otel-gateway | 4318 | ALLOW |
| 02-jaeger | jaeger | payment | 8080 | DENY |
| 03-prometheus | prometheus | kubernetes.default.svc | 443 | ALLOW |
| 03-prometheus | prometheus | payment | 8080 | DENY |
| 04-opensearch | opensearch | kube-dns.kube-system.svc.cluster.local | 53 | ALLOW |
| 04-opensearch | opensearch | payment | 8080 | DENY |
| 05-load-generator | load-generator | frontend-proxy | 8080 | ALLOW |
| 05-load-generator | load-generator | flagd | 8013 | ALLOW |
| 05-load-generator | load-generator | payment | 8080 | DENY |
| 06-cloudflared | cloudflared | frontend-proxy | 8080 | ALLOW |
| 06-cloudflared | cloudflared | grafana | 3000 | ALLOW |
| 06-cloudflared | cloudflared | jaeger | 16686 | ALLOW |
| 06-cloudflared | cloudflared | Cloudflare | 443/7844 | ALLOW |
| 06-cloudflared | cloudflared | payment | 8080 | DENY |
| 07-aiops-engine | aiops-engine | prometheus | 9090 | ALLOW |
| 07-aiops-engine | aiops-engine | jaeger | 16686 | ALLOW |
| 07-aiops-engine | aiops-engine | opensearch | 9200 | ALLOW |
| 07-aiops-engine | aiops-engine | Slack webhook | 443 | ALLOW |
| 07-aiops-engine | aiops-engine | payment | 8080 | DENY |

## Final default-deny acceptance

Run after all allow policies and 90-default-deny-all.yaml are active:

~~~bash
kubectl exec -n techx-tf3 deploy/cart -- nc -z -v -w 5 payment 8080
kubectl exec -n techx-tf3 deploy/cart -- curl -I -L --connect-timeout 5 https://example.com
kubectl exec -n techx-tf3 deploy/product-reviews -- \
  curl -I --connect-timeout 5 \
  https://bedrock-runtime.us-east-1.amazonaws.com
~~~

The first two must time out. Bedrock must return an HTTP response; 403/404 is
acceptable network evidence. Finish with storefront 200, browse, cart,
checkout, Argo Synced/Healthy, and confirmation that /flagservice is unchanged.
