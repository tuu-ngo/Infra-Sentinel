# Mandate 11 Review Phát Hiện Audit

## 1. Kết luận ngắn

Hướng phù hợp cho Mandate 11 là xem auditability như một bài toán phát hiện chủ động, không chỉ là khả năng điều tra sau sự cố.

Phần triển khai nên tập trung vào:

- các hành vi control-plane rủi ro cao;
- định tuyến cảnh báo tới người nhận thật;
- đo time-to-detect;
- giữ mức nhiễu vận hành thấp.

## 2. Kiến trúc phát hiện được khuyến nghị

### 2.1. Luồng cảnh báo tối thiểu

`CloudTrail trail đang bật logging -> rule trên EventBridge default bus -> Lambda audit-alert-router -> SNS topic -> email người vận hành`

Vì sao đây là baseline phù hợp:

- **Nằm ngoài EKS cluster**: nếu cluster bị tấn công, đường phát hiện vẫn còn hoạt động.
- **Chi phí thấp**: không cần SIEM, CloudTrail Lake, hay Security Hub cho mandate này.
- **Đủ nhanh**: EventBridge trên CloudTrail management events thường đủ nhanh cho cam kết cảnh báo ở mức vài phút.
- **Dễ demo**: mentor có thể chạy `aws iam create-access-key ...` hoặc `aws eks create-access-entry ...` rồi chờ cảnh báo.
- **Dùng được cho cả write event và một phần read event**: write event dùng match bình thường trên EventBridge, còn read-only management event như `secretsmanager:GetSecretValue` cần rule EventBridge ở trạng thái `ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS`.

Lưu ý triển khai quan trọng:

- thiết kế này yêu cầu có `CloudTrail trail` thật và trail đó phải đang bật logging;
- điều này đặc biệt quan trọng với phát hiện `iam:*` và với phát hiện secret-read của Group 5;
- `CloudWatch Logs` **không bắt buộc** phải là tầng vận chuyển sự kiện cho vòng triển khai đầu của mandate này;
- đường phát hiện bắt buộc là `CloudTrail -> EventBridge -> Lambda -> SNS`.

### 2.2. Kênh chuyển cảnh báo

Dựa trên repo và môi trường hiện tại, kênh đầu tiên nên dùng là:

- **Chính**: `SNS email` tới đúng người nhận
- **Tùy chọn**: `AWS Chatbot` chỉ nếu team đã có sẵn đường Slack hoạt động ổn

Email nên đi trước vì:

- đơn giản để triển khai hơn;
- không phụ thuộc vào thiết lập workspace Slack và quyền liên quan;
- đủ để đáp ứng yêu cầu rằng cảnh báo phải thực sự tới tay một người.

### 2.3. Các thành phần Terraform nên có

- `infra/modules/audit-detection/`
  - `main.tf`
  - `variables.tf`
  - `outputs.tf`
  - một thư mục Lambda nhỏ như `lambda/index.py`
- `infra/live/production/audit-detection.tf`
- các resource cho:
  - một `CloudTrail` trail đang bật logging
  - các rule `EventBridge` trên default bus
  - `Lambda`
  - `SNS`
- `docs/adr/0011-mandate-11-audit-detection.md`
- `docs/runbooks/mandate-11-audit-detection-demo.md`

Phần này nên tách khỏi module EKS hiện có. Đây là security control-plane và phát hiện audit, không phải logic runtime của ứng dụng.

Lưu ý về region:

- `iam:*` và các management event của global service khác nên được xử lý từ `us-east-1`;
- ví dụ, mentor có thể tạo IAM access key khi đang dùng AWS console từ Singapore, Tokyo, hay bất kỳ vị trí hoặc console region nào khác, nhưng rule phát hiện bắt `iam:CreateAccessKey` vẫn nên được triển khai ở `us-east-1`;
- các dịch vụ theo region như `eks:*` và `secretsmanager:*` nên được xử lý tại region vận hành của chúng, hiện tại là `ap-southeast-1`.

---

## 3. Những gì phải phát hiện cho CDO01, CDO02 và mentor

Đây là phần cốt lõi của review. Trọng tâm không phải là "nên bật dịch vụ AWS nào", mà là:

**Với giả định `CDO01`, `CDO02`, và `mentor` đều là IAM user có `AdministratorAccess`, những hành vi nào phải kích hoạt phát hiện nếu tài khoản hoặc key của họ bị lạm dụng?**

