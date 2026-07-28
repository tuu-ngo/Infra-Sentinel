# Postmortem 0002 - Grafana OOMKilled lặp lại / rủi ro observability

**Ngày:** 08/07/2026
**Người ghi nhận:** Toàn Nguyễn Văn
**Mức độ ảnh hưởng:** Thấp đến trung bình. Không ảnh hưởng trực tiếp storefront/checkout; ảnh hưởng khả năng quan sát hệ thống vì Grafana có thể bị restart đúng lúc cần xem dashboard/alert.
**Trạng thái:** Đang theo dõi - Grafana hiện `Running` và truy cập được qua port-forward, nhưng container chính đã có 12 lần restart, lần gần nhất là `OOMKilled`.

---

## Tóm tắt

Trong lúc review live cluster `techx-corp-tf3` ở `ap-southeast-1`, phát hiện pod Grafana vẫn đang `Running` và UI `/grafana/` trả HTTP 200 qua tunnel local, nhưng container chính `grafana` đã bị restart 12 lần. Lần restart gần nhất có `lastState.terminated.reason: OOMKilled`, `exitCode: 137`.

Đây chưa phải outage của app khách hàng, nhưng là rủi ro cho observability: nếu Grafana bị kill đúng lúc incident đang xảy ra, team có thể mất dashboard tạm thời hoặc bị chậm trong việc soi metrics/logs/traces.

## Hiện trạng lúc ghi nhận

Lệnh kiểm tra:

```powershell
kubectl --kubeconfig .\review-kubeconfig.tmp -n techx-tf3 get pod -l app.kubernetes.io/name=grafana -o wide
kubectl --kubeconfig .\review-kubeconfig.tmp -n techx-tf3 describe pod grafana-6db75489fb-t695t
```

Kết quả chính:

- Pod: `grafana-6db75489fb-t695t`
- Namespace: `techx-tf3`
- Status: `Running`
- Ready: `4/4`
- Node: `ip-10-0-45-62.ap-southeast-1.compute.internal`
- UI qua tunnel: `http://localhost:8080/grafana/` trả HTTP 200
- Container chính `grafana`:
  - Ready: `True`
  - Restart Count: `12`
  - Last State: `Terminated`
  - Last Reason: `OOMKilled`
  - Exit Code: `137`
  - Last Started: `2026-07-08 14:55:45 +0700`
  - Last Finished: `2026-07-08 15:12:47 +0700`
  - Current Started: `2026-07-08 15:12:47 +0700`
  - Memory limit/request: `300Mi`
  - `GOMEMLIMIT`: `314572800`

Events gần nhất có readiness probe fail:

```text
Warning Unhealthy pod/grafana-6db75489fb-t695t
Readiness probe failed: Get "http://10.0.35.174:3000/api/health": dial tcp 10.0.35.174:3000: connect: connection refused
```

## Giải thích OOMKilled

`OOMKilled` nghĩa là container dùng vượt memory limit mà Kubernetes/cgroup cấp cho nó. Kernel kill process, kubelet ghi lại `exitCode: 137`, sau đó Kubernetes restart container theo policy của pod.

Trong sự cố này, container `grafana` có memory limit `300Mi`. Grafana 13.0.1 đang chạy kèm:

- plugin `grafana-opensearch-datasource`
- dashboard provisioning
- datasource provisioning
- alert provisioning
- nhiều dashboard JSON trong chart
- các sidecar `grafana-sc-alerts`, `grafana-sc-dashboard`, `grafana-sc-datasources`

Các sidecar không restart, nhưng container Grafana chính restart 12 lần. Giả thuyết khả năng cao: `300Mi` quá thấp cho Grafana + plugin + provisioning load hiện tại.

## Ảnh hưởng

Không thấy ảnh hưởng trực tiếp đến Storefront:

- Storefront `/`: HTTP 200 qua tunnel
- Grafana `/grafana/`: HTTP 200 sau khi container tự restart
- Jaeger `/jaeger/ui/`: HTTP 200
- Load Generator `/loadgen/`: HTTP 200
- Tất cả pod trong namespace `techx-tf3` đang `Running`

Rủi ro nằm ở mặt vận hành:

- Dashboard có thể gián đoạn trong vài chục giây/phút khi Grafana restart.
- Nếu có incident thật, team có thể mất công cụ quan sát chính đúng thời điểm cần xem.
- Nếu không có alert restart/OOMKilled độc lập với Grafana, việc này dễ bị bỏ qua.

## Nguyên nhân tạm thời

Chưa kết luận root cause tuyệt đối vì chưa có metrics memory theo thời gian (`kubectl top pods` báo `Metrics API not available`). Dựa trên bằng chứng hiện có, nguyên nhân khả năng cao là memory limit của container `grafana` quá thấp so với workload observability hiện tại.

Bằng chứng:

- `lastState.terminated.reason: OOMKilled`
- `exitCode: 137`
- container `grafana` restart 12 lần, các sidecar restart 0
- memory limit/request của container chính chỉ `300Mi`
- Grafana đang có plugin OpenSearch và provisioning sidecar/dashboard

## Những việc chưa làm trong lần ghi nhận này

Theo yêu cầu "chỉ soi, không sửa", chưa thực hiện:

- Chưa tăng memory limit Grafana.
- Chưa helm upgrade.
- Chưa restart pod.
- Chưa cài Metrics Server.
- Chưa thay đổi dashboard/plugin/sidecar.

## Khuyến nghị tiếp theo

1. Tăng memory limit/request cho container `grafana` lên mức an toàn hơn, ví dụ bắt đầu từ `512Mi` hoặc `768Mi`, rồi theo dõi restart/memory thực tế.
2. Bật Metrics Server hoặc một đường quan sát memory pod để có `kubectl top pods` và dashboard memory live.
3. Tạo alert độc lập cho `kube_pod_container_status_restarts_total` và OOMKilled, không chỉ phụ thuộc vào Grafana UI.
4. Xem lại số lượng dashboard/provisioning và plugin OpenSearch nếu Grafana tiếp tục tăng memory.
5. Cập nhật Helm values tracked, tránh chỉ sửa bằng `--set` tạm thời làm drift với repo.

## Lệnh kiểm tra lại

```powershell
kubectl --kubeconfig .\review-kubeconfig.tmp -n techx-tf3 get pod -l app.kubernetes.io/name=grafana -o wide
kubectl --kubeconfig .\review-kubeconfig.tmp -n techx-tf3 describe pod grafana-6db75489fb-t695t
kubectl --kubeconfig .\review-kubeconfig.tmp -n techx-tf3 get events --sort-by=.lastTimestamp
```

Nếu Metrics API được bật:

```powershell
kubectl --kubeconfig .\review-kubeconfig.tmp -n techx-tf3 top pod grafana-6db75489fb-t695t
```

Kiểm tra UI:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8080/grafana/ -TimeoutSec 10
```
