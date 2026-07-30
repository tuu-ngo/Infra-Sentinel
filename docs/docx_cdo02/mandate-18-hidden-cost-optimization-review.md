# Directive #18 - Review hóa đơn ẩn ngoài node compute

Ngày review: 24/07/2026. Phạm vi của tài liệu này là **review và đề xuất** theo Directive #18, dựa trên repo, Terraform state và một số lệnh AWS read-only. Tài liệu này **không phải kế hoạch apply ngay**, không chạy `terraform apply`, không xóa/sửa tài nguyên, không thao tác tay lên hạ tầng và không đụng `flagd`.

## Đọc lại yêu cầu Directive #18

Directive #18 yêu cầu cắt phần chi phí ẩn ngoài node compute bằng **Usage**, không dựa vào cột tiền vì account đang chạy credit. Các nhóm bắt buộc phải xử lý:

- Tài nguyên mồ côi: EBS `available`, EIP không gắn, snapshot/AMI rác, load balancer/target group không dùng.
- Storage: EBS `gp2` -> `gp3`, right-size dung lượng, snapshot/S3 có lifecycle.
- Data transfer: giảm cross-AZ không cần thiết, dùng VPC endpoint cho call nội bộ AWS để giảm NAT gateway/data processing.
- Telemetry: log/trace/metric có sampling, retention hữu hạn, kiểm cardinality nhưng vẫn giữ khả năng vận hành/điều tra.
- Chỉ ra top cost-driver ngoài compute và chứng minh đã giảm bằng usage trước/sau.

Ràng buộc quan trọng: giữ SLO, giữ khả năng quan sát/điều tra, Storefront public, cổng vận hành private, và không đụng `flagd`.

## Nguồn đối chiếu

- Terraform network/datastore/edge: `infra/modules/network/main.tf`, `infra/modules/datastores/*.tf`, `infra/modules/edge/main.tf`.
- Production vars/state: `infra/live/production/*.tf`, `terraform state list` read-only.
- GitOps/PVC/ingress: `gitops/infrastructure/datastore-pvc.yaml`, `gitops/edge/frontend-proxy-internal-ingress.yaml`.
- Observability values: `phase3 - information/techx-corp-chart/values.yaml`, `phase3 - information/deploy/values-prod.yaml`, `phase3 - information/techx-corp-chart/templates/otel-gateway.yaml`.
- AWS live read-only: EC2 volumes/EIP/snapshots/AMI, ELBv2 LB/TG, NAT gateway, VPC endpoints, RDS, ElastiCache, MSK, CloudWatch NAT bytes.

## Kết luận ngắn

Hệ thống đã có một số điểm đáp ứng tốt Directive #18: RDS live dùng `gp3`, ECR có lifecycle, CloudTrail S3 có lifecycle, Prometheus retention 7 ngày, Jaeger giới hạn số trace bằng `MEMORY_MAX_TRACES`, và đã có VPC endpoints cho S3/ECR/SSM.

Tuy nhiên vẫn chưa đạt đầy đủ vì live AWS đang có 3 EBS volume trạng thái `available` bị mồ côi, các PVC in-cluster vẫn khai báo `gp2`, NAT gateway vẫn tồn tại và là single-AZ, telemetry chưa có sampling/retention policy rõ cho OpenSearch log index, CloudWatch EKS control-plane log group đang giữ khoảng 4.8 GB với retention 90 ngày, và chưa có bảng usage trước/sau cho cardinality/volume telemetry.

## Quyết định cuối sau rà soát lần cuối

**Nên thực hiện Directive #18**, vì đây là directive bắt buộc và live account thật sự còn cost-driver ngoài node compute. Nhưng **không nên apply toàn bộ đề xuất trong một lần**. Cách đúng là chia thành các batch nhỏ, ưu tiên việc không chạm đường phục vụ traffic và không đụng dữ liệu active.

Quyết định cụ thể:

