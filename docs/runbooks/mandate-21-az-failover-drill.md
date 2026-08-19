# Runbook — Diễn tập mất AZ **1c** dưới tải (Mandate 21)

**Mục tiêu:** chứng minh **mất trọn AZ `ap-southeast-1c` một cách bất ngờ, dưới tải** mà luồng
browse → cart → checkout **phục hồi trong RTO cam kết** và **0 mất đơn** (RPO=0).
**AZ mục tiêu:** `ap-southeast-1c` — **AZ tệ nhất** (xem §1) · **Thời lượng fault:** `PT5M` · **Chủ trì:** CDO-02
**Công cụ:** AWS FIS — template `aws_fis_experiment_template.az_connectivity_loss` với
`fis_target_az=ap-southeast-1c` (`infra/live/production/fis-chaos-experiments.tf`).

> Kế thừa runbook Mandate 17 (`mandate-17-fis-az-drill.md`, drill 1b). File này chỉ ghi **khác biệt
> cho 1c** + cách đo RTO/RPO của Mandate 21. Nguyên tắc an toàn, tiêu chí ABORT, bảng evidence: theo M17.

---

## 1. Vì sao 1c là AZ tệ nhất (đo live 30/07)

| Thành phần | Ở 1c? | Hệ quả khi mất 1c |
|---|---|---|
| **RDS primary** | ✅ (secondary 1b) | **Multi-AZ failover primary→1b** — đây là RTO driver chính |
| **frontend** | 2/3 replica (sau khi sửa GAP 1) | còn 1 replica @1a + HPA scale; **KHÔNG** còn dồn 100% (đã sửa) |
| **ElastiCache** | replica `002` | primary `001`@1b vẫn chủ → **không cần failover**, cart không gián đoạn |
| **MSK** | 1/3 broker | còn 2 broker; RF=3 nên không mất message |
| **otel-gateway** | 1/2 replica (`2mzcm`) | ⚠️ counter đo blip — xem §4 |
| **cloudflared** | 1/2 replica | còn replica @1a → storefront vẫn vào được |

Mất 1c kích hoạt **nhiều failover nhất** (RDS + frontend reschedule + broker loss) → nếu chịu được 1c,
gần như chịu được 1a/1b. Ma trận đầy đủ 3 AZ: xem ADR 0017.

**Quan sát observability (thuận cho 1c):** Prometheus @**1b**, Grafana @**1a** — **cả hai ngoài 1c** → không
mù khi bắn. (Ngược với M17 bắn 1b phải dời Prometheus trước.) **Vẫn phải verify lại trước mỗi lần bắn** —
observability chạy emptyDir, có thể bị dời chỗ.

---

## 2. Preflight (T-30 phút)

```sh
export AWS_PROFILE=techx-new; export MSYS_NO_PATHCONV=1
SP=./drill-evidence/m21-1c && mkdir -p $SP

# 2.1 FIS đã apply chưa (template + alarm phải tồn tại, alarm OK)
TPL=$(aws fis list-experiment-templates --region ap-southeast-1 \
  --query "experimentTemplates[?tags.Name=='tf3-m17-az-connectivity-loss'].id" --output text)
echo "TPL=$TPL"   # rỗng => chạy: terraform apply "tfplan-fis-1c"
aws cloudwatch describe-alarms --alarm-names tf3-fis-stop-storefront-5xx \
  --region ap-southeast-1 --query "MetricAlarms[].StateValue" --output text   # phải OK

# 2.2 Template đang nhắm ĐÚNG subnet 1c (không phải 1b mặc định)
aws fis get-experiment-template --id "$TPL" --region ap-southeast-1 \
  --query "experimentTemplate.targets" --output json   # subnet phải = private-1c

# 2.3 Money-path spread — mỗi service phải có >=1 replica NGOÀI 1c
kubectl get nodes -o json > $SP/nodes.json
kubectl get pods -n techx-tf3 -o json | python scripts/ops/az-spread-check.py $SP/nodes.json | tee $SP/spread-before.txt
# BẮT BUỘC: "0 money-path workload(s) confined to a single AZ" và không service nào 100% ở 1c

# 2.4 Observability + load-gen KHÔNG ở 1c
for l in prometheus grafana; do
  N=$(kubectl -n techx-tf3 get pods -l app.kubernetes.io/name=$l --field-selector status.phase=Running -o jsonpath='{.items[0].spec.nodeName}')
  echo "$l -> $N -> $(kubectl get node $N -o jsonpath='{.metadata.labels.topology\.kubernetes\.io/zone}')"
done
kubectl -n techx-tf3 get pod -l 'app.kubernetes.io/name in (load-generator,locust-bench)' -o wide

# 2.5 Baseline store
aws rds describe-db-instances --region ap-southeast-1 \
  --query "DBInstances[?DBInstanceIdentifier=='techx-tf3-postgres'].{AZ:AvailabilityZone,Secondary:SecondaryAvailabilityZone,MultiAZ:MultiAZ}" --output table | tee $SP/rds-before.txt
# kỳ vọng: primary 1c, secondary 1b — sau drill primary phải đổi thành 1b
```

