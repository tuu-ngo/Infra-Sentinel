// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
// M9-03: Unit tests cho IdempotencyChecker

using Microsoft.Extensions.Logging;
using Moq;
using Oteldemo;
using Xunit;

namespace Accounting.Tests;

public class IdempotencyCheckerTests
{
    private readonly Mock<ILogger> _mockLogger;

    public IdempotencyCheckerTests()
    {
        _mockLogger = new Mock<ILogger>();
    }

    [Fact]
    public void Compare_ValidReplay_WhenPayloadMatches()
    {
        // Arrange: Tạo incoming order
        var incomingOrder = CreateSampleOrder("order-123", "prod-A", 2, 1000);

        // Tạo existing entities khớp hoàn toàn
        var existingOrder = new OrderEntity { Id = "order-123" };
        var existingItems = new List<OrderItemEntity>
        {
            new OrderItemEntity
            {
                OrderId = "order-123",
                ProductId = "prod-A",
                Quantity = 2,
                ItemCostCurrencyCode = "USD",
                ItemCostUnits = 1000,
                ItemCostNanos = 0
            }
        };
        var existingShipping = new ShippingEntity
        {
            OrderId = "order-123",
            ShippingTrackingId = "track-456",
            ShippingCostCurrencyCode = "USD",
            ShippingCostUnits = 500,
            ShippingCostNanos = 0,
            StreetAddress = "123 Main St",
            City = "SF",
            State = "CA",
            Country = "US",
            ZipCode = "94102"
        };

        // Act
        var result = IdempotencyChecker.Compare(
            incomingOrder,
            existingOrder,
            existingItems,
            existingShipping,
            _mockLogger.Object);

        // Assert
        Assert.Equal(IdempotencyResult.ValidReplay, result);
    }

    [Fact]
    public void Compare_ConflictDlq_WhenItemCountMismatch()
    {
        // Arrange
        var incomingOrder = CreateSampleOrder("order-123", "prod-A", 2, 1000);

        var existingOrder = new OrderEntity { Id = "order-123" };
        var existingItems = new List<OrderItemEntity>(); // EMPTY - mismatch count
        var existingShipping = CreateSampleShipping("order-123");

        // Act
        var result = IdempotencyChecker.Compare(
            incomingOrder,
            existingOrder,
            existingItems,
            existingShipping,
            _mockLogger.Object);

        // Assert
        Assert.Equal(IdempotencyResult.ConflictDlq, result);
    }

    [Fact]
    public void Compare_ConflictDlq_WhenItemQuantityDifferent()
    {
        // Arrange
        var incomingOrder = CreateSampleOrder("order-123", "prod-A", 2, 1000);

        var existingOrder = new OrderEntity { Id = "order-123" };
        var existingItems = new List<OrderItemEntity>
        {
            new OrderItemEntity
            {
                OrderId = "order-123",
                ProductId = "prod-A",
                Quantity = 999, // KHÁC với incoming (2)
                ItemCostCurrencyCode = "USD",
                ItemCostUnits = 1000,
                ItemCostNanos = 0
            }
        };
        var existingShipping = CreateSampleShipping("order-123");

        // Act
        var result = IdempotencyChecker.Compare(
            incomingOrder,
            existingOrder,
            existingItems,
            existingShipping,
            _mockLogger.Object);

        // Assert
        Assert.Equal(IdempotencyResult.ConflictDlq, result);
    }

    [Fact]
    public void Compare_ConflictDlq_WhenShippingAddressDifferent()
    {
        // Arrange
        var incomingOrder = CreateSampleOrder("order-123", "prod-A", 2, 1000);

        var existingOrder = new OrderEntity { Id = "order-123" };
        var existingItems = new List<OrderItemEntity>
        {
            new OrderItemEntity
            {
                OrderId = "order-123",
                ProductId = "prod-A",
                Quantity = 2,
                ItemCostCurrencyCode = "USD",
                ItemCostUnits = 1000,
                ItemCostNanos = 0
            }
        };
        var existingShipping = new ShippingEntity
        {
            OrderId = "order-123",
            ShippingTrackingId = "track-456",
            ShippingCostCurrencyCode = "USD",
            ShippingCostUnits = 500,
            ShippingCostNanos = 0,
            StreetAddress = "999 DIFFERENT St", // KHÁC
            City = "SF",
            State = "CA",
            Country = "US",
            ZipCode = "94102"
        };

        // Act
        var result = IdempotencyChecker.Compare(
            incomingOrder,
            existingOrder,
            existingItems,
            existingShipping,
            _mockLogger.Object);

        // Assert
        Assert.Equal(IdempotencyResult.ConflictDlq, result);
    }

    [Fact]
    public void Compare_TransientError_WhenOrderNotFound()
    {
        // Arrange
        var incomingOrder = CreateSampleOrder("order-123", "prod-A", 2, 1000);
        var existingItems = new List<OrderItemEntity>();
        var existingShipping = CreateSampleShipping("order-123");

        // Act
        var result = IdempotencyChecker.Compare(
            incomingOrder,
            null, // Order NULL (race condition)
            existingItems,
            existingShipping,
            _mockLogger.Object);

        // Assert
        Assert.Equal(IdempotencyResult.TransientError, result);
    }

    [Fact]
    public void Compare_TransientError_WhenShippingNotFound()
    {
        // Arrange
        var incomingOrder = CreateSampleOrder("order-123", "prod-A", 2, 1000);
        var existingOrder = new OrderEntity { Id = "order-123" };
        var existingItems = new List<OrderItemEntity>
        {
            new OrderItemEntity
            {
                OrderId = "order-123",
                ProductId = "prod-A",
                Quantity = 2,
                ItemCostCurrencyCode = "USD",
                ItemCostUnits = 1000,
                ItemCostNanos = 0
            }
        };

        // Act
        var result = IdempotencyChecker.Compare(
            incomingOrder,
            existingOrder,
            existingItems,
            null, // Shipping NULL
            _mockLogger.Object);

        // Assert
        Assert.Equal(IdempotencyResult.TransientError, result);
    }

    // Helper: Tạo sample OrderResult (protobuf)
    private OrderResult CreateSampleOrder(string orderId, string productId, int quantity, long costUnits)
    {
        var order = new OrderResult
        {
            OrderId = orderId,
            ShippingTrackingId = "track-456",
            ShippingCost = new Money
            {
                CurrencyCode = "USD",
                Units = 500,
                Nanos = 0
            },
            ShippingAddress = new Address
            {
                StreetAddress = "123 Main St",
                City = "SF",
                State = "CA",
                Country = "US",
                ZipCode = "94102"
            }
        };

        order.Items.Add(new OrderResult.Types.OrderItem
        {
            Item = new CartItem
            {
                ProductId = productId,
                Quantity = quantity
            },
            Cost = new Money
            {
                CurrencyCode = "USD",
                Units = costUnits,
                Nanos = 0
            }
        });

        return order;
    }

    // Helper: Tạo sample ShippingEntity
    private ShippingEntity CreateSampleShipping(string orderId)
    {
        return new ShippingEntity
        {
            OrderId = orderId,
            ShippingTrackingId = "track-456",
            ShippingCostCurrencyCode = "USD",
            ShippingCostUnits = 500,
            ShippingCostNanos = 0,
            StreetAddress = "123 Main St",
            City = "SF",
            State = "CA",
            Country = "US",
            ZipCode = "94102"
        };
    }
}