Các nhóm dưới đây được chia theo hành vi, không chia theo dịch vụ.

### 3.1. Group 1 - Các hành động làm mù hệ thống

Nhóm này luôn phải cảnh báo ở mức cao nhất, bất kể actor là `CDO01`, `CDO02`, hay `mentor`.

Những gì phải phát hiện:

- tắt audit hoặc thu thập log;
- thay đổi logging theo hướng không còn giữ được cùng mức bằng chứng như trước;
- xóa log;
- giảm thời gian lưu giữ audit log;
- xóa hoặc làm yếu nơi lưu trữ bằng chứng audit.

API/action cần match trực tiếp:

- `cloudtrail:StopLogging`
- `cloudtrail:DeleteTrail`
- `cloudtrail:UpdateTrail`
- `cloudtrail:PutEventSelectors`
- `cloudtrail:StartLogging` khi nó xuất hiện sau một lần dừng bất thường hoặc xảy ra trên trail nhạy cảm
- `logs:DeleteLogGroup`
- `logs:PutRetentionPolicy`
- cộng thêm mọi thay đổi trực tiếp lên bucket hoặc KMS policy có ảnh hưởng đến đường lưu trữ audit log, nếu có cấu hình

Vì sao nhóm này quan trọng:

- kẻ tấn công thường vô hiệu hóa khả năng quan sát trước khi làm việc khác;
- chỉ một khoảng trống logging ngắn cũng có thể làm đứt chuỗi bằng chứng;
- trong mô hình hiện tại, mọi admin user đều có thể làm việc này, nên nó luôn phải được coi là `critical`.

Diễn giải vận hành:

- nếu `CDO01` làm việc này, phải cảnh báo;
- nếu `CDO02` làm việc này, phải cảnh báo;
- nếu `mentor` làm việc này, phải cảnh báo;
- "họ là admin nên có thể họ làm đúng ý" không phải là lý do hợp lệ để suppress detection.

### 3.2. Group 2 - Các hành động tạo thêm một đường vào môi trường

Đây là nhóm quan trọng tiếp theo. Ý chính là **tạo thêm credential, principal, đường đăng nhập, hoặc điểm bám trụ mới**.

Những gì phải phát hiện:

- tạo access key mới;
- tạo IAM user mới;
- tạo role mới cho con người sử dụng;
- tạo login profile mới;
- thay đổi trust policy để principal khác có thể assume role;
- attach policy làm tăng quyền hiệu lực của principal;
- tạo policy version mới và đặt nó làm default.

API/action cần match trực tiếp:

- `iam:CreateAccessKey`
- `iam:CreateUser`
- `iam:CreateRole`
- `iam:CreateLoginProfile`
- `iam:UpdateAssumeRolePolicy`
- `iam:AttachUserPolicy`
- `iam:AttachRolePolicy`
- `iam:PutUserPolicy`
- `iam:PutRolePolicy`
- `iam:CreatePolicyVersion`
- `iam:SetDefaultPolicyVersion`

Vì sao nhóm này quan trọng:

- trong mô hình admin IAM user hiện tại, một access key mới về bản chất là một cửa phụ mới;
- nếu kẻ tấn công lấy được một admin key, việc tạo thêm credential là bước persistence rất phổ biến;
- về góc độ audit, đây là một lần mở rộng bề mặt tấn công ngay lập tức.

Diễn giải theo actor:

- `CDO01`: access key hoặc role mới ngoài thay đổi đã được lên kế hoạch và review thì phải cảnh báo;
- `CDO02`: tương tự;
- `mentor`: việc này còn nên cảnh báo mạnh hơn, vì mentor không cần tạo credential mới để verify mandate.

Nguyên tắc quan trọng:

- detection phải nổ trước;
- tính hợp lệ sẽ được điều tra sau khi cảnh báo phát ra, không phải trước đó.

### 3.3. Group 3 - Các hành động mở rộng quyền quản trị vượt quá phạm vi mong đợi

Nhóm này không phải lúc nào cũng là tạo identity mới. Nó là việc **làm cho một identity đang có trở nên mạnh hơn trước**.

Những gì phải phát hiện:

- attach policy quyền cao cho user hoặc role đang tồn tại;
- chuyển policy sang default version rộng quyền hơn;
- thay đổi trust relationship để thêm principal có thể dùng role;
- thêm user vào privileged group;
- đổi tên IAM user theo cách làm mờ nguồn gốc hoặc ngụy trang một identity đặc quyền;
- biến một đường truy cập hẹp thành một đường truy cập rộng.

API/action cần match trực tiếp:

- `iam:AttachUserPolicy`
- `iam:AttachRolePolicy`
- `iam:PutUserPolicy`
- `iam:PutRolePolicy`
- `iam:CreatePolicyVersion`
- `iam:SetDefaultPolicyVersion`
- `iam:UpdateAssumeRolePolicy`
- `iam:AddUserToGroup`
- `iam:UpdateUser`
- cộng thêm mọi API làm thay đổi permission-boundary hoặc access path nếu team dùng chúng về sau

Vì sao nhóm này quan trọng:

- trong môi trường đã có sẵn admin, nhiều thay đổi mở rộng quyền nhìn có vẻ nhỏ nhưng vẫn là tín hiệu lạm dụng rất rõ;
- đây chính là những thay đổi dễ bị ngụy trang thành "chỉ để vận hành thuận tiện hơn".

Diễn giải theo actor:

- `CDO01`: kể cả khi đang làm hardening, việc mở quyền âm thầm cho người hoặc automation vẫn phải cảnh báo;
- `CDO02`: nếu thêm quyền để xử lý khẩn cấp, nó vẫn cần phát cảnh báo trừ khi đã được phê duyệt rõ ràng và có giới hạn thời gian;
- `mentor`: không có lý do hợp lệ trong lúc review để mentor mở rộng quyền cho chính mình hoặc cho người khác.

### 3.4. Group 4 - Các hành động mở thêm quyền vào cluster hoặc runtime

Với repo này, thay đổi EKS access đặc biệt quan trọng vì nó nối quyền control-plane trên AWS sang quyền kiểm soát runtime thực tế.

Những gì phải phát hiện:

- thêm cluster access cho một principal;
- sửa access entry để principal đang có được thêm quyền;
- gắn quyền ở mức cluster admin;
- tạo đường truy cập mới vào các tài nguyên runtime vận hành riêng tư.

API/action cần match trực tiếp:

- `eks:CreateAccessEntry`
- `eks:UpdateAccessEntry`
- `eks:DeleteAccessEntry`
- `eks:AssociateAccessPolicy`
- `eks:DisassociateAccessPolicy`
- cộng thêm mọi API trực tiếp khác nếu sau này được dùng để mở rộng đường vào bastion riêng hoặc operational UI

Vì sao nhóm này quan trọng:

- đây là bước đi từ "chạm được AWS" sang "điều khiển được workload";
- nếu ai đó thêm hoặc đổi EKS access nằm ngoài thay đổi Git/Terraform đã quản lý, đó là một đường bypass trực tiếp.

Diễn giải theo actor:

- `CDO01` và `CDO02` vốn đã là admin, nên mọi mở rộng thêm vào cluster vẫn đáng quan tâm và vẫn phải cảnh báo;
- `mentor` chỉ nên có đúng phạm vi review đã được cấp, nên mọi đường truy cập mới phải bị coi là bất thường ngay lập tức.

### 3.5. Group 5 - Truy cập secret nhạy cảm bằng tài khoản con người

Vì team vẫn đang dùng admin IAM user, mọi truy cập secret từ identity của con người đều đáng để review.

Những gì phải phát hiện:

- đọc các secret nhạy cảm cho vận hành;
- đọc secret của ứng dụng vốn bình thường chỉ automation mới cần;
- đọc secret ngoài cửa sổ bảo trì đã lên kế hoạch hoặc ngoài mục đích đã biết.

API/action cần match trực tiếp:

- `secretsmanager:GetSecretValue`
- `secretsmanager:BatchGetSecretValue` nếu account có dùng

Những secret tối thiểu nên theo dõi:

- `techx-corp-tf3/flagd-sync-token` hoặc đúng tên secret đang dùng
- secret của RDS / MSK / ElastiCache nếu Mandate #8 đưa chúng vào Secrets Manager

Vì sao nhóm này quan trọng:

- việc đọc secret thường là bước chuẩn bị cho các hành động lớn hơn;
- nếu admin key bị compromise, kẻ tấn công thường pivot sang secret rất sớm;
- với operator là con người, việc đọc secret nên là ngoại lệ chứ không phải đường đi mặc định.

Diễn giải theo actor:

- `CDO01`: có thể có vài trường hợp hợp lệ hiếm hoi, nhưng vẫn cần tín hiệu;
- `CDO02`: tương tự;
- `mentor`: gần như không có lý do hợp lệ để đọc secret khi chỉ đang verify mandate.

Lưu ý quan trọng:

- detection này phải lọc bỏ automation hợp lệ đã biết, nếu không sẽ nhiễu ngay;
- mục tiêu audit ở đây là **human secret access**, không phải mọi event truy cập secret;
- đường triển khai dự kiến cho nhóm này là:
  - `CloudTrail trail đang bật logging`
  - rule `EventBridge` trên default bus với state `ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS`
  - `Lambda`
  - `SNS/email`
- `CloudWatch Logs` không bắt buộc là một đường vận chuyển sự kiện riêng cho nhóm này trong vòng triển khai đầu tiên.

### 3.6. Group 6 - Các hành động phá hủy làm mất đường khôi phục

Nhóm này không chỉ là "xóa tài nguyên". Nó là việc xóa những gì team cần để khôi phục, rollback, hoặc tiếp tục điều tra.

Những gì phải phát hiện:

- xóa cluster, node group, datastore, secret, key, hoặc log bucket;
- lên lịch xóa key;
- xóa tài nguyên test hoặc canary dùng cho verification;
- xóa những thành phần hỗ trợ rollback hoặc phân tích sau sự cố.

API/action cần match trực tiếp:

- `eks:DeleteCluster`
- `eks:DeleteNodegroup`
- `rds:DeleteDBInstance`
- `rds:DeleteDBCluster`
- `elasticache:DeleteReplicationGroup`
- `elasticache:DeleteCacheCluster`
- `kms:ScheduleKeyDeletion`
- `secretsmanager:DeleteSecret`
- `s3:DeleteBucket`
- `cloudtrail:DeleteTrail`

Vì sao nhóm này quan trọng:

- có những lần xóa chưa gây outage ngay, nhưng lại làm mất đường khôi phục;
- với một mandate về auditability, việc mất đường rollback hoặc mất nơi giữ bằng chứng tự nó đã là một sự kiện nguy hiểm.

Diễn giải theo actor:

- `CDO01`: xóa cơ chế phòng thủ hoặc nơi giữ bằng chứng phải cảnh báo;
- `CDO02`: xóa dữ liệu quan trọng hoặc hạ tầng runtime phải cảnh báo;
- `mentor`: mentor không nên xóa các tài nguyên nền tảng trong lúc verification.

### 3.7. Tóm tắt cho ba actor admin này

Nếu cần giải thích đơn giản cho mentor hoặc cho team:

- `CDO01`, `CDO02`, và `mentor` đều là **admin**, nên tiêu chí "user có quyền hay không" không còn hữu ích cho phát hiện;
- vì vậy detection phải tập trung vào **hành vi**:
  - làm mù audit trail;
  - tạo đường truy cập mới;
  - mở rộng quyền;
  - mở rộng quyền vào cluster hoặc runtime;
  - đọc secret từ tài khoản con người;
  - phá hủy tài nguyên hoặc đường khôi phục;
- mọi cảnh báo phải có:
  - ai;
  - làm gì;
  - khi nào;
  - từ đâu;
  - và mất bao lâu để phát hiện.

---

## 4. Những gì không nên làm ở vòng đầu

- không triển khai `Security Hub`, `GuardDuty`, `CloudTrail Lake`, hoặc `OpenSearch SIEM` chỉ để vượt qua mandate này;
- không cảnh báo trên toàn bộ `Describe*`, `List*`, hoặc `Get*`, vì sẽ tạo nhiễu ngay lập tức;
- không phụ thuộc vào Grafana hoặc Prometheus trong cluster cho đường phát hiện audit control-plane này; nếu cluster bị ảnh hưởng, detector có thể chết theo;
- không tuyên bố rằng "ta có thể phân biệt hoàn hảo hành động admin hợp lệ với hành động độc hại" trong khi team vẫn đang dùng admin IAM user với static key.

---

