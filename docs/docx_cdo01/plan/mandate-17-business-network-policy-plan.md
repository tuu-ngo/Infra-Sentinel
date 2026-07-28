# Mandate 17 - Business NetworkPolicy rollout plan

Date: 2026-07-21

## Goal

Add NetworkPolicy containment for the 18 business services in namespace `techx-tf3`.

Done means:

- default-deny ingress + egress applies to business pods;
- allowed traffic is explicit by source pod, destination pod, and port;
- browse -> cart -> checkout still works and SLO does not degrade;
- lateral movement test fails, for example `cart` cannot call `payment:8080`;
- internet egress from business pods is blocked, except audited exceptions;
- no `/flagservice` or flagd runtime behavior is changed.

## Files To Add

Create the new policies under `gitops/infrastructure/`:

- `network-policy-business-default-deny.yaml`
- `network-policy-business-system-egress.yaml`
- `network-policy-business-frontend-proxy.yaml`
- `network-policy-business-frontend.yaml`
- `network-policy-business-checkout.yaml`
- `network-policy-business-services.yaml`

Keep existing datastore/observability policies as-is unless review finds a concrete missing allow rule.

## Review Rules

- Do not use direct `kubectl apply` for enforcement; rollout must go through GitOps/Argo CD.
- Use pod labels such as `app.kubernetes.io/component: <service>`.
- Use pod/container ports, not assumed Service ports.
- Every allow rule must have a reason.
- Allow DNS before enforcing egress deny.
- Allow `otel-collector:4317/4318` where the service exports telemetry.
- Allow `flagd:8013` where the service reads runtime flags.
- Do not change `/flagservice`, flagd config, flag values, or the runtime flag path.

## Allow Matrix

System egress for business pods:

- business pods -> kube-dns TCP/UDP 53
- business pods with OTEL env -> `otel-collector:4317` or `otel-collector:4318`
- business pods with FLAGD env -> `flagd:8013`

Entrypoint:

- ingress/source of production traffic -> `frontend-proxy:8080`
- `frontend-proxy` -> `frontend:8080`
- `frontend-proxy` -> `image-provider:8081`
- `frontend-proxy` -> `flagd:4000` only if flagd UI must remain reachable through the proxy

Frontend:

- `frontend` -> `product-catalog:8080`
- `frontend` -> `cart:8080`
- `frontend` -> `currency:8080`
- `frontend` -> `ad:8080`
- `frontend` -> `recommendation:8080`
- `frontend` -> `checkout:8080`
- `frontend` -> `shipping:8080`
- `frontend` -> `product-reviews:3551`
- `frontend` -> `flagd:8013`
- `frontend` -> `otel-collector:4317`

Checkout:

- `checkout` -> `cart:8080`
- `checkout` -> `product-catalog:8080`
- `checkout` -> `currency:8080`
- `checkout` -> `payment:8080`
- `checkout` -> `shipping:8080`
- `checkout` -> `quote:8080` only if verified in code/runtime
- `checkout` -> `email:8080`
- `checkout` -> `kafka:9092`
- `checkout` -> `flagd:8013`
- `checkout` -> `otel-collector:4317`

Business service ingress:

- `cart:8080` from `frontend`, `checkout`
- `product-catalog:8080` from `frontend`, `checkout`, `recommendation`, `product-reviews`
- `product-reviews:3551` from `frontend`
- `recommendation:8080` from `frontend`
- `shipping:8080` from `frontend`, `checkout`
- `quote:8080` from `shipping`, and from `checkout` only if verified
- `payment:8080` from `checkout`
- `email:8080` from `checkout`
- `ad:8080` from `frontend`
- `currency:8080` from `frontend`, `checkout`
- `llm:8000` from `product-reviews`

Datastore/event egress:

- `cart` -> `valkey-cart:6379`
- `product-catalog` -> `postgresql:5432`
- `product-reviews` -> `postgresql:5432`
- `accounting` -> `postgresql:5432`
- `checkout` -> `kafka:9092`
- `accounting` -> `kafka:9092`
- `fraud-detection` -> `kafka:9092`

External egress:

- Default: no business pod may call the internet.
- Before enforcing, audit whether `product-reviews` really calls AWS API/Bedrock/OpenAI.
- If an external exception is required, document the destination, port, reason, and evidence.

## Detailed Implementation Steps

1. Audit live labels, services, and current policies.

   What to do:

   - Capture pod labels:
     - `kubectl -n techx-tf3 get pods --show-labels`
   - Capture service ports:
     - `kubectl -n techx-tf3 get svc`
   - Capture endpoint mapping:
     - `kubectl -n techx-tf3 get endpoints`
   - Capture existing NetworkPolicy state:
     - `kubectl -n techx-tf3 get networkpolicy`
   - Confirm the real source of traffic into `frontend-proxy`.
   - Confirm whether `checkout -> quote:8080` is actually used.
   - Confirm whether `product-reviews` needs external egress to AWS API, Bedrock, OpenAI, or another external API.

   Expected output:

   - A final dependency matrix based on live labels and ports.
   - A list of any required external egress exceptions, or explicit confirmation that none are needed.

   Why:

   NetworkPolicy selectors are label-based. If the label or port is wrong, the policy can look correct in review but block production traffic after enforcement. This is exactly the class of failure seen in earlier NetworkPolicy incidents.

