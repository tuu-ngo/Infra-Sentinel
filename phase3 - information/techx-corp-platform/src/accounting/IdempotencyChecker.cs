// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
// M9-03: IdempotencyChecker - tách logic verify ra để dễ unit test

using Microsoft.Extensions.Logging;
using Oteldemo;

namespace Accounting;

/// <summary>
/// M9-03: Kết quả của idempotency check.
/// </summary>
internal enum IdempotencyResult
{
    /// <summary>Payload khớp hoàn toàn → commit offset, không persist lại.</summary>
    ValidReplay,

    /// <summary>Payload KHÁC → DLQ + alert, nhưng commit để không block partition.</summary>
    ConflictDlq,

    /// <summary>Lỗi transient khi verify → không commit, retry.</summary>
    TransientError,
}

/// <summary>
/// M9-03: Chứa logic so sánh aggregate để verify idempotent replay.
/// Tách ra khỏi Consumer.cs để unit test độc lập.
/// </summary>
internal static class IdempotencyChecker
{
    /// <summary>
    /// So sánh incoming OrderResult với aggregate đã tồn tại trong DB.
    /// Trả về IdempotencyResult để Consumer quyết định commit hay retry.
    /// </summary>
    public static IdempotencyResult Compare(
        OrderResult incoming,
        OrderEntity? existingOrder,
        IReadOnlyList<OrderItemEntity> existingItems,
        ShippingEntity? existingShipping,
        ILogger logger)
    {
        // Order không tồn tại (race condition)
        if (existingOrder == null)
        {
            logger.LogError("Order {OrderId} caused 23505 but not found in DB. Race condition?",
                incoming.OrderId);
            return IdempotencyResult.TransientError;
        }

        // Shipping không tồn tại (partial state)
        if (existingShipping == null)
        {
            logger.LogError("Order {OrderId} exists but shipping missing. Partial replay?",
                incoming.OrderId);
            return IdempotencyResult.TransientError;
        }

        // Compare item count
        if (existingItems.Count != incoming.Items.Count)
        {
            logger.LogError(
                "Order {OrderId} item count mismatch: existing={Existing}, incoming={Incoming}. DLQ.",
                incoming.OrderId, existingItems.Count, incoming.Items.Count);
            return IdempotencyResult.ConflictDlq;
        }

        // Compare từng item theo ProductId
        foreach (var incomingItem in incoming.Items)
        {
            var matchingItem = existingItems.FirstOrDefault(
                ei => ei.ProductId == incomingItem.Item.ProductId);

            if (matchingItem == null)
            {
                logger.LogError(
                    "Order {OrderId} missing product={ProductId} in DB. DLQ.",
                    incoming.OrderId, incomingItem.Item.ProductId);
                return IdempotencyResult.ConflictDlq;
            }

            if (matchingItem.ItemCostCurrencyCode != incomingItem.Cost.CurrencyCode ||
                matchingItem.ItemCostUnits        != incomingItem.Cost.Units        ||
                matchingItem.ItemCostNanos        != incomingItem.Cost.Nanos        ||
                matchingItem.Quantity             != incomingItem.Item.Quantity)
            {
                logger.LogError(
                    "Order {OrderId} item mismatch for product={ProductId}. DLQ.",
                    incoming.OrderId, incomingItem.Item.ProductId);
                return IdempotencyResult.ConflictDlq;
            }
        }

        // Compare shipping
        if (existingShipping.ShippingTrackingId     != incoming.ShippingTrackingId       ||
            existingShipping.ShippingCostCurrencyCode != incoming.ShippingCost.CurrencyCode ||
            existingShipping.ShippingCostUnits      != incoming.ShippingCost.Units        ||
            existingShipping.ShippingCostNanos      != incoming.ShippingCost.Nanos        ||
            existingShipping.StreetAddress          != incoming.ShippingAddress.StreetAddress ||
            existingShipping.City                   != incoming.ShippingAddress.City      ||
            existingShipping.State                  != incoming.ShippingAddress.State     ||
            existingShipping.Country                != incoming.ShippingAddress.Country   ||
            existingShipping.ZipCode                != incoming.ShippingAddress.ZipCode)
        {
            logger.LogError("Order {OrderId} shipping mismatch. DLQ.", incoming.OrderId);
            return IdempotencyResult.ConflictDlq;
        }

        // Tất cả khớp → valid replay
        logger.LogInformation("Order {OrderId} is valid idempotent replay.", incoming.OrderId);
        return IdempotencyResult.ValidReplay;
    }
}