- **Nên làm trước:** thêm VPC endpoints còn thiếu nhưng giữ NAT nguyên; giảm retention CloudWatch/OpenSearch theo guardrail; thu thập dashboard usage trước/sau.
- **Chờ sau khi Mandate #8 được mentor nghiệm thu:** dọn 3 EBS orphan dạng dynamic PVC, retire PVC/datastore cũ, và mọi việc liên quan `gp2` -> `gp3` của PVC in-cluster. Lý do: các tài nguyên này có thể vẫn là bằng chứng/đường lui sau cutover RDS/ElastiCache/MSK; dọn trước nghiệm thu có rủi ro làm mất rollback evidence hoặc dữ liệu cần đối chiếu.
- **Chưa nên làm ngay:** tắt NAT gateway; đổi/recreate PVC `gp2` -> `gp3` trực tiếp; xóa PVC/datastore cũ nếu chưa có nghiệm thu Mandate #8, bằng chứng live từ Kubernetes và rollback window rõ.
- **Không nên làm:** cắt telemetry kiểu tắt log/trace/metric toàn cục hoặc sampling làm mất error/slow checkout traces.

Giới hạn của lần rà soát này: `kubectl` trên máy đang trỏ tới `https://localhost:8443` nhưng local tunnel/API proxy không chạy, nên chưa xác nhận được PVC/PV live bằng Kubernetes API. Ngoài ra Mandate #8 chưa được mentor nghiệm thu, nên mọi thao tác liên quan PVC/EBS/datastore cũ phải đánh dấu **chờ làm sau**, chỉ thực hiện khi có nghiệm thu, có xác minh bằng `kubectl` hoặc console, và có quyết định kết thúc rollback window.

## Nhóm làm được ngay

Các mục này không phụ thuộc nghiệm thu Mandate #8 và có thể đi trước nếu vẫn theo quy trình PR/plan/read-only evidence:

1. Thêm VPC endpoints còn thiếu trong `infra/modules/network/main.tf`, nhưng giữ NAT gateway nguyên.
2. Giảm retention CloudWatch EKS control-plane logs từ 90 ngày xuống 30 ngày nếu mentor chấp thuận policy điều tra 30 ngày; không tắt `api/audit/authenticator`.
3. Thêm OpenSearch log lifecycle cho `otel-logs-*`, ưu tiên retention 7 ngày để không làm mất khả năng điều tra gần.
4. Thêm trace sampling có guardrail: giữ 100% error traces, slow checkout traces và rollout/canary traces; chỉ sample success traffic.
5. Thu thập usage trước/sau: NAT bytes, log stored bytes, OpenSearch/log volume, active series/cardinality, SLO dashboard.

## Nhóm chờ Mandate #8

Các mục này liên quan trực tiếp datastore migration/rollback của Mandate #8, nên **chờ sau khi #8 được mentor nghiệm thu**:

1. Dọn 3 EBS volume `available` dạng dynamic PVC.
2. Retire PVC/datastore cũ của Postgres/Kafka/Valkey in-cluster.
3. Xử lý PVC `gp2` -> `gp3` cho các PVC cũ.
4. Xóa bất kỳ snapshot/backup thủ công nào đang được dùng làm bằng chứng hoặc đường lui cho #8.

## Đối chiếu từng yêu cầu

