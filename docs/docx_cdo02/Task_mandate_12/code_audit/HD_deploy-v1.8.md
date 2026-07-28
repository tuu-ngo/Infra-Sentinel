# HD_deploy — Mandate 12 audit foundation

Hướng dẫn này chỉ dùng khi được phép thay đổi production. Nó tạo **audit foundation độc lập**; không thay đổi EKS, network, CloudFront, Cloudflare, ứng dụng, flagd hoặc Terraform state hiện có. Người deploy phải đi theo đúng thứ tự gate trong tài liệu này: output đã được duyệt của bước trước mới được dùng làm input cho bước sau; không tự đoán ARN, owner, backend hoặc scope dữ liệu.

Foundation là `PARTIAL`: có CloudTrail, S3 WORM, coverage S3 đã duyệt và alert. Chỉ được tuyên bố Mandate 12 `VERIFIED` sau change IAM hardening riêng, mentor test pass và residual risk root/break-glass được chấp nhận bằng văn bản. Single-account không cho phép tuyên bố root hoặc alert plane cùng account bị chặn tuyệt đối.

## 1. Vị trí file trong repository product

Ba Terraform root được đưa vào ba vị trí độc lập và dùng ba state key khác nhau. Chỉ copy từng root khi phase tương ứng đã được phê duyệt:

```text
Phase3-TF3-Infra-Sentinel/
└── infra/
    └── live/
        ├── audit/                              # foundation; tạo mới
        │   ├── .gitignore
        │   ├── .terraform.lock.hcl
        │   ├── versions.tf
        │   ├── providers.tf
        │   ├── main.tf
        │   ├── variables.tf
        │   ├── outputs.tf
        │   ├── backend.hcl                     # local từ example
        │   └── terraform.tfvars                # local từ example
        └── iam/
            └── mandate-12/
                ├── audit_access/               # phase IAM 1; root/state riêng
                │   ├── *.tf
                │   ├── backend.hcl             # local từ example
                │   └── terraform.tfvars        # local từ example
                └── iam_change/                 # phase IAM 2; root/state riêng
                    ├── *.tf
                    ├── backend.hcl              # local từ example
                    └── terraform.tfvars         # local từ example
```

Nguồn copy lần lượt là `code_audit/foundation/`, `code_audit/iam_hardening/audit_access/` và `code_audit/iam_hardening/iam_change/`. File boundary đã render thuộc PR IAM riêng và phải đặt ở vị trí do IaC owner duyệt; không đặt trong `infra/live/audit/`. Không copy bất kỳ root nào vào `infra/live/production/`; không đổi file hoặc state đang có trong root production.

## 2. Phụ thuộc bắt buộc trước deploy

Hoàn tất và ghi evidence cho từng mục dưới đây **trước** khi tạo plan/apply. Nếu một mục chưa rõ owner hoặc chưa có evidence, trạng thái là `NO-GO`.

| Phụ thuộc | Ở đâu | Cần thực hiện/xác nhận | Owner | Evidence cần lưu |
|---|---|---|---|---|
| Identity deploy | AWS account `197826770971` | Dùng IAM user/assumed role cá nhân; không dùng root; xác nhận account/region bằng `aws sts get-caller-identity` | Deployer | Output STS đã redaction nếu cần |
| Terraform backend | Backend đã được duyệt của product | Lấy đúng S3 state bucket + DynamoDB lock table; tạo **key mới** `mandate-12/audit/terraform.tfstate`, không dùng key production | IaC owner | `backend.hcl` local đã review; không commit secret |
| Audit bucket | Account TF3 | Chọn tên bucket **mới**, duy nhất toàn cầu; không dùng lại 7 bucket hiện hữu vì không bucket nào có Object Lock | Security/IaC owner | Tên đã duyệt trong change record |
| S3 data-event scope | Data owner của bucket/prefix nhạy cảm | Duyệt exact ARN prefix cần log `GetObject`; không dùng all-S3/audit archive/fixture canary làm scope thay thế. Terraform state phải được classify và cover nếu sensitive; chỉ không dùng state làm **canary** | Data owner | Approval + ARN prefix trong `terraform.tfvars` local |
| Coverage matrix | Data/Security/IaC owners | Hoàn tất [`m12-coverage-v1.0.md`](../m12-coverage-v1.0.md): toàn bộ bucket/secret/data path nhạy cảm có owner, classification và exact scope | Data + security owners | Matrix đã ký + đối chiếu từng ARN với `terraform.tfvars` |
| Alert recipient | Security/on-call owner | Xác định recipient cho **cả hai** SNS topics và người xác nhận cả hai subscription ngay sau apply | Security owner | Hai email/subscription owner trong change record |
| CloudTrail ownership | AWS account TF3 | Revalidate `describe-trails`; nếu đã có trail mới từ team khác thì dừng, xác định owner và không tạo trail trùng | Security/IaC owner | Output discovery gần thời điểm deploy |
| Cost gate | TF3 budget owner | Forecast Data Events + S3 storage cho prefix đã duyệt; xác nhận không vượt `$300/tuần/TF` | Budget owner | Forecast và ngưỡng no-go |
| IAM hardening | IAM/CI owner | **Không** gộp vào PR foundation. Hoàn tất [`m12-iam-scope-v1.0.md`](../m12-iam-scope-v1.0.md), audit-access root, iam-change executor, boundary PR và root residual acceptance trước verdict | IAM owner | Inventory, attachment map, simulation/baseline, rollback và acceptance |
| Regional alert route | Security/IaC owner | Xác nhận region thực tế của từng denied API event; IAM/global-service event phải test cả `ap-southeast-1` và `us-east-1` | Security owner | Event/target/SNS timestamp theo region |
| Evidence/test window | Mentor + security owner | Đặt UTC window, observer và nơi lưu evidence; chờ digest delivery trước `validate-logs` | Mentor/test owner | Change window + evidence path |

### Checklist dependency

- [ ] Không dùng root; caller là đúng account/region.
- [ ] Backend state key mới, lock table và quyền backend đã được IaC owner duyệt.
- [ ] Có audit bucket name mới, coverage matrix hoàn chỉnh và S3 prefix nhạy cảm được data owner duyệt.
- [ ] Có security owner xác nhận cả hai SNS subscription sau apply.
- [ ] Discovery live không phát hiện trail/bucket audit trùng hoặc drift.
- [ ] Có cost forecast trong ngân sách.
- [ ] IAM hardening được tách thành change riêng, với inventory daily-admin/CI đầy đủ, root acceptance và rollback plan.
- [ ] Có plan kiểm thử runtime cho mọi anti-audit rule, bao gồm regional IAM alert verification.
- [ ] Có change window, mentor/observer và evidence location.

### 2.1 Thứ tự thực hiện bắt buộc

Không bỏ qua hoặc chạy song song các phase có quan hệ phụ thuộc. Nếu gate của một phase fail, dừng tại phase đó; không dùng root, không sửa tay production và không chuyển sang phase tiếp theo.

| Thứ tự | Phase | Việc phải làm | Output bàn giao cho phase sau | Gate |
|---:|---|---|---|---|
| 0 | Đóng băng phạm vi | Chốt account, region, change window, branch, reviewer và nơi lưu evidence | Change record có owner/UTC window | Đủ approval; chưa chạy lệnh ghi AWS |
| 1 | Discovery chỉ đọc | Kiểm tra identity, trail hiện hữu, backend, bucket/prefix, IAM/CI inventory và chi phí dự kiến | Output discovery có timestamp | Không trùng ownership, không còn phụ thuộc `Unknown` |
| 2 | Duyệt input | Data owner ký coverage matrix; IaC owner duyệt backend; security owner duyệt email/MFA owner; budget owner duyệt forecast | Dependency handoff manifest ở mục 2.3 | Mọi dòng là `APPROVED` |
| 3 | Staging foundation | Copy `foundation/` vào `infra/live/audit/`; tạo local `backend.hcl` và `terraform.tfvars` | PR foundation + plan file | Plan chỉ chứa audit resource mới |
| 4 | Deploy foundation | Apply đúng saved plan trong change window | Trail/bucket/topic/rule ARN từ Terraform output | Apply thành công; không sửa product root |
| 5 | Health + alert gate | Xác nhận hai SNS subscription, kiểm tra trail, selectors, digest, Object Lock và 12 rules | Foundation output manifest + health evidence | Hai subscription `Confirmed`; health pass |
| 6 | Audit access | Copy/apply root `audit_access` bằng output thật của phase 5 | Audit-admin, break-glass và assume-policy ARN | Named MFA owner assume được; operator thường không assume được |
| 7 | Boundary review | Chọn strict/allowlisted template, render từ ARN thật, validate và simulate từng identity | Boundary JSON + managed-policy ARN + simulation | Baseline được phép; audit tamper là `explicitDeny` |
| 8 | IAM executor | Copy/apply root `iam_change`, dùng exact boundary/target/owner ARN | Controlled executor ARN | `allow_boundary_removal=false`; owner MFA assume được |
| 9 | Attach theo batch | Qua executor, attach boundary từng identity/batch nhỏ và chạy lại baseline | Attachment map + kết quả từng batch | Batch trước pass mới làm batch sau |
| 10 | Mentor test/evidence | Chạy T01–T11, validate digest, coverage, denied action và alert ở đúng region | Evidence đã hash + verdict | Tất cả test pass, không có khoảng trống |
| 11 | Đóng change | Cleanup fixture an toàn, lưu evidence, ghi residual acceptance | Hồ sơ bàn giao cuối | Chỉ lúc này mới được ghi `VERIFIED` |

