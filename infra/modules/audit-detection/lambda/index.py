# Deploy marker: đổi giá trị này để ép re-deploy router qua CI khi cần đồng bộ
# lại hash. Lần apply hỏng trước để state lệch ba đằng (source_code_hash,
# code_sha256, CodeSha256 live) khiến invariant router-integrity của heartbeat
# FAIL giả. Bump marker → source_code_hash đổi → CI re-deploy → cả ba hội tụ về
# một hash. KHÔNG đổi logic; chỉ cần khác chuỗi cũ.
# router-deploy-marker: 2026-07-24.1
import json
import logging
import os
from datetime import datetime, timezone

import boto3


LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

SNS = boto3.client("sns")
CLOUDWATCH = boto3.client("cloudwatch")

ALERT_TOPIC_ARN = os.environ["ALERT_TOPIC_ARN"]
METRIC_NAMESPACE = os.environ.get("METRIC_NAMESPACE", "TechX/AuditDetection")
DEPLOYMENT_LABEL = os.environ.get("DEPLOYMENT_LABEL", "unknown")
CONFIG = json.loads(os.environ.get("DETECTOR_CONFIG_JSON", "{}"))

GROUP_MAP = {
    # Group 1 bắt các hành động làm mù audit/log. Đây là tín hiệu critical và
    # không được bỏ qua chỉ vì actor là automation; thay đổi hợp lệ phải dùng
    # suppression có phạm vi và thời hạn rõ ràng.
    "cloudtrail:StopLogging": 1,
    "cloudtrail:DeleteTrail": 1,
    "cloudtrail:UpdateTrail": 1,
    "cloudtrail:PutEventSelectors": 1,
    "cloudtrail:StartLogging": 1,
    "logs:DeleteLogGroup": 1,
    "logs:PutRetentionPolicy": 1,
    # Group 2 bắt việc tạo credential hoặc principal mới để mở thêm đường truy
    # cập. CI/CD hợp lệ vẫn phải để lại tín hiệu hoặc dùng suppression có thời
    # hạn thay vì allowlist vĩnh viễn.
    "iam:CreateAccessKey": 2,
    "iam:CreateUser": 2,
    "iam:CreateRole": 2,
    "iam:CreateLoginProfile": 2,
    # Group 3 bắt các hành động mở rộng quyền IAM. Kể cả khi actor là CI/CD
    # hoặc Terraform automation role, event vẫn phải alert hoặc có suppression
    # có thời hạn cho change đã được duyệt.
    "iam:UpdateAssumeRolePolicy": 3,
    "iam:AttachUserPolicy": 3,
    "iam:AttachRolePolicy": 3,
    "iam:PutUserPolicy": 3,
    "iam:PutRolePolicy": 3,
    "iam:CreatePolicyVersion": 3,
    "iam:SetDefaultPolicyVersion": 3,
    "iam:AddUserToGroup": 3,
    "iam:UpdateUser": 3,
    "eks:CreateAccessEntry": 4,
    "eks:UpdateAccessEntry": 4,
    "eks:DeleteAccessEntry": 4,
    "eks:AssociateAccessPolicy": 4,
    "eks:DisassociateAccessPolicy": 4,
    # Group 5 bắt các lần đọc secret nhạy cảm từ người dùng hoặc principal lạ.
    # Automation hợp lệ được lọc riêng bằng secret_reader_principals, không dùng
    # allowlist automation rộng để tránh che mất truy cập secret bất thường.
    "secretsmanager:BatchGetSecretValue": 5,
    "secretsmanager:GetSecretValue": 5,
    "eks:DeleteCluster": 6,
    "eks:DeleteNodegroup": 6,
    "rds:DeleteDBInstance": 6,
    "rds:DeleteDBCluster": 6,
    "elasticache:DeleteReplicationGroup": 6,
    "elasticache:DeleteCacheCluster": 6,
    "kms:ScheduleKeyDeletion": 6,
    "secretsmanager:DeleteSecret": 6,
    "s3:DeleteBucket": 6,
    # Group 7 (Mandate 12) bắt thay đổi lên chính alert plane và heartbeat:
    # EventBridge rule/target, SNS topic/subscription, Lambda router và các
    # control của audit bucket. Event pattern không lọc được resource, nên nhóm
    # này lọc bằng critical_group_7_target_keywords trong handler: chỉ event
    # nhắm vào resource audit mới đi tiếp, và khi đó nó nằm trong
    # critical_group_numbers nên không bị allowlist hay suppression làm im lặng.
    "events:DisableRule": 7,
    "events:DeleteRule": 7,
    "events:PutRule": 7,
    "events:RemoveTargets": 7,
    "events:PutTargets": 7,
    "sns:AddPermission": 7,
    "sns:RemovePermission": 7,
    "sns:DeleteTopic": 7,
    "sns:SetTopicAttributes": 7,
    "sns:Subscribe": 7,
    "sns:ConfirmSubscription": 7,
    "sns:SetSubscriptionAttributes": 7,
    "sns:Unsubscribe": 7,
    "lambda:DeleteFunction": 7,
    "lambda:UpdateFunctionCode": 7,
    "lambda:UpdateFunctionConfiguration": 7,
    # Đặt reserved concurrency = 0 làm router ngừng xử lý mà không xoá gì.
    "lambda:PutFunctionConcurrency": 7,
    "lambda:DeleteFunctionConcurrency": 7,
    "monitoring:DeleteAlarms": 7,
    "monitoring:DisableAlarmActions": 7,
    "monitoring:PutMetricAlarm": 7,
    "s3:PutBucketPolicy": 7,
    "s3:DeleteBucketPolicy": 7,
    "s3:PutBucketVersioning": 7,
    "s3:PutObjectLockConfiguration": 7,
    "s3:PutBucketLifecycleConfiguration": 7,
    "s3:DeleteBucketLifecycle": 7,
    "s3:PutBucketEncryption": 7,
    "s3:DeleteBucketEncryption": 7,
    "s3:PutPublicAccessBlock": 7,
    "s3:DeletePublicAccessBlock": 7,
    # Group 8 (Mandate 12) bắt thay đổi permissions boundary, policy
    # attachment và trust path OIDC. IAM là global service nên rule tương ứng
    # nằm ở us-east-1.
    "iam:PutUserPermissionsBoundary": 8,
    "iam:DeleteUserPermissionsBoundary": 8,
    "iam:PutRolePermissionsBoundary": 8,
    "iam:DeleteRolePermissionsBoundary": 8,
    "iam:DeletePolicy": 8,
    "iam:DeletePolicyVersion": 8,
    "iam:DeleteUserPolicy": 8,
    "iam:DeleteRolePolicy": 8,
    "iam:DetachUserPolicy": 8,
    "iam:DetachRolePolicy": 8,
    "iam:CreateOpenIDConnectProvider": 8,
    "iam:DeleteOpenIDConnectProvider": 8,
    "iam:UpdateOpenIDConnectProviderThumbprint": 8,
    "iam:AddClientIDToOpenIDConnectProvider": 8,
    "iam:RemoveClientIDFromOpenIDConnectProvider": 8,
}