2. Draft allow policies before default-deny.

   What to do:

   - Create allow policies under `gitops/infrastructure/`.
   - Start with business ingress rules:
     - `frontend-proxy -> frontend`
     - `frontend -> product-catalog/cart/currency/ad/recommendation/checkout/shipping/product-reviews`
     - `checkout -> cart/product-catalog/currency/payment/shipping/email/kafka`
   - Add datastore/event rules:
     - `cart -> valkey-cart`
     - `product-catalog/product-reviews/accounting -> postgresql`
     - `checkout/accounting/fraud-detection -> kafka`
   - Add system egress:
     - DNS TCP/UDP 53
     - `otel-collector:4317/4318`
     - `flagd:8013`

   Expected output:

   - Policy files are ready in git.
   - Each rule has a narrow source, narrow destination, specific port, and clear reason.

   Why:

   Allow rules must exist before default-deny is enforced. Otherwise default-deny can immediately cut required app traffic and cause storefront or checkout failures.

3. Add default-deny baseline after allow rules are ready.

   What to do:

   - Add default-deny ingress and egress policy for business pods.
   - Scope the selector carefully to the 18 business services.
   - Do not accidentally select datastore, observability, Argo CD, or system pods unless intentionally reviewed.

   Expected output:

   - `network-policy-business-default-deny.yaml` exists.
   - The default-deny policy applies only to intended business pods.

   Why:

   Default-deny is the enforcement baseline for containment. Without it, missing allow rules do not matter because Kubernetes still allows traffic by default.

4. Validate manifests before Argo CD sync.

   What to do:

   - Run client dry-run:
     - `kubectl apply --dry-run=client -f gitops/infrastructure/network-policy-business-*.yaml`
   - If cluster access is available, run server dry-run:
     - `kubectl apply --dry-run=server -f gitops/infrastructure/network-policy-business-*.yaml`
   - Manually compare every `podSelector` and port with the audit output from step 1.

   Expected output:

   - Dry-run passes.
   - No selector is accidentally empty or too broad.
   - No allow rule uses the wrong port.

   Why:

   Dry-run catches schema and API errors before GitOps sync. Manual review catches semantic errors that Kubernetes cannot know, such as allowing the wrong component or using an app Service port when NetworkPolicy needs the pod port.

5. Roll out through GitOps in small phases.

   What to do:

   - Merge/sync the change through Argo CD, not by direct `kubectl apply`.
   - Prefer this order:
     - allow rules;
     - DNS/OTEL/flagd egress;
     - default-deny ingress;
     - default-deny egress.
   - After each phase, check:
     - Argo CD app is `Synced/Healthy`;
     - all business pods are Ready;
     - storefront returns HTTP 200;
     - browse product list works;
     - add-to-cart works;
     - checkout works;
     - Grafana/Jaeger still show fresh telemetry.

   Expected output:

   - Each phase has a timestamped verification result.
   - If anything fails, rollback is limited to the latest phase.

   Why:

   This avoids a risky big-bang NetworkPolicy rollout. It also follows the postmortem lesson: test after each layer, because missing telemetry/DNS/port rules can create indirect failures.

6. Run positive connectivity tests.

   What to do:

   - From app behavior:
     - browse -> cart -> checkout must pass.
   - From pods:
     - `cart -> valkey-cart:6379` must pass.
     - `checkout -> payment:8080` must pass.
     - `frontend -> product-catalog:8080` must pass.
     - `product-reviews -> llm:8000` must pass if product reviews AI path is enabled.

   Expected output:

   - Required business paths still work after policies are enforced.

   Why:

   Positive tests prove the policies are not only secure, but operationally safe. Mandate 17 still requires the money path to keep SLO.

7. Run negative containment tests.

   What to do:

   - Exec into a business pod or launch a temporary test pod with the same labels/service account pattern.
   - Verify unrelated internal access is blocked:
     - `cart -> payment:8080` must fail.
     - `cart -> postgresql:5432` must fail.
     - `frontend -> kafka:9092` must fail.
   - Verify internet egress is blocked:
     - `curl https://example.com` must fail.
     - `nc -vz 1.1.1.1 443` must fail.

   Expected output:

   - Lateral movement attempts fail.
   - Internet egress attempts fail unless a documented exception applies.

   Why:

   These are the tests mentors can repeat. They prove the policy actually contains a compromised pod instead of only documenting intended architecture.

8. Write evidence and PR notes.

   What to do:

   - Create `docs/evidence/mandate-17-business-network-policy-rollout.md`.
   - Include:
     - PR/commit IDs;
     - list of new policy files;
     - Argo CD `Synced/Healthy` evidence;
     - storefront HTTP 200 evidence;
     - browse/cart/checkout success evidence;
     - positive connectivity test logs;
     - negative containment test logs;
     - internet egress block logs;
     - explicit statement: `No /flagservice or flagd runtime behavior changed.`

   Expected output:

   - Evidence is reproducible and mentor-friendly.
   - Reviewers can match every DoD item to a command, screenshot, or log.

   Why:

   Mandate 17 is graded by what can be verified live. Evidence must show both safety and containment, not just that YAML files were added.

## Evidence To Submit

- New NetworkPolicy files in `gitops/infrastructure/`.
- Argo CD `Synced/Healthy` after rollout.
- Storefront 200 and browse/cart/checkout success.
- Negative test logs showing lateral movement blocked.
- Negative test logs showing internet egress blocked.
- PR note: `No /flagservice or flagd runtime behavior changed.`

## DoD Checklist

- [ ] Default-deny ingress applies to business pods.
- [ ] Default-deny egress applies to business pods.
- [ ] Explicit allow rules cover browse -> cart -> checkout.
- [ ] No broad internet egress remains for business pods.
- [ ] Lateral movement test fails as expected.
- [ ] Storefront and checkout still pass after rollout.
- [ ] Argo CD is `Synced/Healthy`.
- [ ] Evidence file is committed.
- [ ] PR states flagd and `/flagservice` were not changed.