Ba state key bắt buộc và không được dùng lẫn:

| Terraform root | State key |
|---|---|
| `infra/live/audit/` | `mandate-12/audit/terraform.tfstate` |
| `infra/live/iam/mandate-12/audit_access/` | `mandate-12/audit_access/terraform.tfstate` |
| `infra/live/iam/mandate-12/iam_change/` | `mandate-12/iam-change/terraform.tfstate` |

### 2.2 Cách lấy hoặc tạo từng phụ thuộc

Thực hiện theo đúng thứ tự dưới đây. Các lệnh `aws` ở bước discovery chỉ đọc; lệnh tạo/attach được ghi rõ là chỉ chạy sau approval.

#### A. Xác nhận identity và CloudTrail hiện trạng

```powershell
aws sts get-caller-identity
aws configure get region
aws cloudtrail describe-trails --include-shadow-trails --region ap-southeast-1
```

Kết quả phải là account `197826770971`, region `ap-southeast-1`. Nếu đã có trail, không tạo trail mới ngay: lấy tên/owner/change record của trail hiện hữu, rồi dừng để security owner quyết định import hay tách ownership.

#### B. Lấy backend state độc lập

1. IaC owner cung cấp tên S3 state bucket và DynamoDB lock table đang được product phê duyệt; không tự đoán hoặc copy state key của `infra/live/production`.
2. Xác nhận backend đã tồn tại bằng metadata-only:

```powershell
aws s3api head-bucket --bucket <approved-tfstate-bucket>
aws dynamodb describe-table --table-name <approved-lock-table> --region ap-southeast-1
```

3. Tạo local `backend.hcl` từ example với key mới `mandate-12/audit/terraform.tfstate`. Key mới được Terraform tạo khi apply; không cần và không được tạo thủ công object state.
4. IaC owner review `backend.hcl`; giữ local, không commit nếu chứa thông tin nội bộ.

#### C. Chọn audit bucket mới

1. Chọn tên theo `tf3-m12-audit-197826770971-<unique-suffix>`.
2. Kiểm tra tên chưa bị chiếm. `404` nghĩa là chưa có bucket; `403` hoặc thành công nghĩa là phải chọn tên khác/kiểm tra ownership.

```powershell
aws s3api head-bucket --bucket tf3-m12-audit-197826770971-<unique-suffix>
```

3. Ghi tên đã duyệt vào `terraform.tfvars`. Terraform sẽ tạo bucket mới cùng Object Lock; **không** tạo bucket bằng Console/CLI trước vì Object Lock phải do Terraform quản lý từ lúc tạo.

#### D. Lấy S3 data-event scope

1. Lấy inventory bucket ở mức metadata, sau đó data owner chọn prefix chứa dữ liệu nhạy cảm:

```powershell
aws s3api list-buckets --query "Buckets[].Name" --output table
aws s3api list-objects-v2 --bucket <candidate-bucket> --prefix <candidate-prefix/> --max-keys 5
```

2. Data owner ký/ghi approval cho ARN theo mẫu `arn:aws:s3:::<bucket>/<prefix>/`.
3. Điền ARN đó vào `s3_data_event_arns` và đối chiếu từng giá trị với [coverage matrix](../m12-coverage-v1.0.md). Không dùng `*`, toàn bộ bucket không có approval, audit archive, secret manifest hoặc canary object làm production coverage scope.
4. Terraform state phải được security/IaC owner phân loại: nếu có sensitive output thì thêm exact state prefix vào matrix/selector hoặc có compensating control được chấp nhận bằng văn bản. Không tự động loại trừ state.
5. Nếu chưa có prefix được duyệt hoặc còn asset nhạy cảm `Unknown` thì dừng ở `NO-GO`; không deploy foundation “rỗng” rồi gọi là Mandate 12 complete.

#### E. Tạo alert recipient

1. Security owner chọn email on-call/nhóm nhận alert, có khả năng xác nhận **cả hai** SNS subscription.
2. Điền vào `alert_email` trong `terraform.tfvars`.
3. Sau foundation apply, recipient phải bấm **cả hai** link xác nhận SNS. Chỉ khi cả hai là `Confirmed` mới qua gate; một `PendingConfirmation` là `DEPLOYED`, chưa `VERIFIED`.

#### F. Tạo forecast chi phí

1. Data owner lấy số read/write dự kiến của prefix từ dashboard ứng dụng, S3 metrics hoặc CloudWatch đã có; không bật all-S3 để “đo thử”.
2. Budget owner dùng đơn giá CloudTrail Data Events và S3 storage tại thời điểm deploy (AWS Pricing/Cost Explorer hiện hành) để tính forecast tuần.
3. Lưu số lượng event giả định, đơn giá, tổng forecast và ngưỡng `$300/tuần/TF` vào change record. Không có forecast = `NO-GO`.

#### G. Thu thập phụ thuộc IAM hardening

Foundation không tự hạn chế current admin. Ở phase discovery chỉ thu thập inventory, owner, baseline và approval; **không tạo policy, không apply IAM root và không attach boundary tại mục này**. IAM hardening phải đi qua PR/state root riêng theo đúng chuỗi: **foundation pass → cả hai SNS subscription Confirmed → audit-access root apply → render/create boundary → iam_change executor root → MFA owner assume executor → simulation/baseline từng identity → attach batch nhỏ → denied tests**. Không gộp IAM thay đổi vào PR foundation.

1. IAM owner hoàn tất [IAM scope](../m12-iam-scope-v1.0.md) cho **mọi** daily-admin/CI identity, gồm group, inline/managed policy, trust/OIDC và escalation path; root/audit-admin/break-glass là exception có owner/acceptance, không phải item bị bỏ qua:

```powershell
aws iam get-account-authorization-details `
  --filter User Role Group LocalManagedPolicy AWSManagedPolicy `
  --output json | Set-Content -LiteralPath (Join-Path $evidenceDir "iam-authorization-details.json") -Encoding utf8
aws iam generate-credential-report
aws iam get-credential-report --output json |
  Set-Content -LiteralPath (Join-Path $evidenceDir "iam-credential-report.json") -Encoding utf8
aws iam list-open-id-connect-providers --output json |
  Set-Content -LiteralPath (Join-Path $evidenceDir "iam-oidc-providers.json") -Encoding utf8
aws iam get-role --role-name <approved-ci-or-admin-role> --output json |
  Set-Content -LiteralPath (Join-Path $evidenceDir "iam-reviewed-role.json") -Encoding utf8
```

Đặt `$evidenceDir` trước khi chạy vào nơi restricted/untracked đã được phê duyệt. Các file inventory có thể lộ cấu trúc IAM; không ghi chúng vào product repo và không gửi nguyên bản ra ngoài nhóm review.

2. Chốt exact target user/role ARN, workflow baseline, nhu cầu `sts:AssumeRole`, named security owner và rollback owner trong [IAM scope](../m12-iam-scope-v1.0.md). Mặc định dùng named IAM user đã bật MFA làm trusted owner. Nếu đề xuất role ARN, IAM owner phải chứng minh session thực tế có MFA context phù hợp với trust condition trước plan; chỉ ghi “role có MFA” là chưa đủ.

3. IaC owner duyệt hai path/state IAM riêng, decision strict/allowlisted boundary và owner cho bootstrap policy. Kiểm tra trước collision của các role/policy tên `tf3-m12-*`; nếu resource đã tồn tại thì `NO-GO` để quyết định import/reuse, không tạo đè.

4. Dừng phase discovery tại đây. Các bước G.1–G.9 dưới đây là checklist lệnh cho **phases 6–9** và chỉ được thực hiện khi mục 8.3 trỏ tới, sau khi §7 health pass.

##### G.1 — Lấy output foundation cho phase 6

Sau foundation apply và §7 health pass, lấy output thật và record trạng thái của cả hai subscription:

```powershell
$trailArn = terraform "-chdir=$foundationDir" output -raw trail_arn
$auditBucketName = terraform "-chdir=$foundationDir" output -raw audit_bucket_name
$primaryAlertTopicArn = terraform "-chdir=$foundationDir" output -raw alert_topic_arn
$globalAlertTopicArn = terraform "-chdir=$foundationDir" output -raw global_alert_topic_arn
$primaryRuleArnMap = terraform "-chdir=$foundationDir" output -json anti_audit_rule_arns | ConvertFrom-Json
$globalRuleArnMap = terraform "-chdir=$foundationDir" output -json global_anti_audit_rule_arns | ConvertFrom-Json
terraform "-chdir=$foundationDir" output -json alert_regions

$primaryRuleArns = @($primaryRuleArnMap.PSObject.Properties.Value)
$globalRuleArns = @($globalRuleArnMap.PSObject.Properties.Value)
if ($primaryRuleArns.Count -ne 7 -or $globalRuleArns.Count -ne 5) {
  throw "Expected exactly 7 primary and 5 global anti-audit rules"
}

$primarySubscriptions = aws sns list-subscriptions-by-topic `
  --topic-arn $primaryAlertTopicArn --region ap-southeast-1 --output json | ConvertFrom-Json