| Yêu cầu #18 | Hiện trạng tìm thấy | Đánh giá | Cần làm để đạt |
|---|---|---|---|
| Cắt data-transfer ẩn | Network module đã có VPC endpoints: S3 Gateway, ECR API, ECR DKR, SSM, SSMMessages, EC2Messages. Live có 1 NAT gateway `nat-0b963ceaf95a7817f`, tạo 13/07/2026. CloudWatch 16/07-23/07 ghi `BytesInFromSource`/`BytesOutToDestination` khoảng 2.64 GB. Single NAT nằm một public subnet nên egress còn lại từ AZ khác có thể đi cross-AZ. | Đạt một phần | Giữ endpoint hiện có. Thêm endpoint cho AWS API còn đi qua NAT: Secrets Manager, KMS, STS, CloudWatch Logs/Monitoring, EC2/ELB nếu controller dùng, và Bedrock Runtime nếu app LLM/product-review gọi Bedrock. Không tắt NAT ngay. Không tạo NAT mới mỗi AZ khi chưa có số liệu vì có thể tăng NAT-hours. |
| Telemetry không đốt tiền | Prometheus retention 7d. Jaeger memory backend `MEMORY_MAX_TRACES=25000`. OTel gateway có transform normalize span name để giảm cardinality. OTel node agent không bật logs collection. Gap: chưa thấy `tail_sampling`/`probabilistic_sampler`; log pipeline gửi OTLP logs vào OpenSearch `otel-logs-yyyy-MM-dd` nhưng chưa thấy ISM/delete policy; Prometheus đang promote nhiều resource attributes có khả năng high-cardinality như `service.instance.id`, `k8s.pod.name`, `k8s.replicaset.name`. | Chưa đạt đầy đủ | Thêm sampling có guardrail: giữ 100% error/slow checkout, sample success traffic theo tỷ lệ thấp hơn; thêm OpenSearch ISM xóa/rollover log index sau 3-7 ngày; bỏ bớt label high-cardinality không cần cho SLO; thêm dashboard ingest spans/sec, logs/day, active series/top labels. |
| Chỉ ra top cost-driver ngoài compute và chứng minh giảm | Đã có usage live: MSK 3 broker = 504 broker-hour/tuần + 30 GiB broker EBS; NAT = 168 NAT-hour/tuần + khoảng 2.77 GB data processed trong 7 ngày gần nhất; RDS gp3 20 GiB Multi-AZ; EBS orphan 6 GiB gp2; CloudWatch log group `/aws/eks/techx-corp-tf3/cluster` lưu khoảng 4.8 GB với retention 90 ngày. Các phần đã cắt sẵn: VPC endpoints S3/ECR/SSM, RDS gp3, ECR lifecycle, CloudTrail lifecycle, Prometheus 7d. | Chưa hoàn tất vì chưa thay đổi | Làm trước phần không phụ thuộc #8: NAT bytes giảm sau khi thêm endpoint, CloudWatch/OpenSearch retention giảm nhưng vẫn giữ SLO/trace investigation. Phần EBS orphan 6 GiB -> 0 chờ sau nghiệm thu Mandate #8. |
| Không tài nguyên mồ côi | Live read-only thấy 3 EBS volume `available`, tổng 6 GiB, đều là dynamic PVC `gp2`: `vol-05d59d76c58a9d835` 1 GiB AZ 1a, `vol-0f4b0c53ef8091d52` 2 GiB AZ 1a, `vol-0a22f104910589929` 3 GiB AZ 1b. Không thấy EIP rời. Không thấy AMI/snapshot owner=self. LB `techx-tf3-frontend-internal` active và target group có `LBs=1`. | Chưa đạt, **chờ #8** | Không delete ngay vì Mandate #8 chưa được mentor nghiệm thu. Đánh dấu 3 volume này là cleanup candidate sau nghiệm thu #8; lúc đó xác minh PVC/PV tương ứng, chụp bằng chứng, snapshot tạm nếu còn nghi ngờ, rồi mới delete. |
| Storage đúng loại + có vòng đời | RDS `techx-tf3-postgres`: `gp3`, 20 GiB, max 40 GiB, Multi-AZ, backup 7 ngày. Valkey: 2 node, snapshot retention 3. MSK: 3 broker `kafka.m7g.large`, mỗi broker 10 GiB, Kafka retention 168h. ECR giữ 10 tagged build mới nhất/service và xóa untagged sau 7 ngày. CloudTrail S3 lifecycle 30 ngày. Gap: `gitops/infrastructure/datastore-pvc.yaml` và `values-prod.yaml` vẫn `storageClassName: gp2`; live orphan cũng là gp2. | Đạt một phần, **PVC chờ #8** | Không đổi/recreate PVC in-cluster trước nghiệm thu #8. Sau nghiệm thu, nếu Postgres/Kafka/Valkey in-cluster đã chính thức retired thì cleanup PVC/volume cũ; nếu vẫn cần giữ đường lui thì giữ nguyên hoặc migrate theo snapshot/restore riêng. |

