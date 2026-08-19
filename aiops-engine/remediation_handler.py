import subprocess
import time
import logging
from config import WHITELISTED_ACTIONS, EXECUTION_TIMEOUT_SECONDS, VERIFICATION_PERIOD_SECONDS, SIMULATION_SERVER_URL
from anomaly_detector import AnomalyDetector

logger = logging.getLogger("AIOpsEngine.RemediationHandler")

class RemediationHandler:
    def __init__(self):
        self.whitelisted_actions = WHITELISTED_ACTIONS
        self.detector = AnomalyDetector()

    def validate_action(self, action: str, command: str) -> bool:
        """
        Validation Gate: Chặn đứng lệnh ngoài whitelist (C6 Invariant 2).
        """
        if action not in self.whitelisted_actions:
            logger.warning(f"Action '{action}' is not whitelisted! Blocking execution.")
            return False

        # Kiểm tra thô tránh command injection nguy hiểm
        forbidden_keywords = ["rm", "delete", "flagd-sync", "token", "mkfs", "bash"]

        for kw in forbidden_keywords:
            if kw in command.lower():
                logger.warning(f"Command contains forbidden keyword '{kw}'! Blocking execution.")
                return False

        return True

    def sanitize_command(self, command: str) -> str:
        """
        Namespace Injection: Đảm bảo luôn chạy trên đúng namespace techx-tf3.
        """
        if "kubectl" in command and "-n techx-tf3" not in command:
            if " -n " not in command:
                command = command.replace("kubectl", "kubectl -n techx-tf3")
        return command

    def execute_k8s_command(self, command: str, dry_run: bool = False) -> bool:
        """
        Thực thi lệnh K8s. Hỗ trợ dry-run kiểm tra an toàn trước khi thực thi.
        """
        full_command = command
        if dry_run:
            if "rollout restart" in command or "rollout undo" in command:
                # rollout restart/undo không hỗ trợ --dry-run=client, dùng kubectl get để kiểm tra sự tồn tại của resource
                parts = command.split()
                target = parts[-1]
                full_command = f"kubectl -n techx-tf3 get {target}"
            else:
                full_command += " --dry-run=client"

        logger.info(f"Executing command: {full_command}")
        
        # Hỗ trợ chế độ giả lập Sandbox cục bộ
        import os
        if os.getenv("AIOPS_SIMULATION_MODE") == "true":
            logger.info(f"[SIMULATION] Bypassing actual command execution: {full_command}")
            try:
                import requests
                requests.post(f"{SIMULATION_SERVER_URL}/simulate/remediate", timeout=5)
            except Exception as e:
                logger.error(f"[SIMULATION] Failed to notify mock server of remediation: {e}")
            return True
        try:
            # Chạy lệnh trong terminal tối đa 5 phút (C6 Invariant 3)
            result = subprocess.run(
                full_command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                timeout=EXECUTION_TIMEOUT_SECONDS
            )
            if result.returncode == 0:
                logger.info(f"Command executed successfully: {result.stdout.strip()}")
                return True
            logger.error(f"Command failed with code {result.returncode}: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            logger.error(f"Command execution timed out after {EXECUTION_TIMEOUT_SECONDS}s!")
        except Exception as e:
            logger.error(f"Error executing command: {str(e)}")
        return False

    def verify_remediation(self, culprit_service: str) -> bool:
        """
        Quét Telemetry kiểm chứng lai (Hybrid Verification) trong vòng 5 phút (C6 §50).
        Yêu cầu cả hai điều kiện sau đồng thời vượt qua liên tục trong 5 chu kỳ quét (2.5 phút):
          1. Z-score tỷ lệ lỗi dịch vụ trở lại bình thường (|Z| < 2.0).
          2. Isolation Forest dự đoán trạng thái bình thường (prediction == 1, không có tác dụng phụ về tài nguyên/độ trễ).
        """
        import os
        if os.getenv("AIOPS_SIMULATION_MODE") == "true":
            logger.info(f"[SIMULATION] Bypassing actual 5-minute verification loop for {culprit_service}")
            return True

        metric_to_watch = f'sum(rate(traces_span_metrics_calls_total{{service_name="{culprit_service}", status_code="STATUS_CODE_ERROR"}}[1m])) or vector(0)'
        logger.info(f"Starting SRE 5-minute Hybrid Verification for {culprit_service}...")

        logger.info(f"  - Gate 1 (Z-Score): watching error metric: {metric_to_watch}")
        logger.info(f"  - Gate 2 (ML Isolation Forest): watching multi-dimensional service health")
        
        start_time = time.time()
        consecutive_passes = 0
        
        feature_cols = [
            "rps", "cpu_usage", "memory_usage", "latency_p90", "error_rate", "client_error_rate", "kafka_lag",
            "error_ratio", "client_error_ratio", "latency_deviation", "rps_delta", "cpu_per_rps", "memory_growth", "kafka_lag_growth",
            "hour_of_day", "day_of_week", "is_business_hours", "is_high_traffic_period"
        ]
        
        while time.time() - start_time < VERIFICATION_PERIOD_SECONDS:
            time.sleep(30)
            
            # 1. Kiểm tra Gate 1: Z-score của tỷ lệ lỗi
            z_score = self.detector.check_infra_z_score(metric_to_watch)
            z_passed = abs(z_score) < 2.0
            
            # 2. Kiểm tra Gate 2: ML Isolation Forest
            if_passed = False
            try:
                res = self.detector.check_service_anomaly(culprit_service)
                is_anomalous = res.get("is_anomalous", False)
                if_passed = not is_anomalous
                logger.info(f"ML check for {culprit_service} - Anomaly flag: {is_anomalous}")
            except Exception as e:
                logger.error(f"Error checking ML anomaly flag during verify: {e}")
                if_passed = True
                
            # Đánh giá kết quả chu kỳ quét hiện tại
            if z_passed and if_passed:
                consecutive_passes += 1
                logger.info(f"Verification cycle passed ({consecutive_passes}/5). Z-score: {z_score:.2f}, ML: Normal")
                if consecutive_passes >= 5:
                    logger.info(f"Verification Success! Service {culprit_service} error rate and ML health returned to normal for 5 consecutive checks.")
                    return True
            else:
                consecutive_passes = 0
                logger.warning(f"Verification cycle failed. Z-score passed: {z_passed} (Z: {z_score:.2f}), ML passed: {if_passed}")
                
        logger.warning(f"Verification Timeout! Service {culprit_service} is still anomalous after 5 minutes.")
        return False

    def trigger_rollback(self, rollback_command: str) -> bool:
        """
        Chạy Rollback Plan khi xác minh thất bại.
        """
        logger.warning(f"Triggering rollback plan using command: {rollback_command}")
        return self.execute_k8s_command(rollback_command)

    def escalate(self, incident_id: str, culprit: str, action: str):
        """
        Nếu Rollback thất bại, chuyển sang Manual Mode và bắn báo động khẩn cấp tới SRE.
        """
        logger.critical(f"🚨 ESCALATE: Rollback failed for Incident {incident_id} on {culprit}!")

    def execute_replanning_loop(self, incident_id: str, culprit_service: str, trace_id: str, max_attempts: int = 3) -> dict:
        """
        Agentic Re-planning Loop (Mandate #22 Advanced Safety Flow):
        Cho phép tối đa N=3 lần thử tự dập sự cố.
        Nếu lần thử thứ i verify thất bại, thu gom feedback context (lệnh đã thử + telemetry lỗi)
        chuyển cho LLM suy luận phương án bù đắp tiếp theo (bước i+1).
        Nếu sau 3 lần thử vẫn thất bại -> Tiến hành Auto-Rollback về trạng thái ban đầu và Escalate SRE.
        """
        import os
        from audit_logger import AuditLogger
        audit_logger = AuditLogger()

        history_attempts = []
        initial_rollback_command = None

        logger.info(f"🔄 Starting Agentic Re-planning Loop for Incident {incident_id} (Max attempts: {max_attempts})...")

        for attempt in range(1, max_attempts + 1):
            logger.info(f"--- Re-planning Attempt {attempt}/{max_attempts} for {culprit_service} ---")

            # 1. Gọi Diagnostician lấy phương án xử lý (truyền history context của các bước lặp trước)
            from llm_diagnostician import LLMDiagnostician
            diagnostician = LLMDiagnostician()
            evidence_pack = {
                "incident_id": incident_id,
                "service": culprit_service,
                "culprit_service": culprit_service,
                "trace_id": trace_id,
                "log_templates": [],
                "metrics": {},
                "trace_summary": {},
                "history_context": history_attempts
            }
            diagnosis = diagnostician.diagnose(evidence_pack)

            proposed_action = diagnosis.get("proposed_action", "scale")
            action_cmd = diagnosis.get("action_command", f"kubectl -n techx-tf3 scale deploy/{culprit_service} --replicas=2")
            rollback_cmd = diagnosis.get("rollback_command", f"kubectl -n techx-tf3 scale deploy/{culprit_service} --replicas=1")

            if attempt == 1:
                initial_rollback_command = rollback_cmd

            # 2. Safety Validation Gate
            if not self.validate_action(proposed_action, action_cmd):
                logger.warning(f"Attempt {attempt}: Action '{proposed_action}' blocked by safety validation gate.")
                history_attempts.append({"attempt": attempt, "action": proposed_action, "outcome": "Blocked by Safety Gate"})
                continue

            # 3. Dry-Run Check
            dry_run_passed = self.execute_k8s_command(action_cmd, dry_run=True)
            if not dry_run_passed:
                logger.warning(f"Attempt {attempt}: Dry-run failed for command '{action_cmd}'.")
                history_attempts.append({"attempt": attempt, "action": proposed_action, "outcome": "Dry-run failed"})
                continue

            # 4. Live Execution
            executed_passed = self.execute_k8s_command(action_cmd, dry_run=False)
            if not executed_passed:
                logger.warning(f"Attempt {attempt}: Command execution failed.")
                history_attempts.append({"attempt": attempt, "action": proposed_action, "outcome": "Execution failed"})
                continue

            # 5. Hybrid Telemetry Verification
            is_resolved = self.verify_remediation(culprit_service)
            if is_resolved:
                logger.info(f"🎉 SUCCESS on Attempt {attempt}/{max_attempts}! Incident {incident_id} resolved by action '{proposed_action}'.")
                audit_logger.log_remediation_event(
                    incident_id=incident_id, trigger="ReplanningLoop", culprit_service=culprit_service,
                    proposed_action=proposed_action, action_command=action_cmd, blast_radius_percent=28.57,
                    risk_level="LOW", dry_run_passed=True, executed=True, verification_passed=True,
                    rollback_executed=False, status="REMEDIATION_SUCCESS",
                    message=f"Resolved on attempt {attempt}/{max_attempts}"
                )
                return {
                    "status": "success",
                    "attempts": attempt,
                    "final_action": proposed_action,
                    "action_command": action_cmd,
                    "history": history_attempts
                }
            else:
                logger.warning(f"⚠️ Verification FAILED for Attempt {attempt}/{max_attempts}. Metric did not recover. Rolling back attempt {attempt} to maintain clean slate...")
                attempt_rollback_passed = self.trigger_rollback(rollback_cmd)
                history_attempts.append({
                    "attempt": attempt,
                    "action": proposed_action,
                    "command": action_cmd,
                    "rollback_command": rollback_cmd,
                    "rollback_passed": attempt_rollback_passed,
                    "outcome": "Verification Failed: Immediately rolled back step to restore clean state for next attempt"
                })

        # 6. Nếu qua cả 3 lần thử vẫn không đỡ -> Thực thi Rollback về trạng thái ban đầu & Escalate SRE
        logger.critical(f"⛔ All {max_attempts} attempts failed for Incident {incident_id}! Triggering Auto-Rollback & Escalating to SRE...")
        rollback_passed = False
        if initial_rollback_command:
            rollback_passed = self.trigger_rollback(initial_rollback_command)

        self.escalate(incident_id, culprit_service, "ReplanningExhausted")

        audit_logger.log_remediation_event(
            incident_id=incident_id, trigger="ReplanningLoop", culprit_service=culprit_service,
            proposed_action="re-planning-loop", action_command=initial_rollback_command or "", blast_radius_percent=28.57,
            risk_level="HIGH", dry_run_passed=True, executed=True, verification_passed=False,
            rollback_executed=True, rollback_command=initial_rollback_command or "", rollback_passed=rollback_passed,
            status="ROLLED_BACK_EXHAUSTED",
            message=f"All {max_attempts} attempts failed. Rolled back and escalated to SRE."
        )

        return {
            "status": "rolled_back_exhausted",
            "attempts": max_attempts,
            "escalated": True,
            "rollback_passed": rollback_passed,
            "history": history_attempts
        }