$globalSubscriptions = aws sns list-subscriptions-by-topic `
  --topic-arn $globalAlertTopicArn --region us-east-1 --output json | ConvertFrom-Json
$approvedAlertEmail = "<exact-email-from-D07>"
$primaryConfirmed = @($primarySubscriptions.Subscriptions | Where-Object {
  $_.Protocol -eq "email" -and $_.Endpoint -eq $approvedAlertEmail -and $_.SubscriptionArn -ne "PendingConfirmation"
})
$globalConfirmed = @($globalSubscriptions.Subscriptions | Where-Object {
  $_.Protocol -eq "email" -and $_.Endpoint -eq $approvedAlertEmail -and $_.SubscriptionArn -ne "PendingConfirmation"
})
if ($primaryConfirmed.Count -ne 1 -or $globalConfirmed.Count -ne 1) {
  throw "Exact approved email must have one Confirmed subscription in each region before audit_access"
}
$primarySubscriptionArn = $primaryConfirmed[0].SubscriptionArn
$globalSubscriptionArn = $globalConfirmed[0].SubscriptionArn
```

Khi điền `audit_access/terraform.tfvars`, dùng `$auditBucketName` để tạo đúng ARN `arn:aws:s3:::$auditBucketName`, dùng `$trailArn`, hai topic ARN và flatten đúng 7 + 5 rule ARN từ output. Root audit-access từ chối plan nếu không nhận **đúng 2 topic và 12 rule**. Không nhập lại ARN từ trí nhớ hoặc copy placeholder của example.

`PendingConfirmation`, sai protocol hoặc endpoint không khớp D07 là `NO-GO` cho audit_access và mọi IAM phase tiếp theo. Sau cả hai confirmation, có thể chạy refresh-only theo change approval để đồng bộ Terraform state; boundary phải dùng `$primarySubscriptionArn` và `$globalSubscriptionArn` thực tế từ regional query, không dùng giá trị stale/placeholder. Thiếu một ARN vẫn là `NO-GO` vì policy phải bảo vệ cả primary và global alert plane.

##### G.2 — Deploy audit-access root ở phase 6

Tạo branch `chore/mandate-12-iam-boundary` độc lập. Sau IaC-owner approval, copy **toàn bộ standalone root** `code_audit/iam_hardening/audit_access/` vào `infra/live/iam/mandate-12/audit_access/`, dùng backend state key riêng `mandate-12/audit_access/terraform.tfstate`. Điền audit bucket/trail ARN, **cả hai** SNS topic ARN, toàn bộ 12 primary/global rule ARN và exact MFA-capable security owner ARNs theo `audit_access/README.md`; plan/apply root này trước attachment. Không đặt nó trong `infra/live/audit/` hoặc `infra/live/production/`.

Pre-notify security/on-call với change ID và UTC window: việc tạo audit roles/policies, attach assume policy và các IAM phase tiếp theo sẽ chủ động kích hoạt IAM tamper alerts. Không disable/suppress EventBridge/SNS trong change. Alert có actor/action ngoài mapping hoặc ngoài window là `STOP/INCIDENT`.

```powershell
$auditAccessSource = Join-Path $taskRoot "code_audit\iam_hardening\audit_access"
if (Test-Path -LiteralPath $auditAccessDir) {
  throw "audit_access target exists: stop for ownership/import review"
}
New-Item -ItemType Directory -Path $auditAccessDir
$auditAccessFiles = @(
  ".gitignore", ".terraform.lock.hcl", "backend.hcl.example", "main.tf",
  "outputs.tf", "providers.tf", "README.md", "terraform.tfvars.example",
  "variables.tf", "versions.tf"
)
foreach ($sourceFile in $auditAccessFiles) {
  Copy-Item -LiteralPath (Join-Path $auditAccessSource $sourceFile) -Destination $auditAccessDir
}
Copy-Item -LiteralPath (Join-Path $auditAccessDir "backend.hcl.example") -Destination (Join-Path $auditAccessDir "backend.hcl")
Copy-Item -LiteralPath (Join-Path $auditAccessDir "terraform.tfvars.example") -Destination (Join-Path $auditAccessDir "terraform.tfvars")

# Điền local files từ D02/D03/D09/D10 trước, rồi quét placeholder.
$auditAccessInputs = @(
  (Join-Path $auditAccessDir "backend.hcl"),
  (Join-Path $auditAccessDir "terraform.tfvars")
)
$unresolved = Select-String -Path $auditAccessInputs -Pattern 'REPLACE_WITH|<[^>]+>|\bTODO\b|\bUnknown\b'
if ($unresolved) { $unresolved; throw "Unresolved audit_access input" }

terraform "-chdir=$auditAccessDir" init -backend-config=backend.hcl -input=false -lockfile=readonly
terraform "-chdir=$auditAccessDir" fmt -check
terraform "-chdir=$auditAccessDir" validate
if (git status --porcelain) { throw "Commit/review audit_access source before creating the plan" }
if ((terraform "-chdir=$auditAccessDir" workspace show).Trim() -ne "default") { throw "Unexpected workspace" }
if (terraform "-chdir=$auditAccessDir" state list) { throw "audit_access state is not empty" }
terraform "-chdir=$auditAccessDir" plan -var-file=terraform.tfvars -out=tfplan
terraform "-chdir=$auditAccessDir" show -no-color tfplan | Set-Content -LiteralPath (Join-Path $auditAccessDir "tfplan.txt") -Encoding utf8
Get-FileHash -Algorithm SHA256 (Join-Path $auditAccessDir "tfplan")

# Chỉ sau plan/PR/hash approval trong change window.
$approvedAuditAccessPlanHash = "<approved-audit-access-plan-sha256>"
$approvedAuditAccessGitSha = "<approved-audit-access-git-sha>"
$actualAuditAccessPlanHash = (Get-FileHash -Algorithm SHA256 (Join-Path $auditAccessDir "tfplan")).Hash
if ($actualAuditAccessPlanHash -ne $approvedAuditAccessPlanHash) { throw "audit_access plan hash changed" }
if ((git rev-parse HEAD).Trim() -ne $approvedAuditAccessGitSha) { throw "audit_access Git SHA changed" }
terraform "-chdir=$auditAccessDir" apply tfplan
terraform "-chdir=$auditAccessDir" output
```

Sau audit-access apply, lưu hai role ARN và `security_owner_assume_audit_policy_arn`. Policy assume này chỉ được gắn trong IAM change review vào từng named MFA security owner; không gắn group rộng, operator thường, root hoặc wildcard principal. Audit-admin chỉ đọc evidence; break-glass chỉ `StartLogging`/`EnableRule`.

Trust policy không tự cấp quyền gọi `sts:AssumeRole`. Qua bootstrap IAM change riêng đã duyệt, attach output assume policy vào đúng named MFA owner, sau đó test owner assume audit-admin/break-glass bằng MFA và test operator thường nhận `AccessDenied`. Lưu mapping `owner ARN → assume-policy ARN → audit-role ARN`; không lưu credential.

##### G.3 — Chọn boundary template ở phase 7

   - `operator-boundary-policy.template.json` là **strict default**; nó deny toàn bộ `sts:AssumeRole`. Chỉ attach khi inventory chứng minh target không cần assume role.
   - Nếu CI/workflow cần `sts:AssumeRole`, đây là `NO-GO` cho strict default. Chỉ dùng `operator-boundary-policy.allowlisted-assume-role.template.json` sau khi exact **non-audit** target roles, trust policy/OIDC, audit-admin/break-glass outputs và baseline CI đã được review/test.
   - Không attach boundary vào root, audit-admin/break-glass, hoặc bất kỳ identity nào vẫn giữ unbounded `AdministratorAccess` ngoài scope migration.

##### G.4 — Render và validate boundary ở phase 7

Copy template đã chọn thành file rendered `operator-boundary.json` trong workspace của **PR IAM riêng**; không copy template vào `infra/live/audit`. Thay toàn bộ placeholder bằng outputs foundation/audit-access thật. Kiểm tra JSON và IAM policy validation trước review:

```powershell
Get-Content -Raw operator-boundary.json | ConvertFrom-Json | Out-Null
aws accessanalyzer validate-policy `
  --policy-document file://operator-boundary.json `
  --policy-type IDENTITY_POLICY `
  --region ap-southeast-1
```

##### G.5 — Simulate boundary ở phase 7

Simulate policy cho **từng** target identity và cho primary/global audit resource trước; audit/alert/IAM-escalation actions phải `explicitDeny`, baseline operation cần thiết phải `allowed`:

```powershell
aws iam simulate-principal-policy `
  --policy-source-arn <approved-user-or-role-arn> `
  --permissions-boundary-policy-input-list file://operator-boundary.json `
  --action-names cloudtrail:StopLogging s3:DeleteObject events:DisableRule sns:DeleteTopic iam:DeleteUserPermissionsBoundary iam:UpdateAssumeRolePolicy eks:DescribeCluster `
  --resource-arns <trail-arn> <audit-bucket-arn>/m12-simulation-only <primary-event-rule-arn> <global-event-rule-arn> <primary-alert-topic-arn> <global-alert-topic-arn> <bounded-test-principal-arn>
```

##### G.6 — Tạo hoặc reuse managed boundary ở phase 7

Kiểm tra policy ARN trước. Nếu lệnh `get-policy` thành công, review default version trong IAM PR và **bỏ qua** lệnh `create-policy`; nếu trả `NoSuchEntity` thì mới tạo. Chỉ tạo/reuse managed policy ở bước này; **chưa attach boundary** từ daily-admin identity. Attachment mapping, rendered policy, simulation output và baseline verdict phải cùng PR:

```powershell
aws iam get-policy `
  --policy-arn arn:aws:iam::197826770971:policy/tf3-m12-operator-boundary

aws iam create-policy `
  --policy-name tf3-m12-operator-boundary `
  --policy-document file://operator-boundary.json `
  --description "Mandate 12 operator audit-control boundary"
```

##### G.7 — Deploy IAM executor ở phase 8

Copy **toàn bộ standalone executor root** `code_audit/iam_hardening/iam_change/` vào `infra/live/iam/mandate-12/iam_change/`. Copy `backend.hcl.example`/`terraform.tfvars.example` thành file local, dùng state key riêng `mandate-12/iam-change/terraform.tfstate`, điền `operator_boundary_policy_arn`, exact target user/role ARN sets, MFA-trusted security owner ARN set và giữ removal/rollback flag là `false`. Review plan phải chỉ tạo controlled executor/assume policy, không attach boundary hàng loạt và không mutate audit controls. **`terraform apply` của root này chỉ tạo executor và policy assume; nó không attach boundary vào target identities.**

```powershell
$iamChangeSource = Join-Path $taskRoot "code_audit\iam_hardening\iam_change"
if (Test-Path -LiteralPath $iamChangeDir) {
  throw "iam_change target exists: stop for ownership/import review"
}
New-Item -ItemType Directory -Path $iamChangeDir
$iamChangeFiles = @(
  ".gitignore", ".terraform.lock.hcl", "backend.hcl.example", "main.tf",
  "outputs.tf", "providers.tf", "README.md", "terraform.tfvars.example",
  "variables.tf", "versions.tf"
)
foreach ($sourceFile in $iamChangeFiles) {
  Copy-Item -LiteralPath (Join-Path $iamChangeSource $sourceFile) -Destination $iamChangeDir
}
Copy-Item -LiteralPath (Join-Path $iamChangeDir "backend.hcl.example") -Destination (Join-Path $iamChangeDir "backend.hcl")
Copy-Item -LiteralPath (Join-Path $iamChangeDir "terraform.tfvars.example") -Destination (Join-Path $iamChangeDir "terraform.tfvars")

# Điền local files từ D02/D03/D09/D11/D13 trước, giữ allow_boundary_removal=false.
$iamChangeInputs = @(
  (Join-Path $iamChangeDir "backend.hcl"),
  (Join-Path $iamChangeDir "terraform.tfvars")
)
$unresolved = Select-String -Path $iamChangeInputs -Pattern 'REPLACE_WITH|<[^>]+>|\bTODO\b|\bUnknown\b'
if ($unresolved) { $unresolved; throw "Unresolved iam_change input" }

terraform "-chdir=$iamChangeDir" init -backend-config=backend.hcl -input=false -lockfile=readonly
terraform "-chdir=$iamChangeDir" fmt -check
terraform "-chdir=$iamChangeDir" validate
if (git status --porcelain) { throw "Commit/review iam_change source before creating the plan" }
if ((terraform "-chdir=$iamChangeDir" workspace show).Trim() -ne "default") { throw "Unexpected workspace" }
if (terraform "-chdir=$iamChangeDir" state list) { throw "iam_change state is not empty" }
terraform "-chdir=$iamChangeDir" plan -var-file=terraform.tfvars -out=tfplan
terraform "-chdir=$iamChangeDir" show -no-color tfplan | Set-Content -LiteralPath (Join-Path $iamChangeDir "tfplan.txt") -Encoding utf8
Get-FileHash -Algorithm SHA256 (Join-Path $iamChangeDir "tfplan")

# Chỉ sau plan/PR/hash approval trong change window.
$approvedIamChangePlanHash = "<approved-iam-change-plan-sha256>"
$approvedIamChangeGitSha = "<approved-iam-change-git-sha>"
$actualIamChangePlanHash = (Get-FileHash -Algorithm SHA256 (Join-Path $iamChangeDir "tfplan")).Hash
if ($actualIamChangePlanHash -ne $approvedIamChangePlanHash) { throw "iam_change plan hash changed" }
if ((git rev-parse HEAD).Trim() -ne $approvedIamChangeGitSha) { throw "iam_change Git SHA changed" }
terraform "-chdir=$iamChangeDir" apply tfplan
terraform "-chdir=$iamChangeDir" output
```

Sau IAM PR approval, apply `iam_change`, lấy output và gắn policy assume **chỉ** vào named MFA owner theo mapping đã review, rồi assume executor. Không dùng root, group rộng hay `AdministratorAccess` daily identity làm executor:

```powershell
$m12ExecutorRoleArn = terraform "-chdir=$iamChangeDir" output -raw iam_change_role_arn
$m12OwnerAssumePolicyArn = terraform "-chdir=$iamChangeDir" output -raw security_owner_assume_iam_change_policy_arn

# Chọn đúng một lệnh phù hợp identity đã có trong trusted_change_owner_arns.
aws iam attach-user-policy `
  --user-name <named-mfa-security-owner-user> `
  --policy-arn $m12OwnerAssumePolicyArn

# Hoặc, nếu owner là role đã được review:
aws iam attach-role-policy `
  --role-name <named-mfa-security-owner-role> `
  --policy-arn $m12OwnerAssumePolicyArn