def handler(event, _context):
    detail = event.get("detail", {})
    event_source = detail.get("eventSource", "")
    event_name = detail.get("eventName", "")
    event_key = f"{event_source.replace('.amazonaws.com', '')}:{event_name}"
    group = GROUP_MAP.get(event_key)

    if group is None:
        LOGGER.info(json.dumps({"ignored": True, "reason": "unmapped_event", "event_key": event_key}))
        return {"ignored": True, "reason": "unmapped_event", "event_key": event_key}

    actor = extract_actor(detail.get("userIdentity", {}))
    target = extract_target(detail, group)

    # Mandate 12: nhóm critical là các đòn nhắm vào chính hệ kiểm toán và vào
    # đường leo thang quyền. Nếu để chúng đi qua allowlist automation hoặc
    # suppression window thì một principal đã được tin cậy (CI/CD, Terraform
    # apply, deployer) có thể tắt audit mà không sinh cảnh báo nào — đúng kịch
    # bản Mandate 12 phải bắt được. Approved change vẫn tạo alert; người trực
    # đối chiếu change ID thay vì tắt cảnh báo.
    critical_groups = set(CONFIG.get("critical_group_numbers") or [])

    # Mandate 12: rule nhóm 7 khớp theo eventName và không lọc resource, nên nó
    # nhận cả PutMetricAlarm, UpdateFunctionCode hay PutBucketPolicy lên resource
    # chẳng liên quan gì tới audit plane. Để nguyên thì mọi terraform apply bình
    # thường đều thành CRITICAL không tắt được, và người trực sẽ lọc mail — đúng
    # cửa sổ mù mà mandate muốn chặn. Lọc theo target ở đây chứ không đưa
    # requestParameters vào event pattern: pattern sai một tên field là mất hẳn
    # event, còn ở đây sai thì cùng lắm là thừa alert.
    if group == 7 and not is_audit_plane_target(target):
        LOGGER.info(json.dumps({"ignored": True, "reason": "non_audit_target", "actor": actor, "target": target, "event_key": event_key}))
        return {"ignored": True, "reason": "non_audit_target", "actor": actor, "target": target, "event_key": event_key}

    if group not in critical_groups and is_allowed_automation(actor):
        LOGGER.info(json.dumps({"ignored": True, "reason": "allowlisted_automation", "actor": actor, "event_key": event_key}))
        return {"ignored": True, "reason": "allowlisted_automation", "actor": actor, "event_key": event_key}

    if group not in critical_groups and is_suppressed(actor, target):
        LOGGER.info(json.dumps({"ignored": True, "reason": "suppressed", "actor": actor, "target": target, "event_key": event_key}))
        return {"ignored": True, "reason": "suppressed", "actor": actor, "target": target, "event_key": event_key}

    if group == 5 and not should_alert_secret_read(actor, target):
        LOGGER.info(json.dumps({"ignored": True, "reason": "known_secret_reader_or_unwatched_secret", "actor": actor, "target": target}))
        return {"ignored": True, "reason": "known_secret_reader_or_unwatched_secret", "actor": actor, "target": target}

    event_time = parse_time(detail.get("eventTime"))
    detected_at = datetime.now(timezone.utc)
    ttd_seconds = max(0, int((detected_at - event_time).total_seconds()))
    severity = map_severity(group, target)
    resources = event.get("resources") or []
    rule_name = resources[0] if resources else "eventbridge-rule-unknown"

    payload = {
        "severity": severity,
        "group": group,
        "rule_name": rule_name,
        "event_name": event_name,
        "actor": {
            "principal": actor,
            "type": detail.get("userIdentity", {}).get("type"),
        },
        "when": {
            "eventTime": detail.get("eventTime"),
            "detectedAt": detected_at.isoformat(),
            "time_to_detect_seconds": ttd_seconds,
        },
        "from_where": {
            "sourceIPAddress": detail.get("sourceIPAddress"),
            "awsRegion": detail.get("awsRegion"),
            "userAgent": detail.get("userAgent"),
        },
        "target": target,
        "request_summary": summarize_request(detail.get("requestParameters", {})),
        "investigation_hint": f"Check CloudTrail for eventName={event_name} actor={actor}",
        "deployment_label": DEPLOYMENT_LABEL,
    }

    LOGGER.info(json.dumps(payload))
    try:
        publish_metric(group, severity, ttd_seconds)
    except Exception:
        LOGGER.exception("failed to publish detection latency metric")
    publish_alert(payload)
    return {"sent": True, "severity": severity, "group": group, "ttd_seconds": ttd_seconds}