## 5. Mọi cảnh báo phải chứa những gì

Mỗi cảnh báo ít nhất nên có:

- `severity`
- `rule_name`
- `event_name`
- `actor`
  - `userIdentity.type`
  - `userName` hoặc `arn`
- `when`
  - `eventTime`
  - `detectedAt`
  - `time_to_detect_seconds`
- `from_where`
  - `sourceIPAddress`
  - `awsRegion`
  - `userAgent`
- `target`
  - ARN tài nguyên hoặc tên tài nguyên nếu có
- `request_summary`
  - bản tóm tắt ngắn, đã lọc, của các request parameter quan trọng
- `investigation_hint`
  - ví dụ: "kiểm tra CloudTrail Event History với eventName=CreateAccessKey và actor=<user>"

Ví dụ subject của email:

`[CRITICAL][Audit] CreateAccessKey by arn:aws:iam::197826770971:user/CDO02 from 203.x.x.x (TTD 47s)`

Phần nội dung email nên đủ ngắn để đọc được trên điện thoại.

---

## 6. Nên đo time-to-detect như thế nào

### 6.1. Cam kết được khuyến nghị

Cam kết công khai được khuyến nghị:

- **Cam kết với mentor**: cảnh báo tới tay một người trong vòng **<= 5 phút**
- **Mục tiêu nội bộ**: median **< 90 giây**, p95 **< 180 giây**

Vì sao mức này phù hợp:

- nó thực tế với độ dao động trễ của AWS event;
- nó đủ mạnh để chứng minh đây là phát hiện chủ động;
- nó tránh overcommit vào một mục tiêu không thực tế như "dưới 30 giây".

### 6.2. Cách tính

Trong Lambda cảnh báo:

- lấy `event_time = detail.eventTime` từ CloudTrail event;
- tính `detected_at = now()`;
- tính `ttd_seconds = detected_at - event_time`.

Sau đó:

- đưa `ttd_seconds` vào payload cảnh báo;
- ghi JSON có cấu trúc vào CloudWatch Logs;
- publish custom metric như `AuditDetectionLatencySeconds`.

### 6.3. Cách chứng minh

Trước khi nộp:

1. Chạy ít nhất ba lần diễn tập thật.
2. Giữ lại:
   - timestamp của event từ CloudTrail;
   - email cảnh báo đã nhận;
   - log Lambda có chứa `ttd_seconds`.
3. Ghi một bảng bằng chứng đơn giản trong runbook:
   - event;
   - event time;
   - detected time;
   - `ttd_seconds`;
   - ngưỡng đã cam kết;
   - pass hay fail.

Điểm quan trọng:

- mentor không nên phải tin vào lời nói;
- chính cảnh báo nên hiển thị TTD;
- log và metric phải có sẵn để kiểm tra lại.

---

## 7. Kiểm soát nhiễu và cách mentor tự verify

### 7.1. Yêu cầu kiểm soát nhiễu

Để hệ thống đủ đáng tin và tránh mệt mỏi vì cảnh báo, detector nên áp dụng một tập quy tắc giảm nhiễu nhỏ nhưng rõ ràng:

- duy trì allowlist cho các automation principal đã biết, như role CI/CD và các IRSA role đã được phê duyệt;
- phân biệt human secret access với automation secret access;
- dùng suppression có giới hạn thời gian cho các đợt bảo trì, và mỗi suppression tối thiểu phải có:
  - `actor`
  - `resource`
  - `start`
  - `end`
  - `reason`
- suppression phải tự hết hạn thay vì để mở vô thời hạn;
- mặc định chỉ paging cho các nhóm rủi ro cao nhất:
  - Group 1 - làm mù audit
  - Group 2 - tạo đường truy cập mới
  - Group 4 - mở rộng quyền vào cluster hoặc runtime
- giữ Group 3 và Group 5 ở mức review hoặc high trừ khi actor hoặc target khiến chúng phải lên critical;
- đặt độ nghiêm trọng của Group 6 theo target, trong đó các hành vi phá hủy nhắm vào nơi giữ bằng chứng, KMS key, hoặc datastore quan trọng phải được coi là `critical`.

Đây là mức tối thiểu cần có để đáp ứng yêu cầu của directive rằng cảnh báo phải đủ đáng tin và không bị tắt tiếng vì quá nhiễu.