```

Không chạy cả hai lệnh cho cùng owner trừ khi mapping review yêu cầu; không attach vào group rộng. Lưu ARN policy/owner và change approval, không lưu credential.

Từ MFA security-owner profile đã được approve, assume executor bằng temporary credential trong **process environment**; không ghi JSON credential, secret key hoặc session token vào file/evidence:

```powershell
$m12OwnerProfile = "<approved-mfa-security-owner-profile>"
$m12MfaSerial = "<security-owner-mfa-device-arn>"
$m12ExecutorRoleArn = terraform "-chdir=$iamChangeDir" output -raw iam_change_role_arn
$m12MfaCode = Read-Host "Enter current MFA code"
$m12EnvNames = @("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
$m12PreviousEnv = @{}
foreach ($m12EnvName in $m12EnvNames) {
  $m12PreviousEnv[$m12EnvName] = [Environment]::GetEnvironmentVariable($m12EnvName, "Process")
}

$m12Session = aws sts assume-role `
  --role-arn $m12ExecutorRoleArn `
  --role-session-name "m12-iam-change-$(Get-Date -Format yyyyMMddHHmmss)" `
  --serial-number $m12MfaSerial `
  --token-code $m12MfaCode `
  --duration-seconds 3600 `
  --profile $m12OwnerProfile `
  --output json | ConvertFrom-Json

$env:AWS_ACCESS_KEY_ID = $m12Session.Credentials.AccessKeyId
$env:AWS_SECRET_ACCESS_KEY = $m12Session.Credentials.SecretAccessKey
$env:AWS_SESSION_TOKEN = $m12Session.Credentials.SessionToken
aws sts get-caller-identity
```

Lưu ARN/session name/timestamp đã redaction từ `get-caller-identity`, không lưu credentials. Giữ temporary executor session chỉ trong process hiện tại đến khi G.9 hoàn tất; không restore credential trước attachment.

##### G.8 — Attach boundary ở phase 9

Chỉ từ session executor đã assume, attach từng identity theo attachment map; capture T07 pre/event/post/hash đúng mục 8.3 bước 2 và chạy baseline + simulation trước khi chuyển identity tiếp theo:

```powershell
$m12Caller = aws sts get-caller-identity --output json | ConvertFrom-Json
$m12ExecutorRoleName = ($m12ExecutorRoleArn -split "/")[-1]
if ($m12Caller.Arn -notlike "arn:aws:sts::197826770971:assumed-role/$m12ExecutorRoleName/*") {
  throw "Current caller is not the approved Mandate 12 IAM executor"
}

aws iam put-user-permissions-boundary `
  --user-name <approved-operator-user> `
  --permissions-boundary arn:aws:iam::197826770971:policy/tf3-m12-operator-boundary

aws iam put-role-permissions-boundary `
  --role-name <approved-ci-or-operator-role> `
  --permissions-boundary arn:aws:iam::197826770971:policy/tf3-m12-operator-boundary
```

##### G.9 — Gate từng batch ở phase 9

Sau mỗi attachment, chạy workflow CI/ops đã được owner chỉ định và repeat simulation. Nếu baseline bị hỏng hoặc CI cần role assumption chưa allowlist, rollback theo IAM PR; **không** tắt/xóa audit foundation. Chỉ khi batch pass mới chuyển sang identity tiếp theo và chạy mandatory denied test.

Sau khi toàn bộ approved batch đã pass hoặc đã dừng an toàn, khôi phục process environment ngay:

```powershell
foreach ($m12EnvName in $m12EnvNames) {
  if ($null -eq $m12PreviousEnv[$m12EnvName]) {
    Remove-Item -Path "Env:$m12EnvName" -ErrorAction SilentlyContinue
  } else {
    Set-Item -Path "Env:$m12EnvName" -Value $m12PreviousEnv[$m12EnvName]
  }
}
Remove-Variable m12Session, m12MfaCode -ErrorAction SilentlyContinue
```

### 2.3 Dependency handoff manifest

Trước khi tạo PR foundation, deployer phải lập manifest trong change record/evidence store. Manifest **không chứa credential, secret value hoặc object data**; nó chỉ chứa ARN/name, nguồn lấy, owner, approval reference, timestamp UTC và trạng thái. Không commit manifest nếu có định danh nội bộ không được phép đưa vào Git.

| ID | Loại | Giá trị cần có | Lấy hoặc tạo từ đâu | Điền/dùng ở đâu | Gate |
|---|---|---|---|---|---|
| D01 | `FIXED` + `DISCOVERY` | Account `197826770971`; region `ap-southeast-1`; global-event region `us-east-1` | `sts get-caller-identity`, AWS CLI config; đối chiếu change record | Provider và evidence | Caller không phải root; đúng account/regions |
| D02 | `APPROVAL` + `DISCOVERY` | S3 state bucket, DynamoDB lock table, quyền backend | IaC owner cung cấp; `head-bucket`, `get-bucket-encryption`, `describe-table` | `backend.hcl` của cả ba root | Backend tồn tại, encrypted, owner duyệt |
| D03 | `FIXED` | Ba state key độc lập ở mục 2.1 | Mẫu `backend.hcl.example`; kiểm tra key chưa trùng state khác | Từng `backend.hcl` local | Không dùng key production hoặc dùng chung key |
| D04 | `APPROVAL` + `DISCOVERY` | Tên audit bucket mới | Security/IaC owner chọn; `head-bucket` kiểm tra candidate | Foundation `audit_bucket_name` | Không pre-create; tên không thuộc bucket hiện hữu |
| D05 | `FIXED` + `DISCOVERY` | Trail `tf3-m12-audit` | `describe-trails --include-shadow-trails` | Foundation `trail_name` | Nếu trùng/tồn tại: dừng để quyết định import/ownership |
| D06 | `APPROVAL` + `DISCOVERY` | Exact S3 object ARN prefix nhạy cảm | Inventory metadata + data-owner approval + coverage matrix | Foundation `s3_data_event_arns` | Không `*`, không audit archive; mọi asset `Unknown` phải được xử lý |
| D07 | `APPROVAL` | Email on-call và named confirmation owner | Security owner/change record | Foundation `alert_email` | Người nhận cam kết xác nhận cả hai subscription |
| D08 | `FIXED` + `APPROVAL` | Retention `365` ngày | Security/legal/budget owner duyệt | Foundation `retention_days` | Không hạ dưới 365 |
| D09 | `APPROVAL` + `DISCOVERY` | Named MFA security-owner ARN | IAM owner; với user chạy `get-user` + `list-mfa-devices`; với role phải chứng minh MFA context thực tế | `trusted_principal_arns`, `trusted_change_owner_arns` | Không root/wildcard/CI; MFA gate pass |
| D10 | `GENERATED` | Bucket/trail ARN, 2 topic ARN, 7 + 5 rule ARN, 2 confirmed subscription ARN | Chỉ lấy từ Terraform output + SNS query sau foundation apply | `audit_access/terraform.tfvars`, boundary render, evidence | Đếm/region đúng; không dùng placeholder hoặc ARN nhớ tay |
| D11 | `APPROVAL` + `DISCOVERY` | Exact target user/role ARN và baseline | IAM authorization inventory, trust/OIDC review, CI/ops owner | `iam_change/terraform.tfvars`, attachment map | Không còn target `Unknown`; strict/allowlist decision đã duyệt |
| D12 | `GENERATED` | Audit-admin/break-glass/assume-policy ARN | Output root `audit_access` | Boundary + bootstrap owner mapping | Mapping owner → policy → role được review |
| D13 | `GENERATED` + `APPROVAL` | Rendered boundary hash và managed-policy ARN | Template đã chọn, output thật, Access Analyzer, simulation; create/reuse qua change đã duyệt | `operator_boundary_policy_arn` của `iam_change` | Không placeholder; document/hash/default version khớp |
| D14 | `APPROVAL` | Cost forecast, change window, evidence path, mentor/observer, root residual acceptance | Các owner tương ứng ký trong change record | Go/No-Go và final verdict | Thiếu một mục là `NO-GO` |

Quy tắc chuyển giao: người tạo input ghi `source + timestamp`; owner ghi approval; reviewer đối chiếu input với file local; deployer chỉ đánh `CONSUMED` sau khi plan cho đúng root đã được review. Giá trị sinh sau apply không được điền trước bằng placeholder giả.

Nếu phụ thuộc chưa tồn tại, không dùng giá trị giả hoặc local-state để đi tiếp:

- thiếu backend bucket/lock table: mở change bootstrap backend riêng được IaC owner duyệt;
- thiếu named MFA security owner: hoàn tất IAM onboarding/MFA trong change riêng;
- thiếu on-call mailbox: security owner tạo/gán mailbox, owner và test receipt trước foundation;
- thiếu sensitive-data scope: data owner hoàn tất classification/coverage matrix;
- thiếu dedicated bounded test principal: tạo identity không phải workload trong IAM change riêng;
- thiếu approval hoặc owner cho bất kỳ mục nào: giữ `NO-GO`.

## 3. Go/No-Go trước PR

**GO** chỉ khi tất cả điều kiện sau đã có approval bằng văn bản:

1. AWS caller là account `197826770971`, region `ap-southeast-1`; không dùng root user.
2. Tên audit bucket mới, duy nhất toàn cầu; không tái dùng bucket cũ vì Object Lock không thể bật sau khi tạo.
3. [Coverage matrix](../m12-coverage-v1.0.md) đã ký: mọi asset nhạy cảm có owner/classification; exact approved S3 ARN khớp `s3_data_event_arns` và Terraform state đã được phân loại.
4. Security owner và email SNS đã xác định, có người xác nhận subscription sau apply.
5. Backend bucket/DynamoDB table được duyệt và state key mới là `mandate-12/audit/terraform.tfstate`.
6. IAM scope inventory không còn daily-admin/CI identity `Unknown`; branch/path cho audit-access và IAM PR, strict/allowlist decision, rollback và root residual acceptance đã được review.
7. Change window, reviewer, regional alert test plan và rollback/break-glass owner đã được chỉ định.
8. Dependency handoff manifest ở mục 2.3 có đủ D01–D14, mọi dòng là `APPROVED`; ba backend key đã được xác nhận không trùng nhau hoặc trùng state hiện hữu.
9. Named security owner/trusted change owner không nằm trong target attachment map của operator boundary; nếu không, boundary có thể tự chặn đường assume audit/executor.

**NO-GO** nếu bất kỳ input nào còn placeholder/rỗng, coverage/identity matrix còn `Unknown`, plan có resource ngoài audit scope, IAM hardening bị gộp vào PR foundation, hoặc strict boundary được dự định attach vào CI cần `sts:AssumeRole`.

## 4. Tạo branch và copy staging

Thực hiện trong bản clone được cấp quyền của repository product, tại repository root. Trước khi copy, chạy preflight chỉ đọc:

```powershell
terraform version   # phải >= 1.6
aws --version
git --version
git status --short
git rev-parse HEAD
aws sts get-caller-identity
aws configure get region
```

Lưu product Git SHA vào change record. Worktree phải sạch; caller phải là named user/assumed role trong account `197826770971`, không phải ARN `:root`; region phải là `ap-southeast-1`. Thiếu tool, sai identity/region hoặc worktree bẩn là `NO-GO`.

```powershell
git switch -c chore/mandate-12-audit-foundation

$taskRoot = "G:\XBrain\Phase3\Task_Phase3\Task_mandate_12"
$sourceDir = Join-Path $taskRoot "code_audit\foundation"
$productRepoRoot = (Get-Location).Path
$foundationDir = Join-Path $productRepoRoot "infra\live\audit"
$auditAccessDir = Join-Path $productRepoRoot "infra\live\iam\mandate-12\audit_access"
$iamChangeDir = Join-Path $productRepoRoot "infra\live\iam\mandate-12\iam_change"
$sourceFiles = @(
  ".gitignore",
  ".terraform.lock.hcl",
  "versions.tf",
  "providers.tf",
  "main.tf",
  "variables.tf",
  "outputs.tf",
  "backend.hcl.example",
  "terraform.tfvars.example"
)

if (Test-Path -LiteralPath $foundationDir) {
  throw "infra/live/audit already exists: stop for ownership/import review; do not overwrite"
}
New-Item -ItemType Directory -Path $foundationDir
foreach ($sourceFile in $sourceFiles) {
  Copy-Item -LiteralPath (Join-Path $sourceDir $sourceFile) -Destination $foundationDir
}

Set-Location $foundationDir
Copy-Item -LiteralPath backend.hcl.example -Destination backend.hcl
Copy-Item -LiteralPath terraform.tfvars.example -Destination terraform.tfvars
```

Không dùng `New-Item -Force` hoặc `Copy-Item -Force`: target tồn tại nghĩa là phải dừng để xác định ownership/import. Không copy `.terraform/`. `backend.hcl`, `terraform.tfvars`, `tfplan` và `tfplan.txt` là local/untracked; không commit. Copy và commit `.terraform.lock.hcl` của từng root; nếu init yêu cầu đổi provider/checksum trong lockfile thì dừng để reviewer xem diff.

## 5. Điền input và plan an toàn

Thay toàn bộ placeholder trong `backend.hcl` và `terraform.tfvars` bằng giá trị `APPROVED` từ manifest. `s3_data_event_arns` và `alert_email` là bắt buộc. S3 selector là phép `StartsWith`: prefix đúng có dạng `arn:aws:s3:::bucket/prefix/`; nếu data owner duyệt toàn bucket thì dạng đúng là `arn:aws:s3:::bucket/`, **không** dùng `arn:aws:s3:::bucket/*`.

Trước khi tạo plan, commit các file source/lockfile đã copy qua PR workflow và checkout đúng commit đã review. `backend.hcl`, `terraform.tfvars`, `tfplan*` phải bị ignore; worktree phải sạch. Git SHA chỉ có giá trị làm evidence khi source đã commit.

```powershell
$inputFiles = @(
  (Join-Path $foundationDir "backend.hcl"),
  (Join-Path $foundationDir "terraform.tfvars")
)
$unresolved = Select-String -Path $inputFiles -Pattern 'REPLACE_WITH|<[^>]+>|\bTODO\b|\bUnknown\b'
if ($unresolved) {
  $unresolved
  throw "Unresolved dependency/placeholder: stop before terraform init"
}

terraform "-chdir=$foundationDir" init -backend-config=backend.hcl -input=false -lockfile=readonly
terraform "-chdir=$foundationDir" fmt -check
terraform "-chdir=$foundationDir" validate
if (git status --porcelain) { throw "Commit/review foundation source before creating the plan" }
$workspace = terraform "-chdir=$foundationDir" workspace show
if ($workspace.Trim() -ne "default") { throw "Unexpected Terraform workspace: $workspace" }
$existingState = terraform "-chdir=$foundationDir" state list
if ($existingState) { throw "Foundation state is not empty: stop for ownership/import review" }
terraform "-chdir=$foundationDir" plan -var-file=terraform.tfvars -out=tfplan
terraform "-chdir=$foundationDir" show -no-color tfplan | Set-Content -LiteralPath (Join-Path $foundationDir "tfplan.txt") -Encoding utf8
Get-FileHash -Algorithm SHA256 (Join-Path $foundationDir "tfplan")
git rev-parse HEAD
```

Reviewer chỉ được thấy resource audit mới: S3 audit bucket và controls, CloudTrail, SNS, EventBridge và email subscription. **NO-GO** nếu plan thay đổi/destroy bất kỳ resource EKS, VPC, node group, CloudFront, Cloudflare, ALB, datastore, application, flagd hoặc state hiện hữu.

Lưu `tfplan.txt`, plan SHA-256 và product Git SHA làm evidence. Reviewer phải ghi chính xác hai hash/SHA đã duyệt. Không chạy `apply` khi input chưa duyệt, state không rỗng, target đã tồn tại ngoài state hoặc plan không đúng allowlist.

## 6. Apply có kiểm soát

Sau PR approval và trong change window:

```powershell
$approvedGitSha = "<approved-product-git-sha>"
$approvedPlanHash = "<approved-foundation-plan-sha256>"
$currentGitSha = git rev-parse HEAD
if ($currentGitSha.Trim() -ne $approvedGitSha) { throw "Git SHA changed after plan approval" }
$actualPlanHash = (Get-FileHash -Algorithm SHA256 (Join-Path $foundationDir "tfplan")).Hash
if ($actualPlanHash -ne $approvedPlanHash) { throw "Foundation plan hash changed after approval" }
terraform "-chdir=$foundationDir" apply tfplan
terraform "-chdir=$foundationDir" output
```

Xác nhận **cả hai** email subscription SNS. Trạng thái sau apply chỉ là `DEPLOYED/PARTIAL`; chưa phải `VERIFIED`.

## 7. Verify foundation và integrity

Chạy chỉ đọc, thay placeholder bằng output thật:

```powershell
$trailName = "tf3-m12-audit"
$trailArn = "<trail-arn-from-terraform-output>"
$auditBucket = "<audit-bucket-from-terraform-output>"
$primaryRuleArnMap = terraform "-chdir=$foundationDir" output -json anti_audit_rule_arns | ConvertFrom-Json
$globalRuleArnMap = terraform "-chdir=$foundationDir" output -json global_anti_audit_rule_arns | ConvertFrom-Json
$primaryRuleNames = @(
  $primaryRuleArnMap.PSObject.Properties.Value |
    ForEach-Object { ($_ -split "/")[-1] }
)
$globalRuleNames = @(
  $globalRuleArnMap.PSObject.Properties.Value |
    ForEach-Object { ($_ -split "/")[-1] }
)
$primaryAlertTopicArn = terraform "-chdir=$foundationDir" output -raw alert_topic_arn
$globalAlertTopicArn = terraform "-chdir=$foundationDir" output -raw global_alert_topic_arn

aws cloudtrail describe-trails --trail-name-list $trailName --region ap-southeast-1
aws cloudtrail get-trail-status --name $trailName --region ap-southeast-1
aws cloudtrail get-event-selectors --trail-name $trailName --region ap-southeast-1
aws s3api get-object-lock-configuration --bucket $auditBucket
aws s3api get-bucket-versioning --bucket $auditBucket
aws s3api get-public-access-block --bucket $auditBucket
foreach ($ruleName in $primaryRuleNames) {
  aws events describe-rule --name $ruleName --region ap-southeast-1
  aws events list-targets-by-rule --rule $ruleName --region ap-southeast-1
}
foreach ($ruleName in $globalRuleNames) {
  aws events describe-rule --name $ruleName --region us-east-1
  aws events list-targets-by-rule --rule $ruleName --region us-east-1
}
aws sns get-topic-attributes --topic-arn $primaryAlertTopicArn --region ap-southeast-1
aws sns list-subscriptions-by-topic --topic-arn $primaryAlertTopicArn --region ap-southeast-1
aws sns get-topic-attributes --topic-arn $globalAlertTopicArn --region us-east-1
aws sns list-subscriptions-by-topic --topic-arn $globalAlertTopicArn --region us-east-1
```

Gate pass khi trail là multi-region, global events + log file validation bật, `IsLogging=true`, `LatestDeliveryError` và `LatestDigestDeliveryError` rỗng, selector có management + approved S3 prefix, Object Lock là `COMPLIANCE` 365 ngày, **mọi primary/global rule từ Terraform outputs** có target SNS và **cả hai** email subscription đã `Confirmed`. Điều này chỉ chứng minh config/health, chưa chứng minh rule match runtime.

Lưu output ở cả hai region. CloudTrail global-service event có thể được ghi ở `us-east-1`, trong khi EventBridge matching/target là regional. Chưa có runtime denied IAM event + alert route ở region thực tế thì IAM tamper alert là `VERIFY-LIVE`, không phải pass.

Chờ CloudTrail delivery/digest xuất hiện (thường cần ít nhất một chu kỳ digest), rồi xác minh cryptographic integrity và lưu output làm evidence:

```powershell
$endUtc = (Get-Date).ToUniversalTime()
$startUtc = $endUtc.AddHours(-2)
aws cloudtrail validate-logs `
  --trail-arn $trailArn `
  --start-time $startUtc.ToString("yyyy-MM-ddTHH:mm:ssZ") `
  --end-time $endUtc.ToString("yyyy-MM-ddTHH:mm:ssZ") `
  --verbose | Tee-Object -FilePath m12-validate-logs.txt
```

`validate-logs` phải kết thúc không có `INVALID`/missing digest. Nếu chưa có digest hoặc delivery error thì giữ trạng thái `DEPLOYED`, không chạy mentor test.

## 8. IAM hardening và test để hoàn thành Mandate 12

Chỉ bắt đầu sau khi gate §7 (phase 5) pass: trail delivery/digest healthy, Object Lock đúng, selector có approved prefix, **cả hai** SNS subscription `Confirmed` và security owner/mentor có mặt.

### 8.0 Gate IAM trước khi tạo fixture

Thực hiện đầy đủ phases 6–9 theo mục **2.2-G.1 đến G.9** trước khi đi tiếp 8.1: deploy `audit_access`, render/validate/simulate boundary, deploy `iam_change`, attach boundary theo batch và thu bundle T07. Gate pass khi named MFA owner vào được audit roles/executor, operator thường bị deny đường audit, toàn bộ baseline batch pass và temporary executor credential đã được restore. Nếu gate này chưa pass thì **không** tạo fixture và không gọi audit-admin ở 8.2.

Sau gate 8.0, thứ tự test là 8.1 fixture → 8.2 data/secret/integrity → 8.3 anti-audit runtime → 8.4 verdict → 8.5 cleanup.

### 8.1 Tạo fixture test an toàn

Tạo fixture **sau** foundation, trong UTC window đã duyệt. Canary secret không có giá trị nghiệp vụ; canary object nằm trong prefix đã được owner duyệt để selector thực sự ghi `GetObject`.

```powershell
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$canarySecret = "tf3-m12-canary-$timestamp"
$canaryBucket = "<approved-sensitive-bucket>"
$canaryPrefix = "<approved-sensitive-prefix>"
$canaryKey = "$canaryPrefix/m12-canary-$timestamp.txt"
$canaryFile = Join-Path $env:TEMP "m12-canary-$timestamp.txt"

Set-Content -LiteralPath $canaryFile -Value "non-sensitive mandate-12 canary" -NoNewline
aws secretsmanager create-secret `
  --name $canarySecret `
  --secret-string "non-sensitive mandate-12 canary" `
  --region ap-southeast-1
aws s3 cp $canaryFile "s3://$canaryBucket/$canaryKey"
```

Ghi tên/ARN fixture và UTC timestamp vào evidence. Không dùng `sosflow/db-password`, `techx-corp-tf3/flagd-sync-token`, Terraform state, audit archive hoặc object production làm fixture.

### 8.2 Chứng minh coverage và integrity

```powershell
# Tạo event đọc; output chỉ là ARN để không hiển thị SecretString.
aws secretsmanager get-secret-value `
  --secret-id $canarySecret `
  --region ap-southeast-1 `
  --query "ARN" `
  --output text

# Tạo GetObject data event; không hiển thị nội dung object.
aws s3 cp "s3://$canaryBucket/$canaryKey" - | Out-Null
```

Chờ CloudTrail delivery. Audit-admin/read-only role lấy **bản sao local** của exact log `.json.gz` theo date-prefix; không sửa object archive. `aws s3 ls` chỉ giúp tìm key, chưa phải evidence event:

```powershell
$auditBucket = "<audit-bucket-from-terraform-output>"
$utcDatePrefix = (Get-Date).ToUniversalTime().ToString("yyyy/MM/dd")
aws s3 ls "s3://$auditBucket/AWSLogs/197826770971/CloudTrail/ap-southeast-1/$utcDatePrefix/" --recursive

$evidenceDir = "<approved-local-evidence-directory>"
$logKey = "<exact-key-ending-in-.json.gz-from-list-output>"
$logCopy = Join-Path $evidenceDir (Split-Path $logKey -Leaf)
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
aws s3 cp "s3://$auditBucket/$logKey" $logCopy

# Local-only: script decompresses/parses the downloaded copy and exports metadata only.
$taskRoot = "G:\XBrain\Phase3\Task_Phase3\Task_mandate_12"
& "$taskRoot\code_audit\tools\Export-M12CloudTrailEvidence.ps1" `
  -LogFile $logCopy `
  -EventName GetObject `
  -ResourceContains "$canaryBucket/$canaryPrefix/" `
  -OutputPath (Join-Path $evidenceDir "M12-T03-getobject-redacted.json")

& "$taskRoot\code_audit\tools\Export-M12CloudTrailEvidence.ps1" `
  -LogFile $logCopy `
  -EventName GetSecretValue `
  -ResourceContains $canarySecret `
  -OutputPath (Join-Path $evidenceDir "M12-T04-getsecretvalue-redacted.json")

Get-FileHash -Algorithm SHA256 $logCopy, `
  (Join-Path $evidenceDir "M12-T03-getobject-redacted.json"), `
  (Join-Path $evidenceDir "M12-T04-getsecretvalue-redacted.json") |
  Format-Table -AutoSize
```

`code_audit/tools/Export-M12CloudTrailEvidence.ps1` không gọi AWS, chỉ đọc log copy local, tự decompress `.json.gz`, lọc theo `-EventName` và optional `-ResourceContains`, rồi xuất metadata redacted. Nếu một log file chưa có cả hai records, tải file kế tiếp cùng UTC window; không sửa archive hoặc tự tạo record evidence. T03/T04 chỉ `PASS` khi JSON output chỉ rõ actor, session, time, region, request ID và resource của `GetObject`/`GetSecretValue`, kèm output `validate-logs`.

### 8.3 Deploy IAM hardening và test anti-audit

1. Xác nhận gate 8.0 đã pass và bundle T07 của từng attachment có đủ pre/event/post/hash. Nếu CI cần `sts:AssumeRole` nhưng strict boundary chưa có allowlist đã review/test, đây là `NO-GO`; không attach rồi “thử xem có chạy không”.
2. Với **mỗi** boundary attachment/config change quan trọng đã duyệt, tạo bundle T07 “log không mỏng” trước khi chuyển sang target tiếp theo:

   - `pre-change`: snapshot JSON của exact user/role/control bằng lệnh `get-*`/`describe-*`, kèm SHA-256;
   - `approved intent`: change ID, rendered boundary SHA-256, Terraform plan SHA-256, product Git SHA và attachment map;
   - `raw audit event`: actor/session, `eventTime`, `eventName`, `eventSource`, `awsRegion`, `requestID`, exact resource và `requestParameters`;
   - `post-change`: cùng snapshot command sau change, kèm SHA-256 và diff pre/post;
   - EventBridge invocation/SNS receipt nếu action thuộc anti-audit map.

Ví dụ cho dedicated IAM user; với role dùng `get-role` và exact role name:

```powershell
$boundedTestUser = "<approved-bounded-test-user>"
$preSnapshot = Join-Path $evidenceDir "T07-$boundedTestUser-pre.json"
$postSnapshot = Join-Path $evidenceDir "T07-$boundedTestUser-post.json"
aws iam get-user --user-name $boundedTestUser --output json |
  Set-Content -LiteralPath $preSnapshot -Encoding utf8
Get-FileHash -Algorithm SHA256 $preSnapshot, `
  (Join-Path $iamChangeDir "tfplan"), `
  "<approved-rendered-operator-boundary-path>"

# Thực hiện đúng một attachment đã duyệt qua executor ở G.8, rồi snapshot lại.
aws iam get-user --user-name $boundedTestUser --output json |
  Set-Content -LiteralPath $postSnapshot -Encoding utf8
Get-FileHash -Algorithm SHA256 $postSnapshot
Compare-Object `
  (Get-Content -LiteralPath $preSnapshot) `
  (Get-Content -LiteralPath $postSnapshot) |
  Set-Content -LiteralPath (Join-Path $evidenceDir "T07-$boundedTestUser-diff.txt")
```

Nếu thiếu pre/post snapshot, raw event không đủ xác định ai đổi gì, `requestParameters` bị thiếu/không đủ để đối chiếu intent, hoặc Git/plan/hash không khớp thì T07 là `FAIL/NO-GO`; không suy luận “CloudTrail có event là đủ”. AWS Config/config-history chỉ là fallback qua một thiết kế, chi phí và change riêng đã duyệt; tài liệu này không giả định AWS Config đang bật.

3. Tạo test map từ **cả** `terraform "-chdir=$foundationDir" output -json anti_audit_rule_arns` và `terraform "-chdir=$foundationDir" output -json global_anti_audit_rule_arns`: mỗi primary/global rule output phải có một denied API action, expected service-specific event source, EventBridge target và recipient evidence. Map là evidence bắt buộc, gồm cả rule được bổ sung sau này.
4. Từ **dedicated bounded operator identity**, sau simulation và dưới quan sát security owner, chạy test CloudTrail bằng cả hai dạng input tên và ARN để chứng minh alert không có cửa sổ lọt do request form:

```powershell
$trailName = "tf3-m12-audit"
$trailArn = terraform "-chdir=$foundationDir" output -raw trail_arn
aws cloudtrail stop-logging --name $trailName --region ap-southeast-1
aws cloudtrail stop-logging --name $trailArn --region ap-southeast-1
aws cloudtrail delete-trail --name $trailName --region ap-southeast-1
```

5. Chạy đủ các nhóm còn lại từ cùng bounded identity, chỉ trên exact audit controls/dedicated test principal đã phê duyệt:

| Nhóm rule/control | API deny tối thiểu cần map/test | Điều kiện PASS bổ sung |
|---|---|---|
| Audit S3 | Một mutation bucket audit, ví dụ `s3api delete-public-access-block --bucket <audit-bucket>` | `AccessDenied`, Object Lock/versioning/PAB sau test không đổi |
| EventBridge | `events disable-rule --name <anti-audit-rule>`; lặp map cho mọi rule output cần chứng minh | `AccessDenied`, rule/target vẫn enabled và alert receipt có timestamp |
| SNS | `sns delete-topic --topic-arn <alert-topic-arn>` hoặc subscription/policy mutation đã duyệt | `AccessDenied`, topic/subscription vẫn `Confirmed` |
| IAM boundary/policy | Detach/delete boundary hoặc policy-attachment mutation trên **dedicated bounded test principal** | `AccessDenied`, boundary/attachment không đổi |
| IAM trust path | `iam:UpdateAssumeRolePolicy` trên dedicated bounded test role sau simulation | `AccessDenied`, trust policy hash không đổi |

Với test trust path, không tạo broad trust document. Lấy **bản hiện tại** của dedicated test role làm request input; nếu policy bị cấu hình sai và request được phép, nội dung vẫn semantic-idempotent nhưng phải xử lý Critical incident:

```powershell
$boundedTestRole = "<dedicated-bounded-test-role>"
$trustPolicyInput = Join-Path $evidenceDir "current-trust-policy.json"
aws iam get-role --role-name $boundedTestRole `
  --query "Role.AssumeRolePolicyDocument" --output json |
  Set-Content -LiteralPath $trustPolicyInput -Encoding utf8
Get-FileHash -Algorithm SHA256 $trustPolicyInput
aws iam update-assume-role-policy `
  --role-name $boundedTestRole `
  --policy-document "file://$trustPolicyInput"
```

Kỳ vọng của mọi request là `AccessDenied`. Nếu bất kỳ lệnh nào thành công, dừng test, mở Critical incident và preserve evidence; không tiếp tục test hoặc tự xóa evidence. Break-glass chỉ có quyền recovery hẹp cho `StartLogging`/`EnableRule`; delete trail/topic/bucket hoặc control hỏng khác phải qua approved incident/root-custodian và Terraform recovery change riêng. Không test root, audit-admin/break-glass, workload role, object production hoặc archive object thật.

6. Với **mỗi** test map row, dùng log-copy + `Export-M12CloudTrailEvidence.ps1` để capture actor/session/error/`eventSource`/`awsRegion`, EventBridge target invocation và SNS receipt. T01/T02/T08/T09 chỉ `PASS` khi đủ deny + event + alert + control không đổi.

Ngoài ảnh/email SNS đã nhận, lấy metric EventBridge `Invocations` và `FailedInvocations` trong đúng test window cho **từng** primary/global rule. List target hay rule `ENABLED` không chứng minh target đã chạy:

```powershell
$metricEndUtc = (Get-Date).ToUniversalTime()
$metricStartUtc = $metricEndUtc.AddMinutes(-30)
$primaryRuleNames = @(
  (terraform "-chdir=$foundationDir" output -json anti_audit_rule_arns | ConvertFrom-Json).PSObject.Properties.Value |
    ForEach-Object { ($_ -split "/")[-1] }
)
$globalRuleNames = @(
  (terraform "-chdir=$foundationDir" output -json global_anti_audit_rule_arns | ConvertFrom-Json).PSObject.Properties.Value |
    ForEach-Object { ($_ -split "/")[-1] }
)
$ruleSets = @(
  @{ Region = "ap-southeast-1"; Names = $primaryRuleNames },
  @{ Region = "us-east-1"; Names = $globalRuleNames }
)
foreach ($ruleSet in $ruleSets) {
  foreach ($ruleName in $ruleSet.Names) {
    aws cloudwatch get-metric-statistics `
      --namespace AWS/Events --metric-name Invocations `
      --dimensions "Name=RuleName,Value=$ruleName" `
      --start-time $metricStartUtc.ToString("yyyy-MM-ddTHH:mm:ssZ") `
      --end-time $metricEndUtc.ToString("yyyy-MM-ddTHH:mm:ssZ") `
      --period 60 --statistics Sum --region $($ruleSet.Region)
    aws cloudwatch get-metric-statistics `
      --namespace AWS/Events --metric-name FailedInvocations `
      --dimensions "Name=RuleName,Value=$ruleName" `
      --start-time $metricStartUtc.ToString("yyyy-MM-ddTHH:mm:ssZ") `
      --end-time $metricEndUtc.ToString("yyyy-MM-ddTHH:mm:ssZ") `
      --period 60 --statistics Sum --region $($ruleSet.Region)
  }
}
```

Lưu output metric theo rule, EventBridge target invocation và email receipt. `Invocations` phải có datapoint phù hợp với action test; `FailedInvocations` không được có lỗi chưa giải thích. Metric không thay alert receipt, và email receipt không thay metric.

7. Với denied IAM action, kiểm tra region thực tế trước khi verdict; EventBridge là regional:

```powershell
$iamEventName = "DeleteUserPermissionsBoundary" # thay bằng action IAM đã chạy
foreach ($lookupRegion in @("ap-southeast-1", "us-east-1")) {
  aws cloudtrail lookup-events `
    --region $lookupRegion `
    --lookup-attributes AttributeKey=EventName,AttributeValue=$iamEventName `
    --max-results 10
}
```

Archive log copy vẫn là evidence chính. `lookup-events` chỉ hỗ trợ định vị nhanh event/region. Nếu event chỉ thấy ở `us-east-1` mà không có EventBridge/SNS route đã test ở region đó, M12-T10 là `VERIFY-LIVE`/không pass; mở change regional riêng trước mentor sign-off.

### 8.4 Evidence và verdict cuối

Theo [m12-tests-v1.6.md](../m12-tests-v1.6.md), tạo một thư mục evidence cho mỗi T01–T11 gồm UTC window, approver, observer, principal/session, command redacted, log/digest result, EventBridge/SNS/region evidence và verdict.

Chỉ đánh dấu Mandate 12 `VERIFIED` khi T01–T11 pass, `validate-logs` không có `INVALID`/missing digest, Object Lock retention 365 ngày có evidence, coverage matrix không còn asset nhạy cảm `Unknown`, IAM scope/attachment mapping hoàn chỉnh, root residual acceptance đã ký, và không có ảnh hưởng storefront/private ops/flagd. Claim phải ghi rõ giới hạn single-account: root/break-glass và continuity của toàn bộ same-account alert plane là residual risk, không phải “đã bị chặn tuyệt đối”.

### 8.5 Cleanup fixture sau evidence

Chỉ cleanup **sau** khi evidence log/alert đã hash, observer xác nhận và request IDs đã ghi vào verdict. Không dùng force delete secret hoặc xóa archive/evidence gốc.

```powershell
# Chỉ delete marker/version-aware cleanup cho canary key đã tạo ở 8.1.
aws s3api delete-object --bucket $canaryBucket --key $canaryKey