def extract_actor(user_identity):
    actor_type = user_identity.get("type")
    session_issuer = (((user_identity.get("sessionContext") or {}).get("sessionIssuer")) or {})
    if session_issuer.get("arn"):
        return session_issuer["arn"]
    if user_identity.get("arn"):
        return user_identity["arn"]
    if user_identity.get("userName"):
        return user_identity["userName"]
    if user_identity.get("principalId"):
        return user_identity["principalId"]
    return actor_type or "unknown"


def extract_target(detail, group=None):
    request = detail.get("requestParameters") or {}

    if group == 4:
        cluster_name = request.get("name") or request.get("clusterName")
        principal_arn = request.get("principalArn")
        if cluster_name and principal_arn:
            return f"{cluster_name} principal={principal_arn}"
        if principal_arn:
            return str(principal_arn)

    if group == 5:
        secret_targets = []
        for key in ["secretId", "SecretId", "secretIdList", "SecretIdList", "secretIds", "SecretIds"]:
            value = request.get(key)
            if isinstance(value, list):
                secret_targets.extend(str(item) for item in value if item)
            elif value:
                secret_targets.append(str(value))
        if secret_targets:
            return ",".join(secret_targets)

    # Mandate 12: nhóm 7 trải trên 5 service, mỗi API đặt tên tham số một kiểu.
    # Danh sách key chung ở dưới không có alarmName/functionName/topicArn/rule
    # nên target của phần lớn event nhóm 7 sẽ ra "unknown" — mà target chính là
    # thứ quyết định event có phải đòn vào audit plane hay không.
    if group == 7:
        group_7_targets = []
        for key in [
            "name",              # events:PutRule / DeleteRule / DisableRule
            "rule",              # events:PutTargets / RemoveTargets
            "topicArn",          # sns:Subscribe / SetTopicAttributes / DeleteTopic
            "subscriptionArn",   # sns:Unsubscribe / SetSubscriptionAttributes
            "functionName",      # lambda:UpdateFunctionCode / PutFunctionConcurrency
            "alarmName",         # monitoring:PutMetricAlarm
            "alarmNames",        # monitoring:DeleteAlarms / DisableAlarmActions
            "bucketName",        # s3:PutBucketPolicy và các control bucket khác
        ]:
            value = request.get(key)
            if isinstance(value, list):
                group_7_targets.extend(str(item) for item in value if item)
            elif value:
                group_7_targets.append(str(value))
        if group_7_targets:
            return ",".join(group_7_targets)

    for key in [
        "userName",
        "roleName",
        "groupName",
        "secretId",
        "name",
        "clusterName",
        "trailName",
        "bucketName",
        "keyId",
        "dbInstanceIdentifier",
        "dbClusterIdentifier",
        "replicationGroupId",
        "cacheClusterId",
        "principalArn",
    ]:
        value = request.get(key)
        if value:
            return str(value)

    resources = detail.get("resources") or []
    if resources:
        first = resources[0]
        if isinstance(first, dict):
            return first.get("ARN") or first.get("arn") or json.dumps(first)
        return str(first)

    return "unknown"