**Chốt:** nếu §2.3 fail (còn service dồn 1c) → **dừng, sửa placement trước** (vd `kubectl rollout restart`
service đó khi có node lành ở AZ khác). Bài test sẽ fail vì lý do biết trước, đừng bắn.

---

## 3. T-5 phút — bật thu thập (3 nguồn độc lập)

**Terminal A — harness Prometheus (RTO + SLO):**
```sh
kubectl port-forward -n techx-tf3 svc/prometheus 9090:9090 &
python scripts/ops/az-drill-measure.py --interval 5 --out ./drill-evidence/m21-1c/sli.csv
# In liên tục checkout/browse/cart success, rate, p95, order counter; SLO breach đánh dấu ***
```

**Terminal B — vòng curl ngoài (RTO chính xác, góc khách hàng — bằng chứng mạnh nhất):**
```sh
while true; do
  printf '%s %s %s\n' "$(date -u +%FT%TZ)" \
    "$(curl -s -o /dev/null -w '%{http_code} %{time_total}' --max-time 10 https://d2tn71186d7ilz.cloudfront.net/)" \
    "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://d2tn71186d7ilz.cloudfront.net/api/products)"
  sleep 2
done | tee ./drill-evidence/m21-1c/external-probe.log
```

**Terminal C — lệnh dừng khẩn, gõ sẵn KHÔNG Enter:**
```sh
aws fis stop-experiment --id <EXPERIMENT_ID> --region ap-southeast-1
```

**Terminal D** — Grafana SLO dashboard (request rate / success / p95 / node count) để quay màn hình.
**Tải:** giữ locust/load-generator ở mức ổn định (ghi lại mức user). Lưu ý 2/3 locust nằm ở 1c sẽ rụng —
load-generator@1b + 1 locust@1a vẫn chạy; nếu muốn giữ nguyên mức tải, cân nhắc scale locust ra 1a/1b trước.

---

## 4. Đo RTO / RPO — cách chốt số

**RTO (bao lâu luồng ra tiền phục hồi):**
- **Nguồn chính = external-probe.log**: RTO = từ timestamp 5xx/timeout đầu tiên → tới khi 200 ổn định trở lại.
  Đây là góc khách hàng, không smoothing.
- **Nguồn phụ = sli.csv**: cột `checkout_slo_ok` chuyển 0 rồi về 1. Lưu ý window 90s làm dip/recover **giãn ~90s**
  → dùng để kể chuyện SLO trên dashboard, KHÔNG dùng làm con số RTO chính (nó bi quan hơn thực tế).
- Mốc tham chiếu: **RDS failover** thường 60–120s. Kỳ vọng RTO checkout ≈ cửa sổ failover RDS.

**RPO (mất đơn — kỳ vọng 0):**
- ⚠️ **KHÔNG chỉ tin `sum(app_confirmation_counter_total)`**: otel-gateway có 1 replica ở 1c; khi nó chết,
  series counter re-route sang gateway 1a → sum **blip** (artifact đo, không phải mất đơn).
- **Tín hiệu RPO đáng tin:**
  1. **checkout PlaceOrder error** trong cửa sổ (span metrics đi qua gateway 1a còn sống): lỗi phải ~0 hoặc
     chỉ trong đúng cửa sổ RDS failover, và request lỗi được retry (REL-02/REL-09) → không đơn nào bị nuốt.
  2. **Counter đơn phục hồi sau drill**: sau khi 1c về + gateway 1c chạy lại, `orders_confirmed` phải **vượt
     baseline** và tiếp tục tăng đều — không mất mảng.
  3. **Ground-truth (khuyến nghị)**: đếm đơn trong RDS trước/sau (accounting), so với số checkout thành công
     load-gen phát. RDS Multi-AZ replicate **đồng bộ** → mọi đơn đã commit sống sót failover ⇒ RPO=0 theo thiết kế.

---

## 5. Bắn (T-0)

```sh
aws fis start-experiment --experiment-template-id "$TPL" --region ap-southeast-1 \
  --tags Name=m21-az1c-drill | tee ./drill-evidence/m21-1c/experiment-start.json
EXP=$(python -c "import json;print(json.load(open('./drill-evidence/m21-1c/experiment-start.json'))['experiment']['id'])")
echo "EXPERIMENT_ID=$EXP"   # dán ngay vào Terminal C
```
Ghi **giờ UTC chính xác lúc bắn**. Mọi mốc sau đối chiếu theo nó.

### 5.1. ⚠️ RDS KHÔNG tự failover dưới NACL partition — phải trigger tay (đo drill 31/07)

