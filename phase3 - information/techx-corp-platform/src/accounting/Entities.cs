// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
// M9-03: Thêm IdempotencyConstants để check ConstraintName chính xác

using Microsoft.EntityFrameworkCore;
using System.ComponentModel.DataAnnotations.Schema;

namespace Accounting;

[Table("shipping", Schema = "accounting")]
[PrimaryKey(nameof(ShippingTrackingId))]
internal class ShippingEntity
{

    public required string ShippingTrackingId { get; set; }

    public required string ShippingCostCurrencyCode { get; set; }

    public required long ShippingCostUnits { get; set; }

    public required int ShippingCostNanos { get; set; }

    public required string StreetAddress { get; set; }

    public required string City { get; set; }

    public required string State { get; set; }

    public required string Country { get; set; }

    public required string ZipCode { get; set; }

    public required string OrderId { get; set; }
}

[Table("orderitem", Schema = "accounting")]
[PrimaryKey(nameof(ProductId), nameof(OrderId))]
internal class OrderItemEntity
{
    public required string ItemCostCurrencyCode { get; set; }

    public required long ItemCostUnits { get; set; }

    public required int ItemCostNanos { get; set; }

    public required string ProductId { get; set; }

    public required int Quantity { get; set; }

    public required string OrderId { get; set; }
}

[Table("order", Schema = "accounting")]
[PrimaryKey(nameof(Id))]
internal class OrderEntity
{
    [Column("order_id")]
    public required string Id { get; set; }

}

/// <summary>
/// M9-03: Hằng số tên constraint dùng để kiểm tra idempotency.
/// PostgreSQL đặt tên mặc định là "{table}_pkey", EF Core snakecase → "order_pkey".
/// Verify: SELECT conname FROM pg_constraint WHERE conrelid='accounting.order'::regclass;
/// </summary>
internal static class IdempotencyConstants
{
    /// <summary>
    /// Constraint name cho PRIMARY KEY của bảng accounting."order" (order_id).
    /// 23505 với ConstraintName này = replay hợp lệ cùng order_id.
    /// </summary>
    public const string OrderPrimaryKeyConstraint = "order_pkey";

    /// <summary>
    /// Constraint name cho PRIMARY KEY của bảng accounting.orderitem (order_id, product_id).
    /// </summary>
    public const string OrderItemPrimaryKeyConstraint = "orderitem_pkey";

    /// <summary>
    /// Constraint name cho PRIMARY KEY của bảng accounting.shipping (shipping_tracking_id).
    /// </summary>
    public const string ShippingPrimaryKeyConstraint = "shipping_pkey";
}

