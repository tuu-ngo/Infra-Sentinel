variable "region" {
  description = "AWS region chính duy nhất được phép deploy Mandate 12."
  type        = string
  default     = "ap-southeast-1"

  validation {
    condition     = var.region == "ap-southeast-1"
    error_message = "Mandate 12 hiện chỉ được deploy tại ap-southeast-1."
  }
}

variable "global_event_region" {
  description = "Region bat buoc cho EventBridge/SNS alert doi voi IAM global-service events."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.global_event_region == "us-east-1"
    error_message = "IAM global-service events cua CloudTrail phai duoc bat tai us-east-1 trong foundation nay."
  }
}

variable "audit_bucket_name" {
  description = "Tên MỚI, duy nhất toàn cầu cho audit bucket. Object Lock chỉ bật được khi tạo bucket."
  type        = string
}

variable "trail_name" {
  description = "Tên CloudTrail account-level."
  type        = string
  default     = "tf3-m12-audit"
}

variable "retention_days" {
  description = "Default Object Lock COMPLIANCE retention; phải >= 365."
  type        = number
  default     = 365

  validation {
    condition     = var.retention_days >= 365
    error_message = "Mandate 12 yêu cầu retention ít nhất 365 ngày."
  }
}

variable "s3_data_event_arns" {
  description = "ARN prefix S3 nhạy cảm đã được owner duyệt, ví dụ arn:aws:s3:::bucket/prefix/. Bắt buộc có ít nhất một prefix."
  type        = list(string)

  validation {
    condition = length(var.s3_data_event_arns) > 0 && alltrue([
      for arn in var.s3_data_event_arns : can(regex("^arn:aws:s3:::[^/]+/.+", arn))
    ])
    error_message = "Phải khai báo ít nhất một ARN prefix S3 hợp lệ trước khi deploy Mandate 12."
  }
}

variable "alert_email" {
  description = "Email security owner nhan canh bao o ca ap-southeast-1 va us-east-1. Hai SNS subscription phai duoc xac nhan sau apply."
  type        = string

  validation {
    condition     = trimspace(var.alert_email) != ""
    error_message = "Phải khai báo alert_email trước khi deploy Mandate 12."
  }
}
