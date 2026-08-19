# Postmortem 0017 — `product-catalog` về 0 replica, HPA không tự cứu được

**Ngày:** 30/07/2026
**Người viết:** CDO01 — TF3
**Mức độ:** Sự cố người dùng thấy được — `/api/products` và `/api/products/<id>` trả HTTP 500
**Thời lượng:** ~08:21Z → 09:03Z (≈ 42 phút), trong đó ~40 phút là phát hiện + chẩn đoán,
~2 phút khôi phục sau khi có quyền ghi.
**Phát hiện bởi:** CDO01, trong lúc kiểm tra Service headless sau khi merge PR #658/#660.

## Ảnh hưởng

| Route | Trạng thái trong sự cố |
|---|---|
| `GET /api/products` | **HTTP 500** |
| `GET /api/products/<id>` | **HTTP 500** |
| `GET /` | 200 (trang chủ không gọi product-catalog trực tiếp) |
| `GET /api/cart` | 200 |
| `POST /api/checkout` | 200 — luồng tiền **không** bị ảnh hưởng |

Danh mục sản phẩm không tải được. Không mất dữ liệu.

## Diễn biến (UTC)

| Giờ | Việc |
|---|---|
| 07:50 | Field manager `kubectl-rollout` cập nhật Deployment `product-catalog` |
| ~08:21 | Event: `Scaled down replica set product-catalog-694b86d8fb from 2 to 0`; `poddisruptionbudget/product-catalog-pdb: No matching pods found` |
| 08:38 | `argocd-controller` + `kube-controller-manager` cập nhật Deployment (sync commit `5d4f85b`) |
| ~08:40 | Phát hiện `product-catalog 0/0` khi kiểm tra endpoint của Service headless |
| 08:42 | Xác nhận `/api/products` = 500 qua CloudFront |
| 08:45 | `kubectl scale` bị từ chối — kubeconfig hardcode profile readonly (xem §"Điều làm chậm khắc phục") |
| 09:01 | Scale về 2 thành công bằng `--token` sinh từ profile `acc-moi` |
| 09:02 | Pod Ready 2/2, nhưng `/api/products` **vẫn 500** |
| 09:03 | Tự hồi phục — kênh gRPC của frontend thoát backoff sau ~60 giây |

## Nguyên nhân

### Vì sao không tự hồi phục — đã xác định chắc chắn

`spec.replicas = 0` làm HPA **ngừng hoạt động hoàn toàn**. HPA coi `replicas: 0` là
"autoscaling đã tắt" và không bao giờ scale từ 0 lên, kể cả khi `minReplicas: 2`. Nó hiển thị
`cpu: <unknown>` vì không còn pod nào để đo — vòng luẩn quẩn tự khoá.

**GitOps cũng không có đòn bẩy.** Template chart bỏ hẳn field `replicas` khi
`replicasManagedExternally: true`:

```gotemplate
{{- if not .replicasManagedExternally }}
replicas: {{ .replicas | default .defaultValues.replicas }}
{{- end }}
```

Không có `replicas` trong desired state ⇒ ArgoCD không có gì để khôi phục, selfHeal vô dụng.
`kubectl scale` là đòn bẩy **duy nhất** — tức một thao tác thủ công, trái quy ước "không apply
tay" của repo, nhưng là lối thoát duy nhất.

Kiểm chứng: `spec.replicas` hiện **không thuộc sở hữu của manager nào**. Cả bốn manager
(`helm`, `kubectl-rollout`, `argocd-controller`, `kube-controller-manager`) đều không khai
`f:replicas` trong `managedFields`. Field mồ côi, đứng yên ở giá trị cuối cùng ai đó để lại.

### Vì sao về 0 — CHƯA xác định

Không kết luận được từ dữ liệu hiện có. Ghi lại những gì biết và những gì loại trừ:

| Giả thuyết | Trạng thái |
|---|---|
| ArgoCD gỡ field `replicas` khi sync | **Loại**. Gỡ `replicas` khỏi Deployment thì API server áp mặc định **1**, không phải 0. |
| HPA scale xuống 0 | **Loại**. `minReplicas: 2`, và HPA không có quyền xuống dưới min. |
| Argo Rollouts `scaleDown: progressively` | **Chưa loại hẳn**. Cơ chế này CÓ đưa Deployment được tham chiếu về 0, nhưng Rollout duy nhất đang tồn tại (`checkout-rollout`) trỏ vào `checkout`, không phải `product-catalog`. |
| Thao tác tay của người khác | **Chưa loại**. Manager `kubectl-rollout` xuất hiện lúc 07:50Z. |

