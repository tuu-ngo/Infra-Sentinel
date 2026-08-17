# Mandate 17 staged NetworkPolicies

This directory contains the reviewed policy set, but it is intentionally not
active. `techx-infrastructure-app` uses Argo CD directory mode without
`directory.recurse`, so only YAML files placed directly in
`gitops/infrastructure/` are synchronized.

Do not enable this directory by setting `directory.recurse: true`. Promote one
file at a time to `gitops/infrastructure/` in the order below. Each promotion
must use a separate PR and a low-traffic change window.

## Design constraints

- Production uses Amazon VPC CNI network policy in `standard` mode.
- A previous rollout proved that selector-only egress through a ClusterIP can
  be dropped by this cluster. The staged service rules therefore use exact pod
  selectors first, and the `ad` canary must prove DNS, flagd, telemetry, and
  frontend-to-ad ClusterIP behavior on the current VPC CNI before any wider
  promotion. If selector-only traffic fails, stop and add read-only-audited
  Service ClusterIP `/32` peers to the canary in a follow-up PR; do not replace
  them with a broad VPC CIDR. Destination ingress policies still enforce the
  caller identity.
- Managed RDS, ElastiCache, and MSK endpoints live in the three production
  private subnets. Only their required ports are allowed.
- Standard NetworkPolicy cannot restrict HTTPS by FQDN. Public HTTPS is
  therefore isolated to dedicated proxy workloads with reviewed FQDN RBAC;
  business pods may reach only their proxy Service and cannot use
  `0.0.0.0/0` directly.
- `flagd` keeps its protected runtime read path and can synchronize only with
  the configured `122.248.223.194` HTTPS source. Nothing here changes or
  removes `/flagservice`.
- DNS is intended only for CoreDNS on TCP/UDP 53. The `ad` canary must prove
  that selector-only DNS works through the CoreDNS ClusterIP. If it does not,
  add the observed CoreDNS Service ClusterIP as an exact `/32`; never guess it
  or open a broad service/VPC CIDR.
- The failed first `ad` canary was rolled back in PR #432. A read-only cluster
  audit on 2026-07-25 observed `kube-dns=172.20.0.10`,
  `flagd=172.20.213.30`, and `otel-gateway=172.20.117.175`. The follow-up
  canary keeps the pod selectors for endpoint churn and adds only these Service
  ClusterIP `/32` peers. These values still require a fresh read-only check
  immediately before promotion; a changed Service ClusterIP blocks promotion.
- Production has no direct `checkout -> quote` client configuration. The real
  path is `checkout -> shipping -> quote`, so no unnecessary direct rule is
  opened.

## Product Reviews private-path rollout

This runtime PR depends on the Product Reviews Terraform endpoint PR being
merged and successfully applied first. It does not promote
`32-product-reviews.yaml`.

1. Confirm the `product-reviews-ai-private-path` Terraform apply completed and
   its endpoint, ENI IP, SSM, and IAM checks passed.
2. Merge this runtime PR during a low-traffic window. The production Deployment
   uses `RollingUpdate`, `maxUnavailable: 0`, so the old ReplicaSet remains
   available while new pods wait for the endpoint Secret.
3. Wait for `product-reviews-ai-endpoints` to become Ready, then verify the
   Product Reviews rollout, both private endpoint connections, Argo CD
   `Synced/Healthy`, storefront HTTP 200, and browse/cart/checkout.
4. Keep the legacy `us-east-1` model permission for rollback until the APAC
   runtime has completed its agreed soak window. Remove it in a cleanup PR.
5. Promote `32-product-reviews.yaml` only in a later policy PR after rechecking
   all six endpoint ENI addresses and passing the allowed/denied matrix.

If the secret handoff or runtime rollout fails, revert this Git commit so Argo
restores the previous workload specification. Do not patch the Deployment or
apply the NetworkPolicy manually.

## Active-policy replacement gate

Kubernetes NetworkPolicy rules are additive for every policy selecting a pod.
A narrow staged policy does not override a broader active policy. Before every
promotion, capture the active inventory and identify every policy whose
`podSelector` overlaps the workload being promoted:

```bash
mkdir -p outputs/mandate-17/pre-promotion
kubectl -n techx-tf3 get networkpolicies -o yaml \
  > outputs/mandate-17/pre-promotion/networkpolicies-before.yaml
kubectl -n techx-tf3 get networkpolicies \
  -o custom-columns=NAME:.metadata.name,POD-SELECTOR:.spec.podSelector
```

The promotion PR must include an inventory table with the active policy name,
GitOps source file, selected workload, overlapping ingress/egress permissions,
and one disposition: `retain`, `update-in-place`, or `replace`. Promotion is
blocked when an overlapping policy has no documented disposition or retains a
broader rule than the staged contract.

Prefer updating the existing GitOps manifest in place and preserving its
`metadata.name`. If replacement is unavoidable, remove the old manifest and
add the reviewed replacement through Git in the same promotion PR. Never use
`kubectl apply`, `patch`, `edit`, or `delete` to perform the replacement.
After Argo CD synchronizes, verify the intended object was updated and any
replaced object was pruned before accepting a negative connectivity test.

