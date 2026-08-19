// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { ChannelOptions } from '@grpc/grpc-js';

/**
 * Mandate #19 — cân tải phía client cho các hop gRPC của frontend.
 *
 * VẤN ĐỀ ĐO ĐƯỢC (30/07/2026, docs/evidence/mandate-19/real-2026-07-30/):
 * frontend gọi backend qua Service ClusterIP (`product-catalog:8080`). gRPC giữ
 * MỘT kết nối TCP dài hạn, và kube-proxy ghim kết nối đó vào ĐÚNG MỘT pod. Hệ quả
 * đo trực tiếp bằng `kubectl top pod` khi product-catalog đang ở 11 replica:
 *
 *     xxhsp 353m · cw8nx 136m · pzcxg 11m · 8 pod còn lại 1-2m
 *
 * Tám pod rỗng hoàn toàn. HPA thấy CPU trung bình 48% nên không scale thêm, trong
 * khi pod nóng chính là pod làm vỡ deadline và sinh HTTP 500 trên /api/products/[id].
 * Đây là lý do nới maxReplicas ở PR #649 KHÔNG nâng được trần: replica thêm vào là
 * dung lượng mà traffic không bao giờ tới được.
 *
 * CÁCH SỬA: DNS headless (trả về TẤT CẢ pod IP) + `round_robin` phía client. Phải
 * đủ CẢ HAI:
 *   - Chỉ đổi sang headless mà giữ `pick_first` (mặc định của gRPC) thì client vẫn
 *     chỉ dùng IP đầu tiên -> vẫn ghim một pod.
 *   - Chỉ đặt `round_robin` mà giữ ClusterIP thì DNS chỉ trả về 1 VIP -> không có
 *     gì để xoay vòng.
 *
 * Cùng pattern mà hop `frontend-proxy -> frontend` đã dùng (`frontend-headless`),
 * và đó cũng là lý do CPU của frontend trải đều 123-138m trong khi backend lệch.
 *
 * `dns:///` là bắt buộc: không có scheme, gRPC-js coi chuỗi là địa chỉ đơn và bỏ
 * qua bản ghi DNS còn lại.
 */
export const loadBalancedChannelOptions: Partial<ChannelOptions> = {
  'grpc.service_config': JSON.stringify({
    loadBalancingConfig: [{ round_robin: {} }],
  }),
  // Bắt gRPC phân giải lại DNS thường xuyên hơn mặc định 30s. Pod backend bị HPA
  // thay liên tục dưới tải; 30s là quá lâu để nhận pod mới và bỏ pod đã chết.
  'grpc.dns_min_time_between_resolutions_ms': 5000,
  // Giữ kết nối sống qua các khoảng nghỉ để không phải bắt tay lại giữa burst.
  'grpc.keepalive_time_ms': 20000,
  'grpc.keepalive_timeout_ms': 5000,
  'grpc.keepalive_permit_without_calls': 1,
};

/**
 * Chuẩn hoá địa chỉ backend về dạng gRPC hiểu là "phân giải DNS, dùng mọi bản ghi".
 * Giữ nguyên nếu địa chỉ đã có scheme, để override bằng env vẫn thắng.
 */
export const dnsTarget = (addr: string): string =>
  addr.includes('://') ? addr : `dns:///${addr}`;