## Nếu sửa thì sửa ở đâu

| Hạng mục | File/code liên quan | Ghi chú triển khai |
|---|---|---|
| Thêm VPC endpoints | `infra/modules/network/main.tf` | Thêm các `aws_vpc_endpoint` mới cho Secrets Manager, KMS, STS, CloudWatch Logs/Monitoring, Bedrock Runtime nếu cần. Giữ NAT hiện tại. |
| CloudWatch EKS log retention | Terraform EKS module hoặc `aws_cloudwatch_log_group` nếu repo quản lý trực tiếp | Không tắt `api/audit/authenticator`; chỉ cân nhắc giảm retention 90 ngày xuống 30 ngày nếu mentor chấp nhận mất log cũ hơn. |
| OpenSearch log lifecycle | `phase3 - information/techx-corp-chart/values.yaml` hoặc thêm manifest policy riêng | Cần policy retention cho `otel-logs-*`, không xóa log incident quá sớm. |
| Trace sampling | `phase3 - information/techx-corp-chart/values.yaml`, `phase3 - information/techx-corp-chart/templates/otel-gateway.yaml` | Chỉ sample success traffic. Giữ 100% error/slow checkout và rollout/canary traces. |
| Giảm metric cardinality | `phase3 - information/techx-corp-chart/values.yaml` phần `promote_resource_attributes` | Phải kiểm tra dashboard SLO/rollout analysis trước khi bỏ label. |
| Cross-AZ internal traffic | Service template `phase3 - information/techx-corp-chart/templates/_objects.tpl` hoặc values nếu chart hỗ trợ | Chỉ test từng service. Không rollout toàn hệ thống nếu chưa đo SLO. |
| Dọn EBS orphan | Không nằm trong repo | **Chờ sau nghiệm thu Mandate #8** vì 3 volume orphan có tag dynamic PVC và có thể còn liên quan bằng chứng/rollback datastore. Đây là thao tác live AWS sau khi verify. Nên snapshot tạm nếu còn nghi ngờ. |
| PVC `gp2` -> `gp3` | `gitops/infrastructure/datastore-pvc.yaml`, `phase3 - information/deploy/values-prod.yaml`, `phase3 - information/techx-corp-chart/templates/valkey-cart-pvc.yaml` | **Chờ sau nghiệm thu Mandate #8.** Không patch trực tiếp PVC đang tồn tại. Cần xác minh datastore in-cluster còn dùng hay chỉ còn rollback. |

## Rà soát ảnh hưởng nếu deploy/apply các thay đổi đề xuất

### 1. Chỉ sửa file `solutionmd18.md`

Việc chỉ chỉnh sửa tài liệu `solutionmd18.md` **không ảnh hưởng hạ tầng**, không restart pod, không thay đổi Terraform/GitOps, không gây downtime và không làm mất dữ liệu.

### 2. Thêm VPC endpoint mới

Nếu chỉ thêm endpoint mới và **không tắt NAT**, rủi ro thấp. Terraform sẽ tạo thêm endpoint/ENI và private DNS cho AWS service tương ứng. App thường không downtime vì route NAT vẫn còn làm đường lui.

Guardrail:

- Chạy `terraform plan` và kiểm tra chỉ có `aws_vpc_endpoint`/security group rule liên quan được thêm.
- Không đổi `enable_nat_gateway`, `single_nat_gateway`, route table NAT trong cùng PR.
- Sau apply, kiểm tra External Secrets, image pull, CloudWatch/STS/KMS calls và NAT bytes.