Jaeger is an explicit blocker: active policy `jaeger-access` currently permits
broader ingress than `02-jaeger.yaml`. Its promotion must update
`gitops/infrastructure/network-policy-jaeger.yaml` in place while preserving
the `jaeger-access` name, or document and verify an equivalent GitOps
replacement. Adding `jaeger-platform-policy` beside the old policy is not a
valid restriction because the old ingress allowance would remain effective.

## Promotion order

1. Pass the active-policy replacement gate, then capture pre-change pods,
   events, Argo health, storefront HTTP 200, SLO, and positive/negative
   connectivity evidence.
2. Promote only `14-ad.yaml` as the first canary. Verify frontend-to-ad, DNS,
   flagd, telemetry, an unrelated denied flow, readiness, storefront, and SLO.
3. Soak the canary for at least one stable SLO window. If selector-only traffic
   fails, stop and test exact Service ClusterIP `/32` peers in a new canary PR.
4. Promote the remaining leaf services one at a time: `quote`, `currency`,
   `email`, `image-provider`, `llm`, and then the money-path `payment` service.
5. Promote datastore clients one at a time: `accounting`, `fraud-detection`,
   `product-catalog`, and `cart`.
6. Promote downstream callers one at a time: `shipping`, `recommendation`, and
   `product-reviews`. Do not promote `product-reviews` while its
   `mandate-17.techx.io/promotion-blocked` annotation remains `true`.
7. Promote `checkout`, then `frontend`, then `frontend-proxy`, each in its own
   PR with a prepared revert commit.
8. Promote `flagd`, then platform policies one at a time. Audit whether AIOps
   calls the Kubernetes API before changing `07-aiops-engine.yaml`. Do not
   promote `cloudflared` or `aiops-engine` while promotion-blocked.
9. Promote `90-default-deny-all.yaml` in the final PR only after the full allow
   graph has passed its soak windows.

After every file is synchronized:

Use the read-only evidence script and follow its handoff runbook:

- [`mandate-17-connectivity-test.sh`](../../../scripts/network-policy/mandate-17-connectivity-test.sh)
- [`mandate-17-network-policy-connectivity-test.md`](../../../docs/runbooks/mandate-17-network-policy-connectivity-test.md)
- [`mandate-17-network-policy-test-scenarios.md`](../../../docs/runbooks/mandate-17-network-policy-test-scenarios.md)
- [`mandate-17-service-access-flow-scenario.md`](../../../docs/runbooks/mandate-17-service-access-flow-scenario.md)

```bash
kubectl -n argocd get application techx-infrastructure-app techx-corp
kubectl -n techx-tf3 get pods
kubectl -n techx-tf3 get events --sort-by=.lastTimestamp | tail -40
kubectl -n techx-tf3 get policyendpoints.networking.k8s.aws
curl -fsS -o /dev/null -w 'storefront=%{http_code} total=%{time_total}s\n' \
  https://d2tn71186d7ilz.cloudfront.net/
```

Run the browse, cart, and checkout smoke path. With temporary `pods/exec`
permission, also run one allowed dependency test and one unrelated-service
test from the newly isolated workload. The allowed call must succeed and the
unrelated call must time out.

Use existing Deployment-owned workload pods for connectivity checks. If a
dedicated attacker probe is required, define it as a temporary GitOps-managed
Deployment with ReplicaSet/Deployment `ownerReferences` and an approved image.
A bare Pod is not accepted as AWS VPC CNI enforcement evidence.

If any positive test, readiness check, SLO, or Argo health check regresses,
revert that promotion commit immediately and let Argo CD prune the policy.
Never repair the live object with `kubectl apply`, `patch`, `edit`, or `delete`.
Do not begin a promotion when the error budget is exhausted or another major
production change is running in parallel.

## Final acceptance tests

After `90-default-deny-all.yaml` is active:

```bash
# Unrelated east-west call: expected to time out.
kubectl -n techx-tf3 exec deploy/cart -- nc -vz -w 5 payment 8080

# Public internet from a business pod without an exception: expected to fail.
kubectl -n techx-tf3 exec deploy/cart -- \
  curl -I -L --connect-timeout 5 https://example.com

# Bedrock must work through the dedicated Product Reviews egress proxy.
kubectl -n techx-tf3 exec deploy/product-reviews -- \
  curl -I --connect-timeout 5 https://bedrock-runtime.us-east-1.amazonaws.com

# An authority outside the proxy allowlist must return CONNECT 403.
kubectl -n techx-tf3 exec deploy/product-reviews -- \
  curl -I --connect-timeout 5 https://example.com
```

An HTTP 403/404 from the Bedrock endpoint is sufficient network evidence; a
timeout is not. Capture command output, Argo `Synced/Healthy`, storefront 200,
and the browse/cart/checkout result as PR evidence.