Cần EKS audit log để chốt. Chưa truy được ở thời điểm viết.

**Không đổ lỗi cho việc merge PR #658/#660.** Thời điểm `argocd-controller` cập nhật (08:38Z)
trùng với sync commit `5d4f85b`, nhưng scale-down xảy ra **trước đó ~17 phút** (08:21Z) và cả
hai PR đều không đụng gì tới `product-catalog`. Trùng thời điểm không phải nguyên nhân.

## Điều làm chậm khắc phục

`~/.kube/config` **hardcode profile readonly bên trong `exec.env`** cho cluster
`197826770971`:

```yaml
env:
- name: AWS_PROFILE
  value: nvtank-readonly
```

Biến `AWS_PROFILE` đặt ở shell **không thắng được** giá trị này — kubectl luôn gọi
`aws eks get-token` bằng profile readonly. Người vận hành làm đúng theo CLAUDE.md
(`export AWS_PROFILE=acc-moi`) vẫn nhận `Forbidden`, và thông báo lỗi không hề gợi ý vì sao.

Cách đi vòng đã dùng:

```sh
kubectl -n techx-tf3 scale deploy product-catalog --replicas=2 \
  --token="$(AWS_PROFILE=acc-moi aws eks get-token --cluster-name techx-corp-tf3 \
    --region ap-southeast-1 --output json | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"]["token"])')"
```

## Vì sao 500 kéo dài thêm 60 giây sau khi pod đã Ready

Kênh gRPC của `frontend` kẹt ở `TRANSIENT_FAILURE` với exponential backoff:

```
14 UNAVAILABLE: No connection established.
Last error: connect ECONNREFUSED 172.20.145.185:8080
```

`172.20.145.185` là ClusterIP của `product-catalog`. Client giữ **một** subchannel tới VIP đó
và chỉ thử lại theo backoff, nên dù endpoint đã sẵn sàng, người dùng vẫn thấy 500 thêm ~60 giây.

Đây chính là điểm yếu mà Mandate #19 đã đo được và đang xử (ADR 0011 §3.2): `round_robin` trên
Service headless + `dns_min_time_between_resolutions_ms: 5000` rút ngắn đáng kể cửa sổ này, vì
client giữ nhiều subchannel và phân giải lại DNS nhanh hơn.

## Rủi ro còn lại — 9 service khác cùng cơ chế

`replicasManagedExternally: true` đang bật cho: `ad`, `frontend`, `product-catalog`, `cart`,
`checkout`, `currency`, `product-reviews`, `recommendation`, `frontend-proxy`, `email`.

**Mọi service trong danh sách này đều có cùng lỗ hổng**: nếu `spec.replicas` bị đưa về 0 vì bất
kỳ lý do gì, HPA không cứu được và GitOps cũng không. `frontend` hoặc `frontend-proxy` rơi vào
trạng thái này là mất toàn bộ storefront.

## Hành động

| # | Việc | Chủ | Trạng thái |
|---|---|---|---|
| 1 | Khôi phục `product-catalog` về 2 replica | CDO01 | ✅ xong |
| 2 | Truy EKS audit log để chốt ai set 0 | CDO01 | mở |
| 3 | Cảnh báo `spec.replicas == 0` trên service hot path. **Chặn:** kube-state-metrics chưa cài (`kube_deployment_spec_replicas` không tồn tại), và cAdvisor chết 7/8 node — xem ADR 0011 §"Khoảng trống quan sát" | CDO01 | mở |
| 4 | Sửa `~/.kube/config`: bỏ `AWS_PROFILE` hardcode trong `exec.env`, hoặc thêm context riêng cho `acc-moi` | CDO01 | mở |
| 5 | Cập nhật CLAUDE.md: `export AWS_PROFILE=acc-moi` **không đủ** cho thao tác ghi; ghi lại cách dùng `--token` | CDO01 | mở |
| 6 | Xem xét lại `replicasManagedExternally`: nên để chart render `replicas` bằng đúng `minReplicas` của HPA và đưa `/spec/replicas` vào `ignoreDifferences`, để giá trị mặc định khi field bị reset là **min chứ không phải 0** | CDO01 | mở — cần thiết kế, không vá vội |

## Điều làm đúng

- Luồng tiền không gián đoạn: `cart` và `checkout` giữ 200 suốt sự cố.
- PDB phát tín hiệu đúng (`No matching pods found`) ngay tại thời điểm scale-down — nếu có
  cảnh báo gắn vào sự kiện này thì đã phát hiện sớm hơn 20 phút.

---

**Ký:** CDO01 — TF3 · 30/07/2026
