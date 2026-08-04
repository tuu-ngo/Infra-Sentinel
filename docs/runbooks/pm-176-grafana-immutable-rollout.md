# PM-176 — Grafana immutable plugin rollout

This runbook verifies that Grafana owns the OpenSearch datasource plugin in its
custom ECR image and does not download it during Pod startup.

Implementation timeline, failure analysis, final core evidence, and the
remaining PR #426 gates are recorded in
[`docs/pm-176-grafana-opensearch-implementation-report.md`](../pm-176-grafana-opensearch-implementation-report.md).

The deploy source is `main` through ArgoCD. Do not use `helm upgrade`,
`kubectl apply`, or an ad-hoc image patch as the final state.

## Preconditions

- PR 1 image build has completed and the production values contain the exact
  ECR tag plus `sha256` digest.
- PR 2 has been merged into `main`.
- `native-admission-policies` and `techx-corp` are both `Synced/Healthy`.
- The operator has `kubectl exec`, `kubectl port-forward`, and read access to
  the Grafana namespace.
- `AWS_PROFILE=techx-new` in WSL is the active production session for account
  `197826770971`. Confirm with `aws sts get-caller-identity` before any
  cluster command. An operator profile is required for the destructive
  recreation gate.

## Static/render gate

From WSL:

```bash
helm template techx-corp \
  "phase3 - information/techx-corp-chart" \
  --namespace techx-tf3 \
  -f "phase3 - information/techx-corp-chart/values.yaml" \
  -f "phase3 - information/deploy/values-flagd-sync.yaml" \
  -f "phase3 - information/deploy/values-prod.yaml" \
  -f "phase3 - information/deploy/values-aio-llm.yaml" \
  >/tmp/pm176-rendered.yaml

python3 -m pytest -q \
  scripts/ci/test_pm176_grafana_immutable_runtime.py \
  scripts/ci/test_runtime_hardening.py
```

The render must show exactly one `GF_PATHS_PLUGINS=/opt/grafana/plugins`
entry, no `GF_PLUGINS_PREINSTALL*` entry, no plugin installer command, and an
ECR `tag@sha256` image reference. The rendered `grafana.ini` must also contain:

```ini
[plugins]
allow_loading_unsigned_plugins = grafana-opensearch-datasource
preinstall_disabled = true
preinstall_auto_update = false
plugin_admin_enabled = false
plugin_admin_external_manage_enabled = false
```

The PR must also pass `.github/workflows/verify-grafana-image.yml`. This
read-only check builds both `linux/amd64` and `linux/arm64`, blocks any
HIGH/CRITICAL Trivy finding, and runs an amd64 startup smoke. The smoke must
set `GF_PLUGINS_PREINSTALL_DISABLED=true`; setting
`GF_PLUGINS_PREINSTALL` to an empty value is insufficient because Grafana 13
otherwise starts its default catalog installer.

The provisioned OpenSearch datasource must use
`database: "[otel-logs-]YYYY-MM-DD"` together with
`interval: Daily`. The interval is required for the plugin to expand the
time-pattern during Save & Test; without it, the health endpoint treats the
pattern as a literal index name. Dashboard PPL queries may continue to use
`source=otel-logs-*`.

## Non-destructive runtime gate

Run the smoke test with the current Grafana egress state:

```bash
bash scripts/pm-176-grafana-smoke.sh
```

The script creates only a short-lived local port-forward. It records the Pod
UID, node, image, imageID, Argo state, plugin manifest, API responses, and
startup log under `outputs/pm-176/<UTC timestamp>/`.

Required PASS results:

- Pod is Ready with zero restarts.
- Image is the expected first-party digest.
- `/opt/grafana/plugins/grafana-opensearch-datasource/plugin.json` exists and
  reports the pinned version.
- Grafana API health is successful.
- Plugin API reports `grafana-opensearch-datasource` enabled.
- Datasource UID `webstore-logs` has type
  `grafana-opensearch-datasource`.
- Datasource health is successful.
- Startup log contains no runtime download/install attempt for any plugin.
- Startup log contains no modified/invalid plugin signature or validation error.
- The image contains `TF3-PROVENANCE` with
  `trust_model=tf3-derived-unsigned`, and no `MANIFEST.txt` remains beside the
  rebuilt backend. The outer image digest/SBOM/Cosign controls do not claim to
  be an upstream Grafana plugin signature.

`BLOCKED` means the operator permission or tool is missing; it is not a pass.
Resolve it or attach the output as incomplete evidence.

## NetworkPolicy integration gate

After the Grafana image/config PR is verified, rebase and merge the NetworkPolicy
PR. Wait for `techx-infrastructure-app` to become `Synced/Healthy`, then run:

```bash
EXPECT_EGRESS_BLOCK=1 bash scripts/pm-176-grafana-smoke.sh
```

The public egress assertion must fail closed while the internal OpenSearch,
Prometheus, Jaeger, DNS, and Kubernetes API paths remain usable. Do not add a
public plugin-repository allow rule to make this test pass.

## Destructive Pod recreation gate

This is an operator-only action. Run during an approved low-traffic window:

```bash
POD_BEFORE="$(kubectl -n techx-tf3 get pod \
  -l app.kubernetes.io/name=grafana \
  -o jsonpath='{.items[0].metadata.uid}')"

kubectl -n techx-tf3 delete pod \
  -l app.kubernetes.io/name=grafana

kubectl -n techx-tf3 rollout status deployment/grafana --timeout=5m
EXPECT_EGRESS_BLOCK=1 bash scripts/pm-176-grafana-smoke.sh
```

The new Pod UID must differ from `POD_BEFORE`. The smoke output must still
contain all required PASS results and no runtime download. A Pod merely being
Ready is insufficient evidence.

Repeat once more using a controlled rollout or pod-template annotation change.
Keep both output directories as evidence.

## Functional Grafana check

Use the Grafana URL or the smoke test's local port-forward to verify the
`webstore-logs` datasource and a real dashboard panel that queries OpenSearch.
Do not use a fabricated query. Record the datasource health/query response in
the evidence directory without recording credentials or tokens.

## Rollback

Trigger rollback for CrashLoopBackOff, incompatible/unsigned plugin, missing
`webstore-logs`, failed OpenSearch query, failed sidecar provisioning, failed
digest admission, or startup download attempts.

1. Stop the destructive test.
2. Use GitHub to create a revert PR for the PM-176 production-values/config
   merge commit, targeting `main`.
3. Merge the revert through normal branch protection and wait for ArgoCD
   `Synced/Healthy`.
4. Run the smoke test against the previous image and attach the failure
   evidence.
5. If the failure is introduced only by the NetworkPolicy PR, revert that PR
   separately. Do not leave public egress enabled as the permanent workaround.

Never delete evidence from a failed rollout.