Kết luận: có thể làm an toàn nếu tách PR nhỏ. Không nên gây downtime.

### 3. Tắt hoặc xóa NAT gateway

Không nên làm ở thời điểm này. NAT vẫn có thể đang phục vụ outbound cho các call chưa có endpoint, call internet ngoài AWS, Cloudflare tunnel hoặc dependency không nằm trong AWS PrivateLink.

Rủi ro:

- Pod/node mất egress.
- External Secrets, controller hoặc workload gọi AWS API thiếu endpoint có thể lỗi.
- Cổng vận hành private có thể bị ảnh hưởng nếu đường egress phụ thuộc NAT.

Kết luận: có thể gây downtime vận hành hoặc lỗi workload. Không đưa vào batch đầu.

### 4. Xóa 3 EBS volume orphan

Vì Mandate #8 chưa được mentor nghiệm thu, bước này **chưa làm ngay**. Ba volume `available` đang mang tag dynamic PVC nên phải xem là candidate cleanup sau nghiệm thu, không phải rác chắc chắn có thể xóa tức thì.

Nếu volume đúng là `available` và không còn PV/PVC nào dùng, xóa volume sẽ không làm pod đang chạy downtime vì volume không attach vào instance nào.

Rủi ro chính là **mất dữ liệu rollback** nếu volume đó vẫn còn giá trị điều tra hoặc khôi phục.

Guardrail:

- Đối chiếu `VolumeId` với PV/PVC cũ, namespace `techx-tf3`, tag dynamic PVC.
- Chỉ thực hiện sau khi Mandate #8 được mentor nghiệm thu hoặc mentor xác nhận không cần giữ các volume/PVC này làm bằng chứng/rollback.
- Xác minh app đã cutover sang managed RDS/ElastiCache/MSK và không còn đọc/ghi volume đó.
- Nếu còn nghi ngờ, snapshot tạm có TTL rồi mới delete.

Kết luận: đánh dấu **chờ sau nghiệm thu Mandate #8**. Không nên gây downtime nếu xác minh đúng, nhưng có thể mất dữ liệu/bằng chứng rollback nếu xóa trước nghiệm thu hoặc xóa nhầm.

### 5. Đổi PVC `gp2` -> `gp3`

Vì Mandate #8 chưa được mentor nghiệm thu, mọi thay đổi PVC in-cluster liên quan Postgres/Kafka/Valkey cũ phải **chờ làm sau**. Đây không phải batch an toàn của Directive #18 ở thời điểm hiện tại.

Đây là phần rủi ro cao nhất nếu làm thẳng. `storageClassName` của PVC đang tồn tại không nên patch trực tiếp; nhiều trường PVC là immutable. Nếu ai xóa/recreate PVC để lấy gp3 thì có thể làm mất dữ liệu.

Rủi ro:

- ArgoCD sync lỗi vì field immutable.
- Stateful pod dùng RWO PVC có thể bị restart/downtime nếu recreate.
- Dữ liệu Postgres/Kafka/Valkey in-cluster có thể mất nếu xóa PVC/PV sai.
- Có thể làm mất bằng chứng/đường lui của Mandate #8 trước khi mentor nghiệm thu.

Guardrail:

- Không đổi trực tiếp PVC đang active.
- Nếu datastore in-cluster không còn phục vụ traffic, vẫn chỉ retire theo runbook cleanup **sau nghiệm thu Mandate #8**, sau khi có snapshot/backup và rollback window đã đóng.
- Nếu còn cần dữ liệu, migrate bằng snapshot/restore hoặc tạo PVC gp3 mới, copy dữ liệu, rồi cutover có kiểm soát.

Kết luận: không apply thẳng và không làm trước nghiệm thu #8. Có thể gây downtime/mất dữ liệu nếu làm sai.

### 6. Telemetry sampling và retention

