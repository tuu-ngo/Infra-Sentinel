# Demo xuống mềm (YC#4) — 30/07/2026

Tái lập bằng một lệnh:

```sh
kubectl -n techx-tf3 port-forward svc/grafana 23000:80
bash scripts/mandate-19/shed_demo.sh <out-dir> 120 420
```

Tải: `mandate19_locustfile.py` (BrowseOverloadUser weight 9 : ProtectedCheckoutUser weight 1),
120 user, 420 giây, bắn qua **CloudFront công khai** — không phải đường tắt trong cluster.

## Kết quả

Offered **597,2 rps** ≈ **3× trần đo được** (202,4 RPS @ 1000 user).

| Route | Class | Requests | Failures | Ghi chú |
|---|---|---:|---:|---|
| `GET /api/products` | shed | 190 378 | 83 607 | **83 495 × HTTP 429** |
| `GET /` | shed | 47 358 | 20 780 | **20 769 × HTTP 429** |
| `GET /api/cart` | **protected** | 4 389 | **1** | **99,977%** |
| `POST /api/checkout` | **protected** | 4 388 | **1** | **99,977%** |
| `GET /api/products/:id` | **protected** | 4 391 | **5** | **99,886%** |

Hy sinh **104 264** request browse để giữ luồng tiền ở **99,95%**. Hệ không sập.

## Bằng chứng cơ chế

`probe.txt` — bắn tay qua CloudFront trong lúc overload:

```
GET /                        codes= 200 200 200 429 429 429 200 429   load-shed-header=yes
GET /api/products            codes= 429 429 200 200 200 429 429 429   load-shed-header=yes
GET /api/products/OLJCESPC7Z codes= 200 200 200 200 200 200 200 200   load-shed-header=no
GET /api/cart                codes= 200 200 200 200 200 200 200 200   load-shed-header=no
```

`counters.txt` — counter Envoy, chứng minh chính `local_ratelimit` chặn chứ không phải tầng khác:

| Bucket | enabled | rate_limited | ok |
|---|---:|---:|---:|
| `browse_rate_limiter` (per-route, browse_shedable) | 106 883 | **19 539** | 87 344 |
| `local_rate_limiter` (global fallback — route protected dùng cái này) | 148 919 | **0** | 148 919 |

Bucket bảo vệ luồng tiền **không chạm tới một lần nào** trong 148 919 request.

## Ảnh và video

| File | Nội dung |
|---|---|
| `timelapse.mp4` | 24 frame dashboard SLO, 1920px — **đọc được số trên panel** |
| `timelapse.gif` | bản nhẹ để dán vào PR/báo cáo; chữ nhoè, chỉ xem xu hướng |
| `frames/01-truoc-overload.png` | trước khi phóng tải |
| `frames/02-dang-overload.png` | đỉnh overload — browse **716 req/s**, `Node count Mean: 9 / Max: 9` |
| `frames/03-cuoi-overload.png` | cuối cửa sổ |

Mỗi frame có **time picker nằm trong ảnh** nên tua lại và đối chiếu được, không dựng khống.

## Hai điểm cần giải thích khi trình bày

1. **Browse success trên Grafana không tụt** khi shed hoạt động. Đúng thiết kế: 429 bị chặn
   tại Envoy nên không tới `frontend`, và `SLO.md` định nghĩa browse SLI là **non-5xx** — 429
   không phải 5xx. Shed hy sinh browse **mà không đốt error budget**.

2. **Panel *"Pod count — hot-path services"* hiện `No data`** trong mọi frame. Đó là lỗi hạ
   tầng quan sát có sẵn (cAdvisor timeout ở 7/8 node, xem ADR 0011 §"Khoảng trống quan sát"),
   **không** phải bằng chứng pod không scale. Số replica thật nằm trong `infra.txt` của từng
   stage ladder.
