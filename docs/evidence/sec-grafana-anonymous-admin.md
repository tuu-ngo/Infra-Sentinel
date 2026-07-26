# Evidence: SEC-01 Grafana Anonymous Organization Admin Remediation

## 1. Issue Overview
Grafana was configured with `auth.anonymous.enabled = true` and `org_role = Admin`, which allows anyone reaching the Grafana endpoint to gain anonymous Organization Admin access within the configured Grafana organization without providing credentials. Concurrently, `adminPassword: admin` was hardcoded in plaintext.

## Pre-fix runtime PoC — VERIFIED

Grafana version: `13.0.1`
Grafana commit: `a100054f`
Database status: `ok`

The requests were executed through a local Kubernetes port-forward.
No Authorization header, API token or authenticated cookie was used.
Response bodies were discarded.

| Attempt | `/api/health` | `/api/user` | `/api/org/users` | `/api/admin/settings` |
|---:|---:|---:|---:|---:|
| 1 | 200 | 401 | 200 | 403 |
| 2 | 200 | 401 | 200 | 403 |
| 3 | 200 | 401 | 200 | 403 |

Classification:

- Anonymous Organization Admin: **CONFIRMED**
- Anonymous Grafana Server Admin: **NOT CONFIRMED**
- Mutation performed: **NO**
- Sensitive body retained: **NO**

Execution date: 2026-07-15
Exact execution time: not captured in the original terminal transcript
Evidence ingestion time: 2026-07-15T16:59:00Z

---

## Post-Fix Verification

### Prerequisite: Secret Deployment
The AWS Secrets Manager object must exist before the rollout succeeds.

> **Note on ExternalSecret Retention Policy:**
> If the AWS secret is removed, the existing Kubernetes Secret is retained and the ExternalSecret enters an error state. This favors availability but can retain stale credentials until explicitly rotated or deleted.

Verification will be done via:
```bash
aws secretsmanager describe-secret \
  --secret-id techx-corp-tf3/grafana-admin-credentials \
  --profile cdo1 \
  --region ap-southeast-1 \
  --query '{
    Name:Name,
    ARN:ARN,
    LastChangedDate:LastChangedDate
  }'
```

And to verify expected JSON properties without printing their contents:
```bash
set +x

aws secretsmanager get-secret-value \
  --secret-id techx-corp-tf3/grafana-admin-credentials \
  --profile cdo1 \
  --region ap-southeast-1 \
  --query SecretString \
  --output text |
python3 -c '
import json
import sys

value = json.load(sys.stdin)
required = {"admin-user", "admin-password"}
missing = required - value.keys()

if missing:
    raise SystemExit(
        f"FAIL: missing properties: {sorted(missing)}"
    )

username = value["admin-user"]
password = value["admin-password"]

if not isinstance(username, str) or not username:
    raise SystemExit("FAIL: admin-user is empty")

if username != "admin":
    raise SystemExit(
        "FAIL: admin-user must remain the existing admin login "
        "during this rotation"
    )

if not isinstance(password, str) or len(password) < 20:
    raise SystemExit(
        "FAIL: admin-password is absent or shorter than 20 characters"
    )

print("PASS: required secret properties exist")
'

set -x
```

### Static Verification
- Run `scripts/security/test-observability-security.sh`: **PASS**

### Runtime Verification
**Status:** `PENDING POST-FIX RUNTIME VERIFICATION`
*(To be completed by the operator after the PR is merged and rolled out).*

Layer A — Anonymous Organization Admin:
  CONFIRMED pre-fix; expected fixed after rollout.

Layer B — Grafana Kubernetes ServiceAccount secret permissions:
  PENDING.

Layer C — Server-side path using the Pod identity:
  NOT DEMONSTRATED.