# Không dùng --force-delete-without-recovery; giữ recovery window tối thiểu 7 ngày.
aws secretsmanager delete-secret `
  --secret-id $canarySecret `
  --recovery-window-in-days 7 `
  --region ap-southeast-1

Remove-Item -LiteralPath $canaryFile -Force
```

Lưu output delete/scheduled deletion, object version/delete-marker metadata nếu có, UTC time và hash evidence vào `M12-T11`. Nếu cleanup không thành công, ghi incident/owner follow-up; không “dọn” bằng quyền root hoặc bằng cách xóa audit log.

## 9. Rollback và break-glass

Không rollback bằng cách tắt trail hoặc xóa audit bucket. Xử lý theo phase đang dừng:

| Tình huống | Hành động an toàn | Trạng thái |
|---|---|---|
| Chưa apply | Hủy plan/change; không có AWS mutation | `NO-GO` |
| Foundation apply một phần | Giữ state/evidence, sửa đúng root rồi plan/apply fix-forward; không destroy bucket/trail | `PARTIAL/INCIDENT` |
| SNS còn pending | Giữ foundation, yêu cầu đúng D07 confirmer xác nhận cả hai region; không sang IAM phase | `DEPLOYED/PARTIAL` |
| `audit_access` hoặc `iam_change` apply một phần | Dừng phase sau, preserve state/plan/hash và fix-forward trong root tương ứng | `PARTIAL/INCIDENT` |
| Boundary attachment làm hỏng baseline | Dừng batch ngay; không attach identity tiếp theo; dùng change rollback riêng đã duyệt qua executor cho đúng target | `ROLLBACK REQUIRED` |
| Alert/digest/integrity fail | Dừng test, bảo toàn log/evidence và mở incident; không tự sửa/xóa archive | `FAIL/INCIDENT` |

Rollback boundary chỉ được thực hiện bằng PR/change time-boxed riêng: đặt `allow_boundary_removal=true` trong root `iam_change`, review exact target + plan/hash, assume executor bằng MFA, gỡ boundary đúng target, chạy baseline, sau đó lập tức đưa flag về `false` bằng change tiếp theo. Không dùng root hoặc daily-admin để bypass executor.

Khi selector gây noise/cost, chỉ thu hẹp selector sau approval và vẫn giữ toàn bộ sensitive coverage đã ký. Nếu thu hẹp làm mất asset trong coverage matrix thì là `NO-GO`, không phải rollback hợp lệ.

`prevent_destroy` bảo vệ resource audit. Nếu có yêu cầu xóa vĩnh viễn, phải là change break-glass riêng được security owner phê duyệt: lưu evidence, xác nhận retention/legal hold, review PR gỡ guard, rồi mới thao tác. Không dùng nó để xử lý sự cố thường ngày.

---

**Phiên bản:** v1.8
**Cập nhật:** 18/07/2026
**Trạng thái:** READY FOR REVIEW — chưa được phép deploy