FIS `disrupt-connectivity` blackhole subnet bằng NACL. **ElastiCache tự failover** trên cú này (cart hồi
~52s nhờ REL-17-07). Nhưng **RDS Multi-AZ (instance) KHÔNG tự failover** — AWS health-check nội bộ không
coi NACL của khách là AZ failure, nên product-catalog/checkout (đọc/ghi RDS-1c) 5xx suốt fault → stop-alarm
tự abort. **AZ chết thật (mất điện/hardware) thì AWS tự trigger**; drill NACL thì phải mô phỏng bằng tay,
**ngay khi fault ăn vào (~T+40s)** để rút cửa sổ 5xx trước khi stop-alarm bắt:
```sh
aws rds reboot-db-instance --db-instance-identifier techx-tf3-postgres --force-failover \
  --region ap-southeast-1
# RDS failover ~56s; verify primary đổi AZ:
aws rds describe-db-instances --region ap-southeast-1 \
  --query "DBInstances[?DBInstanceIdentifier=='techx-tf3-postgres'].{az:AvailabilityZone,sec:SecondaryAvailabilityZone}" --output text
```
> ⚠️ `describe-db-instances` có thể **lag** hiển thị AZ cũ vài phút sau failover. Bằng chứng tin cậy hơn:
> `/api/products` hồi 200 **khi 1c vẫn blackhole** = DB đã rời 1c. Xem event `Multi-AZ failover completed`.

**Trong 5 phút, cần thấy:**
| Mốc | Kỳ vọng |
|---|---|
| ~30–60s | node 1c `NotReady`; endpoint 1c gỡ khỏi Service; RDS bắt đầu failover |
| 60–120s | RDS primary đổi sang **1b**; checkout error (nếu có) hồi; frontend HPA có thể thêm pod @1a |
| 1–3 phút | external-probe **vẫn 200** (hoặc chỉ vài 5xx trong cửa sổ failover rồi hồi); traffic dồn AZ lành |
| suốt bài | checkout ≥99%, browse/cart ≥99.5%, p95<1s (đo sau khi ra khỏi cửa sổ failover) |

Chụp trong lúc chạy: `kubectl get nodes -o wide`, `kubectl -n techx-tf3 get pods -o wide`,
`kubectl -n techx-tf3 get endpoints` → thư mục evidence.

---

## 6. Sau drill (T+5 → T+20)

```sh
aws fis get-experiment --id $EXP --region ap-southeast-1 | tee ./drill-evidence/m21-1c/experiment-final.json
# RDS primary đã đổi 1c->1b?
aws rds describe-db-instances --region ap-southeast-1 \
  --query "DBInstances[?DBInstanceIdentifier=='techx-tf3-postgres'].{AZ:AvailabilityZone,Secondary:SecondaryAvailabilityZone}" --output table | tee ./drill-evidence/m21-1c/rds-after.txt
# node/pod hồi phục, không pod lỗi
kubectl get nodes -o wide | tee ./drill-evidence/m21-1c/nodes-after.txt
kubectl -n techx-tf3 get pods --no-headers | awk '$3!="Running" && $3!="Completed"' | tee ./drill-evidence/m21-1c/abnormal-after.txt
# NACL 1c đã được FIS trả nguyên trạng chưa (xác nhận bằng mắt)
aws ec2 describe-network-acls --region ap-southeast-1 \
  --filters Name=association.subnet-id,Values=subnet-0fdf5cd134c155b94 \
  --query "NetworkAcls[].{Id:NetworkAclId,Default:IsDefault}" --output table | tee ./drill-evidence/m21-1c/nacl-after.txt
# dừng harness (Ctrl-C ở Terminal A) -> in DRILL SUMMARY (RTO/RPO)
```

**Chốt hồi phục:** mọi pod `Running`; storefront `200`; NACL 1c về bản gốc; RDS `available` (primary giờ 1b —
bình thường, **không cần failback ngay**, hoặc lên lịch failback ngoài giờ nếu muốn primary về 1c).

---

## 7. ABORT (dừng ngay, không hỏi)

Theo M17 §7, thêm cho 1c:
| Dấu hiệu | Hành động |
|---|---|
| external-probe 5xx liên tiếp **>90s** (dài hơn cửa sổ failover RDS bình thường) | `stop-experiment` |
| RDS **không** failover sau 180s (kẹt ở 1c unreachable) | `stop-experiment` + kiểm RDS event |
| checkout success <99% kéo dài >2 phút (quá cửa sổ failover) | `stop-experiment` |
| Alarm `tf3-fis-stop-storefront-5xx` → ALARM | FIS tự dừng — xác nhận rollback |
| Mất kết nối kubectl **và** Grafana (mù hoàn toàn) | `stop-experiment` |

---

## 8. Nếu FAIL

Không sửa vội. Ghi chính xác cái gì gãy + lúc nào, xác nhận rollback sạch, phân loại **thiết kế** (thiếu
replica/AZ, elastic thiếu node ở AZ lành để HPA scale) vs **cấu hình** (probe/PDB/DNS/retry). Mở finding
`REL-21-xx`, sửa, **drill lại**. Chuỗi *phát hiện → sửa → drill lại* được đánh giá cao hơn một lần chạy đẹp.

> Rủi ro đã biết trước drill (ghi trong ADR 0017, không giấu): **elastic pool chỉ có node ở 1a+1c, không ở
> 1b** → mất 1c thì HPA frontend chỉ còn node elastic 1a để scale; nếu 1a hết chỗ, pod Pending → capacity
> giảm. Đây là đánh đổi cost có chủ đích; drill để đo RTO thật ở mức capacity hiện có.