### 7.1.1. Cách triển khai tối thiểu

Cách triển khai tối thiểu được khuyến nghị nên giữ nhỏ gọn:

- giữ một file cấu hình detector ngay trong package của Lambda;
- lưu:
  - `allowed_principals`
  - `human_principals`
  - `secret_reader_principals`
  - `suppressions`
- mỗi suppression phải chứa:
  - `actor`
  - `resource`
  - `start`
  - `end`
  - `reason`
- detector nên đánh giá mỗi event theo thứ tự:
  1. kiểm tra principal có phải automation principal đã được phê duyệt hay không;
  2. kiểm tra có suppression hợp lệ và chưa hết hạn hay không;
  3. kiểm tra event có phải là secret access từ human principal hay không;
  4. ánh xạ event sang severity dựa trên nhóm event và target.

Ánh xạ severity mặc định được khuyến nghị:

- Group 1, Group 2, Group 4 -> `critical`
- Group 3, Group 5 -> `high`
- Group 6 -> `high` theo mặc định, và `critical` khi target là evidence store, KMS key, hoặc datastore quan trọng

Mức này đủ để trả lời các câu hỏi thường gặp của mentor về hoạt động CI/CD, automation đã được phê duyệt, và bảo trì có kế hoạch mà không cần xây cả một hệ thống quản lý cảnh báo đầy đủ hay thêm hạ tầng cấu hình riêng.

### 7.2. Kỳ vọng để mentor tự verify

Mentor phải có thể thực hiện một hành động vô hại nhưng rõ ràng là nguy hiểm và tự xác minh kết quả mà không cần dựa vào giải thích bằng lời.

Vì vậy, luồng verification nên cho thấy:

- hành động mà mentor đã thực hiện;
- cảnh báo tương ứng tới trong ngưỡng đã cam kết;
- nội dung cảnh báo:
  - ai
  - làm gì
  - khi nào
  - từ đâu
  - time-to-detect
- đường đi đầu-cuối của cảnh báo:
  - nguồn event
  - bước xử lý
  - kênh nhận

Các hành động phù hợp để mentor tự verify gồm:

- `iam:CreateAccessKey`, với lưu ý triển khai quan trọng là mentor có thể thực hiện thao tác này từ bất kỳ console region hoặc vị trí nào, nhưng rule phát hiện cho IAM event này nên được triển khai ở `us-east-1`
- `eks:CreateAccessEntry`
- `cloudtrail:StopLogging` rồi `cloudtrail:StartLogging` trên một target test đã được phê duyệt

Điểm quan trọng không nằm ở đúng một hành động test cụ thể, mà là mentor có thể tự nhìn thấy cảnh báo, đường định tuyến, và thời gian phát hiện đã đo được.

---

## 8. Góc nhìn về chi phí

Với thiết kế đã khoanh vùng là management events + EventBridge + Lambda + SNS email:

- chi phí sẽ rất nhỏ so với ngưỡng `$300/tuần`;
- nó hiệu quả chi phí hơn nhiều so với việc đưa Security Hub, GuardDuty, hoặc SIEM vào chỉ cho mandate này.

Các guardrail quan trọng:

- không bật data event không cần thiết;
- chỉ theo dõi secret-access cho những secret thực sự nhạy cảm;
- không giữ retention vô hạn cho Lambda log và detector log trên CloudWatch.

Thời gian retention ngắn như 14 đến 30 ngày thường là đủ, trừ khi có yêu cầu lưu trữ audit riêng.

---

## 9. Tài liệu xác minh và retry follow-up

- [Xác minh tĩnh Group 1 và Group 2](mandate11-group1-group2-verification.md): đối chiếu event catalog, EventBridge rule, Lambda mapping, severity, cảnh báo và các blocker phải đóng trước runtime acceptance.
- [Thiết kế Lambda retry và xử lý sự kiện lỗi](mandate11-lambda-retry-design.md): tách retry EventBridge/Lambda, DLQ, IAM, idempotency, monitoring, replay và kế hoạch kiểm thử sau khi hạ tầng sẵn sàng.

Hai tài liệu follow-up trên không thay thế bằng chứng chạy thật. Trạng thái chỉ được đổi sang `VERIFIED` sau khi có CloudTrail event, Lambda log, SNS email và số liệu TTD đầu-cuối từ môi trường đã deploy.
