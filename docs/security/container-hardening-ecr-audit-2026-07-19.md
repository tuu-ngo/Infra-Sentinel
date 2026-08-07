# Container hardening and ECR supply-chain audit — 2026-07-19

## Decision

**Do not blindly enable a read-only root filesystem in production today.** This
is an audit-only deliverable: it deliberately does not change the chart,
production values, Argo CD Application, or a live workload. The audit found
that the current template lets a component `securityContext` replace the
default context, so a future hardening implementation needs a separate,
canaried chart change. ECR is already compliant with the requested repository
controls: the live `techx-corp` repository is **IMMUTABLE**, not MUTABLE, and
enhanced continuous scanning is enabled.

This closes the audit deliverable and leaves a safe, testable implementation
path instead of a manifest-only recommendation.

## Evidence and scope

The inventory is the production Helm composition rendered on 2026-07-19:

```sh
helm template techx-corp 'phase3 - information/techx-corp-chart' \
  --namespace techx-tf3 \
  -f 'phase3 - information/techx-corp-chart/values.yaml' \
  -f 'phase3 - information/deploy/values-flagd-sync.yaml' \
  -f 'phase3 - information/deploy/values-prod.yaml' \
  -f 'phase3 - information/deploy/values-aio-llm.yaml'
```

`helm lint` passed for the same chart and value layers. The new repeatable
inventory command is:

```sh
python3 scripts/ci/audit-container-hardening.py \
  --rendered /tmp/techx-rendered.yaml \
  --output /tmp/container-hardening-inventory.json
```

It evaluates every rendered Pod template (Deployment, StatefulSet, DaemonSet,
Rollout, Job and Pod) and every app, sidecar, init and ephemeral container for
the three controls below. It is an audit signal; it does not weaken or replace
the existing Kyverno policy.

The active render contains **28 workloads / 38 containers**: **1 critical**
finding (the documented Kafka ownership init), **1 high** finding (the same
init does not explicitly disable privilege escalation), and **33 medium**
read-only-root-filesystem findings. The draft strict values file is not an
effective enforcement mechanism with the current replacement semantics: the
strict render has the same 35 findings. That is an audit finding, not a reason
to merge a runtime fix without a canary.

| Control | Current enforcement | Why it limits post-compromise movement |
| --- | --- | --- |
| `runAsNonRoot: true` | Kyverno Enforce; chart default | prevents a compromised process from starting as UID 0 |
| `allowPrivilegeEscalation: false` | Kyverno Enforce; chart default | blocks setuid/file-capability privilege gain inside the container |
| `readOnlyRootFilesystem: true` | draft only; current template/value layering does not enforce it | blocks persistence and binary/config tampering on the image filesystem |

## Deployment gap table

The table is for each rendered Deployment's primary application container.
`Yes` means the effective rendered container value is present. The separate
init/sidecar rows below are equally in scope because their compromise also
creates a pod-level attack path.

| Deployment | Non-root | No privilege escalation | Read-only root | Gap severity |
| --- | :---: | :---: | :---: | --- |
| accounting | Yes | Yes | No | Medium — root filesystem writable |
| ad | Yes | Yes | No | Medium |
| cart | Yes | Yes | Yes | None |
| checkout | Yes | Yes | Yes | None |
| currency | Yes | Yes | No | Medium |
| email | Yes | Yes | No | Medium |
| flagd | Yes | Yes | No | Medium |
| fraud-detection | Yes | Yes | No | Medium |
| frontend | Yes | Yes | Yes | None |
| frontend-proxy | Yes | Yes | No | Medium — generates Envoy config at startup |
| image-provider | Yes | Yes | No | Medium — generates NGINX config at startup |
| kafka | Yes | Yes | No | Medium — persistent broker data path |
| llm | Yes | Yes | No | Medium |
| load-generator | Yes | Yes | No | Medium — browser/cache writable paths must be mapped first |
| payment | Yes | Yes | Yes | None |
| postgresql | Yes | Yes | No | Medium — persistent database data path |
| product-catalog | Yes | Yes | No | Medium |
| product-reviews | Yes | Yes | No | Medium |
| quote | Yes | Yes | No | Medium |
| recommendation | Yes | Yes | No | Medium |
| shipping | Yes | Yes | Yes | None |
| valkey-cart | Yes | Yes | No | Medium — persistent `/data` path |
| grafana | Yes | Yes | No | Medium — dependency chart; configure through its own values |
| jaeger | Yes | Yes | No | Medium — dependency chart; configure through its own values |
| prometheus | Yes | Yes | No | Medium — dependency chart; configure through its own values |

### Complete init/sidecar coverage

The primary-container table covers all **25 rendered Deployments**. The audit
also checked every additional container, so a Deployment with an init or
sidecar is not silently treated as compliant based only on its primary
container:

| Deployment | Additional container(s) | Non-root | No privilege escalation | Read-only root | Gap severity |
| --- | --- | :---: | :---: | :---: | --- |
| accounting | `wait-for-kafka` init | Yes | Yes | No | Medium |
| cart | `wait-for-valkey-cart` init | Yes | Yes | No | Medium |
| checkout | `wait-for-kafka` init | Yes | Yes | No | Medium |
| flagd | `flagd-ui` sidecar, `init-config` init | Yes | Yes | No | Medium |
| fraud-detection | `wait-for-kafka` init | Yes | Yes | No | Medium |
| grafana | `grafana-sc-alerts`, `grafana-sc-dashboard`, `grafana-sc-datasources` sidecars | Yes | Yes | No | Medium |
| kafka | `init-kafka-data` init | **No: UID 0** | **No** | No | **Critical + high documented ownership exception** |

This accounts for the full rendered inventory: **28 workloads / 38
containers**. The Kafka init is the only non-root exception and the only
container missing `allowPrivilegeEscalation: false`.