def should_alert_secret_read(actor, target):
    target_name = target or ""
    watched = CONFIG.get("sensitive_secret_names") or []
    if watched and not any(secret_name in target_name for secret_name in watched):
        return False

    if matches_any(actor, CONFIG.get("secret_reader_principals") or []):
        return False

    return True


def is_allowed_automation(actor):
    return matches_any(actor, CONFIG.get("allowed_principals") or [])


def is_audit_plane_target(target):
    """Event nhóm 7 có nhắm vào resource của audit plane hay không.

    Hai đường fail-safe cố ý: config thiếu keyword, hoặc không trích được target,
    thì trả True — thà thừa một alert còn hơn im lặng bỏ qua một đòn thật.
    """
    keywords = CONFIG.get("critical_group_7_target_keywords") or []
    lowered = (target or "").strip().lower()
    if not keywords or not lowered or lowered == "unknown":
        return True
    return any(keyword in lowered for keyword in keywords)


def is_suppressed(actor, target):
    now = datetime.now(timezone.utc)
    for suppression in CONFIG.get("suppressions") or []:
        if suppression.get("actor") not in ("*", actor):
            continue
        resource = suppression.get("resource", "*")
        if resource not in ("*", target) and resource not in (target or ""):
            continue
        start = parse_time(suppression.get("start"), default_now=False)
        end = parse_time(suppression.get("end"), default_now=False)
        if not start or not end:
            LOGGER.warning(json.dumps({"ignored_suppression": True, "reason": "missing_or_invalid_window", "suppression": suppression}))
            continue
        if start <= now <= end:
            return True
    return False


def matches_any(actor, candidates):
    for candidate in candidates:
        if actor == candidate:
            return True
    return False


def map_severity(group, target):
    if group in set(CONFIG.get("critical_group_numbers") or []):
        return "critical"
    if group == 6:
        lowered_target = (target or "").lower()
        for keyword in CONFIG.get("critical_group_6_target_keywords") or []:
            if keyword in lowered_target:
                return "critical"
        return "high"
    if group in (3, 5):
        return "high"
    return "info"


def summarize_request(request_parameters):
    if not request_parameters:
        return {}
    summary = {}
    for key in sorted(request_parameters.keys()):
        if key.lower() in {"secretstring", "secretbinary"}:
            continue
        value = request_parameters[key]
        if isinstance(value, (dict, list)):
            summary[key] = json.dumps(value)[:200]
        else:
            summary[key] = str(value)[:200]
    return summary


def publish_metric(group, severity, ttd_seconds):
    CLOUDWATCH.put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[
            {
                "MetricName": "AuditDetectionLatencySeconds",
                "Unit": "Seconds",
                "Value": ttd_seconds,
                "Dimensions": [
                    {"Name": "DeploymentLabel", "Value": DEPLOYMENT_LABEL},
                    {"Name": "Group", "Value": str(group)},
                    {"Name": "Severity", "Value": severity},
                ],
            }
        ],
    )


def publish_alert(payload):
    subject = (
        f"[{payload['severity'].upper()}][Audit][{DEPLOYMENT_LABEL}] "
        f"{payload['event_name']} by {payload['actor']['principal']} "
        f"(TTD {payload['when']['time_to_detect_seconds']}s)"
    )
    SNS.publish(
        TopicArn=ALERT_TOPIC_ARN,
        Subject=subject[:100],
        Message=json.dumps(payload, indent=2),
    )


def parse_time(value, default_now=True):
    if not value:
        return datetime.now(timezone.utc) if default_now else None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        if default_now:
            LOGGER.warning(json.dumps({"invalid_time": value, "fallback": "now"}))
            return datetime.now(timezone.utc)
        return None