Không làm app business downtime, nhưng có thể làm giảm khả năng điều tra nếu cấu hình quá mạnh.

Rủi ro:

- Sampling sai làm mất trace lỗi/chậm.
- Retention log quá ngắn làm không còn log để điều tra incident.
- Bỏ label metric sai làm hỏng dashboard SLO/rollout analysis.

Guardrail:

- Giữ 100% error traces.
- Giữ 100% slow checkout traces.
- Giữ traces trong giai đoạn rollout/canary.
- Chỉ sample success traces.
- OpenSearch retention nên bắt đầu 7 ngày, không xóa ngay log cũ khi chưa kiểm tra.
- Kiểm dashboard SLO, Jaeger trace search, OpenSearch log search trước/sau.

Kết luận: không gây downtime, nhưng có thể làm "mù observability" nếu cắt quá tay.

### 6.1. CloudWatch EKS control-plane logs

EKS đang bật control-plane logs loại `api`, `audit`, `authenticator`; đây là log quan trọng cho vận hành và điều tra quyền truy cập. Không nên tắt các log type này để tiết kiệm.

Điểm nên xử lý là retention: log group `/aws/eks/techx-corp-tf3/cluster` đang retention 90 ngày và lưu khoảng 4.8 GB. Giảm retention xuống 30 ngày thường không gây downtime và không ảnh hưởng app, nhưng sẽ xóa/mất khả năng tra cứu log control-plane cũ hơn 30 ngày.

Kết luận: nên giảm retention nếu mentor đồng ý policy điều tra 30 ngày; không nên tắt EKS control-plane logging.

### 7. Cross-AZ/topology-aware routing

Thay đổi routing nội bộ có thể ảnh hưởng traffic distribution. Nếu service local endpoint không đủ hoặc pod spread không đều, request có thể dồn vào một AZ/node.

Guardrail:

- Test từng service ít rủi ro.
- Không áp dụng toàn bộ mesh/service cùng lúc.
- Đo SLO, error rate, p95, pod distribution theo AZ trước/sau.

Kết luận: có rủi ro gián tiếp tới SLO nếu rollout rộng. Không nên làm batch đầu.

## Thứ tự triển khai an toàn đề xuất

1. Chỉ thêm bằng chứng và checklist review, không mutate hạ tầng.
2. Thêm VPC endpoints còn thiếu, giữ NAT nguyên.
3. Giảm retention CloudWatch EKS logs từ 90 ngày xuống 30 ngày nếu được chấp thuận; không tắt logging.
4. Đo lại NAT bytes 7 ngày.
5. Thêm telemetry retention/sampling theo guardrail, kiểm dashboard trước/sau.
6. **Sau khi Mandate #8 được mentor nghiệm thu:** xử lý EBS orphan sau khi verify bằng Kubernetes/console và snapshot tạm nếu cần.
7. **Sau khi Mandate #8 được mentor nghiệm thu:** xử lý PVC `gp2`/`gp3`, và chỉ làm như một migration/retirement riêng.

## Kết luận về downtime và mất dữ liệu

Nếu chỉ cập nhật tài liệu này hoặc thêm VPC endpoints mà giữ NAT nguyên thì **không nên gây downtime và không làm mất dữ liệu**.

Các thay đổi có thể gây sự cố nếu làm sai là:

- Tắt NAT gateway quá sớm.
- Xóa EBS/PVC khi Mandate #8 chưa được nghiệm thu hoặc chưa xác minh dữ liệu rollback.
- Đổi/recreate PVC `gp2` -> `gp3` trực tiếp.
- Sampling/retention telemetry quá mạnh làm mất khả năng điều tra.

Vì vậy Directive #18 nên được triển khai bằng các PR nhỏ, có `terraform plan`, có GitOps diff, có bằng chứng usage trước/sau, và có checkpoint SLO/observability sau từng bước. Không nên apply toàn bộ đề xuất trong một lần.
