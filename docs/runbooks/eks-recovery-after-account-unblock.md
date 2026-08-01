# Runbook — Khôi phục cluster sau khi AWS mở khóa account

**Khi nào dùng:** sau khi AWS Support mở khóa account (sự cố postmortem 0002 — account hold +
mất bastion). Mục tiêu: dựng lại bastion, khôi phục đường vào, verify toàn hệ thống.

**Điều kiện tiên quyết:** account đã ACTIVE trở lại (verify: `aws sts get-caller-identity` OK và
`aws ec2 describe-account-attributes` không lỗi block). KHÔNG chạy runbook này khi account còn hold.

---

## Bước 0 — Xác nhận account đã mở
```bash
# Không còn lỗi "account blocked" khi thử 1 thao tác tạo nhẹ (dry-run):
aws ec2 run-instances --dry-run --image-id ami-xxxx --instance-type t3.micro --region ap-southeast-1
# Kỳ vọng: "DryRunOperation" (được phép), KHÔNG phải "Blocked".
```

## Bước 1 — Merge PR #41 (vá AMI footgun) TRƯỚC khi apply
Phải merge [PR #41](https://github.com/tuu-ngo/Phase3-TF3-Infra-Sentinel/pull/41)
(`lifecycle { ignore_changes = [ami] }`) vào main **trước**, nếu không lần apply tới lại dựng
bastion trên AMI mới nhất rồi tiếp tục drift. (Không sao về mặt access — chỉ để sạch state.)

## Bước 2 — Terraform apply để dựng lại bastion
```bash
# Qua CI (khuyến nghị): merge 1 PR đụng infra/ → terraform-apply.yml chạy → approve gate production.
# HOẶC thủ công (nếu cần gấp), từ infra/:
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan     # ĐỌC KỸ: chỉ nên thấy aws_instance.bastion + cloudfront được tạo/sửa
terraform apply tfplan
```
> ⚠️ Đọc plan: xác nhận KHÔNG có resource nào ngoài bastion (+CloudFront nếu cần) bị destroy/replace.

## Bước 3 — Lấy thông tin bastion mới + mở tunnel
```bash
terraform output ssm_tunnel_command     # lệnh đã điền sẵn bastion id mới
# Chạy lệnh đó (giữ terminal), rồi terminal khác:
aws eks update-kubeconfig --name techx-corp-tf3 --region ap-southeast-1
kubectl config set-cluster arn:aws:eks:ap-southeast-1:012619468490:cluster/techx-corp-tf3 \
  --server=https://localhost:8443 --insecure-skip-tls-verify=true
kubectl get nodes    # phải thấy 3 node Ready
```

## Bước 4 — Verify workload + ArgoCD
```bash
kubectl -n argocd get applications          # techx-corp / infra / bootstrap = Synced/Healthy
kubectl -n techx-tf3 get pods               # tất cả Running
kubectl -n techx-tf3 get deploy             # nhóm checkout 2/2 (REL-01)
kubectl -n techx-tf3 get pdb                # 10 PDB, ALLOWED DISRUPTIONS >=1
aws eks list-addons --cluster-name techx-corp-tf3 --region ap-southeast-1  # coredns/kube-proxy/vpc-cni managed
```

## Bước 5 — Verify public storefront sống lại
```bash
# CloudFront phải resolve lại ra IP + trả HTTP 200:
nslookup d1a89tvsgnjen6.cloudfront.net 8.8.8.8       # phải có Address
curl -s -o /dev/null -w "%{http_code}\n" https://d1a89tvsgnjen6.cloudfront.net/   # 200
```
> Nếu CloudFront vẫn chưa resolve sau khi account mở vài phút: kiểm tra distribution status
> (`aws cloudfront get-distribution`), có thể cần 1 apply/re-enable nhẹ.

## Bước 6 — Kiểm tra mất mát dữ liệu (nếu node từng bị terminate)
Nếu trong lúc hold node bị AWS terminate và tái tạo: datastore in-cluster (0 PVC) đã mất dữ liệu.
Kiểm tra `product-catalog`/`accounting` có dữ liệu không; nếu mất → đây là hệ quả REL-10, ghi nhận
và ưu tiên PVC/managed DB (ADR 0002) ngay sau khôi phục.

## Bước 7 — Đóng postmortem
Cập nhật `docs/postmortem/0002-*` trạng thái → Đã đóng, ghi thời điểm khôi phục + có mất dữ liệu không.

---
## Nhắc lại 2 điều để không lặp lại
- **Đọc `terraform plan` trước khi approve** — bắt các replace/destroy nhạy cảm.
- **Dựng AWS billing/Budget alert** — account hold lần này vì payment; đừng để bị bất ngờ nữa.