### Sidecars, init containers and non-Deployment workloads

| Workload/container | Finding | Severity | Required handling |
| --- | --- | --- | --- |
| `kafka/init-kafka-data` | UID 0 is required to create and chown the mounted EBS data directory; privilege escalation is not explicitly disabled | Critical + High, documented time-bounded Kyverno exception; mentor disposition pending | keep the narrow exception; in a separate canary PR add `allowPrivilegeEscalation: false` and `drop: ["ALL"]`, then replace the ownership init with CSI/pre-provisioned ownership |
| app wait/init containers and `flagd/init-config` | non-root and no-escalation are present; root filesystem is writable | Medium | include init containers in the separate deep-merge/template hardening PR, then canary their startup command |
| `flagd/flagd-ui` sidecar | non-root and no-escalation are present; root filesystem is writable | Medium | after the template fix, canary with the strict profile and retain its `/app/data` writable volume |
| `otel-collector-agent` DaemonSet | outside the component template; separate dependency values | Medium if strict policy is expanded cluster-wide | verify vendor chart's writable host/queue paths before adding a read-only policy |
| `opensearch` StatefulSet | outside the component template; persistent state and vendor init behavior | Medium if strict policy is expanded cluster-wide | use the OpenSearch chart's documented security settings and test on a snapshot-capable node |

There are no unapproved primary-container gaps for `runAsNonRoot` or
`allowPrivilegeEscalation` in this render. The only UID 0 and
privilege-escalation finding is the documented Kafka init exception in
[`exception-register.yaml`](../evidence/mandate-05/exception-register.yaml).

## Proposed chart baseline — not applied

The current chart uses replacement semantics for component, sidecar and init
`securityContext` values. It also has a duplicate empty
`default.securityContext` mapping in `values.yaml`. Consequently, a values-only
`readOnlyRootFilesystem` override does not change the current rendered
workloads. A future hardening PR must first remove that duplicate mapping and
deep-merge default and per-container contexts before applying the baseline.

The proposed baseline for that separate hardening PR is:

```yaml
runAsNonRoot: true
allowPrivilegeEscalation: false
capabilities:
  drop: ["ALL"]
seccompProfile:
  type: RuntimeDefault
```

The draft strict profile in
[`values-security-baseline.yaml`](../../phase3%20-%20information/deploy/values-security-baseline.yaml)
adds:

```yaml
readOnlyRootFilesystem: true
```

It is deliberately not referenced by the Argo CD production application and,
until the template is fixed, is a proposal rather than an effective profile.
No production render or workload changes result from merging this audit-only
file.

### Safe promotion gate

1. In a separate PR, remove the duplicate context mapping and deep-merge the
   default with component, sidecar and init contexts; render the exact Argo CD
   value stack and review the manifest diff.
2. Select one stateless, already read-only service (`checkout`, `frontend`,
   `payment`, `cart`, or `shipping`) and deploy through the normal GitOps
   canary path; do not use `kubectl edit`.
3. Require Ready pods, a successful application probe, no `Read-only file
   system` / `permission denied` log line, and a rollback commit ready before
   moving to the next service.
4. For `frontend-proxy` and `image-provider`, first redirect generated config
   to an `emptyDir`; for `load-generator`, mount its browser/cache paths; for
   PostgreSQL, Valkey, Kafka and OpenSearch, retain only their explicit data
   volumes as writable and test persistence/restart.
5. Only after all owners pass this gate, add a Kyverno
   `require-read-only-root-filesystem` Enforce rule. Dependency charts need
   their own values first, so a global policy today would cause regression.

The additional control has effectively no cloud-service cost; its cost is the
targeted compatibility test and any `emptyDir` mount needed by images that
generate configuration, cache data, sockets or persistent state.

## ECR supply-chain result

Live read-only AWS inspection on 2026-07-19, account `197826770971`, returned:

```text
repository: techx-corp
imageTagMutability: IMMUTABLE
scanOnPush: true
encryption: AES256
registry scan type: ENHANCED
registry scan frequency: CONTINUOUS_SCAN
repository filter: *
```

Therefore the premise that this repository remains `MUTABLE` is stale; no
ECR mutation is needed. The CI workflow additionally blocks first-party
HIGH/CRITICAL Trivy findings before promotion, pins first-party production
images to digests, and signs the pushed digest with GitHub OIDC Cosign. See
[`image-supply-chain-controls.md`](image-supply-chain-controls.md).

Residual supply-chain gap: the external runtime images rendered for PostgreSQL,
Valkey and Flagd are still tag-pinned in this chart. They are outside this ECR
repository, but should be migrated to upstream digests and retained in the
weekly external-image scan inventory before any claim of full end-to-end image
immutability.

## Audit closure checklist

| Required outcome | Status | Evidence |
| --- | --- | --- |
| Audit `runAsNonRoot`, `allowPrivilegeEscalation`, and `readOnlyRootFilesystem` for every Deployment and its init/sidecar containers | Complete | 25 Deployments, 28 workloads, and 38 containers rendered and evaluated by `audit-container-hardening.py` |
| Severity-ranked gap table and a chart-wide baseline proposal | Complete | Tables above; proposal records the current template gap and a separate canary promotion path |
| Verify ECR scan-on-push and tag mutability | Complete | Live AWS read-only query: `IMMUTABLE`, `scanOnPush=true`, enhanced continuous scan |
| Avoid an unsafe blanket read-only rollout | Complete | No chart, production values, or Argo CD Application change is included; strict profile remains an unreferenced proposal |

This audit is therefore **closed**. Implementing the proposed deep merge,
enabling the strict profile, and changing the Kafka ownership exception are
separate, explicitly risk-bearing hardening changes; they are not part of this
evidence-only task.
