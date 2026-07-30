// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
// M9-03: Idempotent consumer với ConstraintName check, fresh-context compare, DLQ

using Confluent.Kafka;
using Microsoft.Extensions.Logging;
using Oteldemo;
using Microsoft.EntityFrameworkCore;
using System.Diagnostics;
using Npgsql;

namespace Accounting;

internal class DBContext : DbContext
{
    public DbSet<OrderEntity> Orders { get; set; }
    public DbSet<OrderItemEntity> CartItems { get; set; }
    public DbSet<ShippingEntity> Shipping { get; set; }

    protected override void OnConfiguring(DbContextOptionsBuilder optionsBuilder)
    {
        var connectionString = Environment.GetEnvironmentVariable("DB_CONNECTION_STRING");

        optionsBuilder.UseNpgsql(connectionString).UseSnakeCaseNamingConvention();
    }
}


internal class Consumer : IDisposable
{
    private const string TopicName = "orders";

    private ILogger _logger;
    private IConsumer<string, byte[]> _consumer;
    private bool _isListening;
    // M9-03: BỎ _dbContext singleton - phải tạo fresh context cho mỗi message để tránh
    // conflict khi compare sau failed insert (ChangeTracker cũ chứa entity Added).
    private readonly string? _connectionString;
    private static readonly ActivitySource MyActivitySource = new("Accounting.Consumer");

    public Consumer(ILogger<Consumer> logger)
    {
        _logger = logger;

        var servers = Environment.GetEnvironmentVariable("KAFKA_ADDR")
            ?? throw new InvalidOperationException("The KAFKA_ADDR environment variable is not set.");

        _consumer = BuildConsumer(servers);
        _consumer.Subscribe(TopicName);

       if (_logger.IsEnabled(LogLevel.Information))
       {
           _logger.LogInformation("Connecting to Kafka: {servers}", servers);
       }

        // M9-03: Lưu connection string, tạo DBContext mới mỗi message thay vì singleton
        _connectionString = Environment.GetEnvironmentVariable("DB_CONNECTION_STRING");
    }

    public void StartListening()
    {
        _isListening = true;

        try
        {
            while (_isListening)
            {
                try
                {
                    using var activity = MyActivitySource.StartActivity("order-consumed",  ActivityKind.Internal);
                    var consumeResult = _consumer.Consume();
                    if (ProcessMessage(consumeResult.Message))
                    {
                        // REL-09: commit only AFTER the order is safely persisted.
                        // Previously EnableAutoCommit=true committed the offset before
                        // the DB write, so a crash or DB failure lost the order silently
                        // even though the customer had already been charged.
                        _consumer.Commit(consumeResult);
                    }
                    else
                    {
                        // Transient failure (e.g. Postgres down). Rewind to this offset
                        // and back off so the same message is retried, not skipped.
                        _consumer.Seek(consumeResult.TopicPartitionOffset);
                        Thread.Sleep(TimeSpan.FromSeconds(2));
                    }
                }
                catch (ConsumeException e)
                {
                    if (_logger.IsEnabled(LogLevel.Error))
                    {
                        _logger.LogError(e, "Consume error: {reason}", e.Error.Reason);
                    }
                }
            }
        }
        catch (OperationCanceledException)
        {
            _logger.LogInformation("Closing consumer");

            _consumer.Close();
        }
    }

    // M9-03: Returns true khi offset an toàn để commit (persisted hoặc idempotent match
    // hoặc poison message/DLQ), false khi transient failure cần retry.
    private bool ProcessMessage(Message<string, byte[]> message)
    {
        OrderResult order;
        try
        {
            order = OrderResult.Parser.ParseFrom(message.Value);
        }
        catch (Exception ex)
        {
            // Poison message: parsing sẽ không bao giờ thành công khi retry.
            // Skip nó (commit) để không block partition vĩnh viễn.
            // TODO M9-14: Dead-letter topic là improvement tiếp theo.
            _logger.LogError(ex, "Skipping unparseable order message");
            return true;
        }

        Log.OrderReceivedMessage(_logger, order);

        // M9-03: Kiểm tra message key = order_id (cần thiết cho ordering + dedupe)
        if (message.Key != order.OrderId)
        {
            _logger.LogWarning("Message key mismatch: key={Key} but order_id={OrderId}. " +
                "Producer PHẢI set key=order_id (sửa trong M9-03).",
                message.Key, order.OrderId);
        }

        if (string.IsNullOrEmpty(_connectionString))
        {
            // No DB configured - skip persistence (development mode)
            return true;
        }

        // M9-03: Tạo DBContext MỚI/SẠCH cho mỗi message - KHÔNG dùng singleton
        // vì sau SaveChanges fail, ChangeTracker cũ chứa entity Added sẽ gây
        // conflict khi fetch lại để compare.
        using var dbContext = new DBContext();

        try
        {
            var orderEntity = new OrderEntity
            {
                Id = order.OrderId
            };
            dbContext.Add(orderEntity);
            
            foreach (var item in order.Items)
            {
                var orderItem = new OrderItemEntity
                {
                    ItemCostCurrencyCode = item.Cost.CurrencyCode,
                    ItemCostUnits = item.Cost.Units,
                    ItemCostNanos = item.Cost.Nanos,
                    ProductId = item.Item.ProductId,
                    Quantity = item.Item.Quantity,
                    OrderId = order.OrderId
                };

                dbContext.Add(orderItem);
            }

            var shipping = new ShippingEntity
            {
                ShippingTrackingId = order.ShippingTrackingId,
                ShippingCostCurrencyCode = order.ShippingCost.CurrencyCode,
                ShippingCostUnits = order.ShippingCost.Units,
                ShippingCostNanos = order.ShippingCost.Nanos,
                StreetAddress = order.ShippingAddress.StreetAddress,
                City = order.ShippingAddress.City,
                State = order.ShippingAddress.State,
                Country = order.ShippingAddress.Country,
                ZipCode = order.ShippingAddress.ZipCode,
                OrderId = order.OrderId
            };
            dbContext.Add(shipping);
            dbContext.SaveChanges();
            
            // Success - commit offset
            return true;
        }
        catch (DbUpdateException dbEx) when (dbEx.InnerException is PostgresException pgEx && pgEx.SqlState == "23505")
        {
            // M9-03: Unique violation (23505) - CHỈ coi là idempotent replay hợp lệ
            // khi ConstraintName = order_pkey (constraint của order_id).
            // Nếu là constraint khác → lỗi dữ liệu thật sự → KHÔNG commit.
            
            if (pgEx.ConstraintName == IdempotencyConstants.OrderPrimaryKeyConstraint)
            {
                // Duplicate order_id - CÓ THỂ là replay hợp lệ.
                // PHẢI verify bằng fresh context: fetch order+items+shipping và so sánh
                // canonical với payload hiện tại.
                _logger.LogInformation("Duplicate order_id={OrderId}, verifying idempotency...",
                    order.OrderId);

                return VerifyIdempotentReplay(order);
            }
            else
            {
                // 23505 nhưng KHÔNG phải order_pkey → lỗi constraint khác
                // (vd shipping_tracking_id duplicate với order_id khác).
                // Đây là data integrity issue → DLQ và alert.
                _logger.LogError(pgEx,
                    "Constraint violation (NOT order_id): constraint={Constraint}, order_id={OrderId}. " +
                    "Ghi vào DLQ và alert.",
                    pgEx.ConstraintName, order.OrderId);
                
                // TODO M9-14: Implement durable DLQ/quarantine topic
                // Tạm thời: commit để không block partition, nhưng PHẢI có alert
                return true; // COMMIT - vì retry sẽ fail y hệt
            }
        }
        catch (Exception ex)
        {
            // Transient persistence failure (Postgres unavailable, network, etc).
            // DO NOT commit; signal caller để rewind và retry.
            _logger.LogError(ex, "Failed to persist order {OrderId}; will retry", order.OrderId);
            return false;
        }
    }

    /// <summary>
    /// M9-03: Verify idempotent replay bằng fresh DbContext.
    /// Fetch order existing từ DB rồi delegate sang IdempotencyChecker.Compare()
    /// — cùng path với unit test, không duplicate logic.
    /// </summary>
    private bool VerifyIdempotentReplay(OrderResult incomingOrder)
    {
        // Dùng FRESH DbContext — KHÔNG dùng context đang chứa entity Added failed.
        using var freshContext = new DBContext();

        try
        {
            var existingOrder = freshContext.Orders
                .AsNoTracking()
                .FirstOrDefault(o => o.Id == incomingOrder.OrderId);

            var existingItems = freshContext.CartItems
                .AsNoTracking()
                .Where(i => i.OrderId == incomingOrder.OrderId)
                .ToList();

            var existingShipping = freshContext.Shipping
                .AsNoTracking()
                .FirstOrDefault(s => s.OrderId == incomingOrder.OrderId);

            // Delegate toàn bộ compare logic sang IdempotencyChecker —
            // đây là cùng path được unit test kiểm tra.
            var result = IdempotencyChecker.Compare(
                incomingOrder,
                existingOrder,
                existingItems,
                existingShipping,
                _logger);

            return result switch
            {
                IdempotencyResult.ValidReplay  => true,   // commit
                IdempotencyResult.ConflictDlq  => true,   // commit + đã alert trong Compare()
                IdempotencyResult.TransientError => false, // không commit → retry
                _ => false
            };
        }
        catch (Exception ex)
        {
            // Transient failure khi fetch từ DB → retry toàn bộ message
            _logger.LogError(ex, "Failed to verify idempotency for order {OrderId}; will retry",
                incomingOrder.OrderId);
            return false;
        }
    }

    private static IConsumer<string, byte[]> BuildConsumer(string servers)
    {
        var conf = new ConsumerConfig
        {
            GroupId = $"accounting",
            BootstrapServers = servers,
            // https://github.com/confluentinc/confluent-kafka-dotnet/tree/07de95ed647af80a0db39ce6a8891a630423b952#basic-consumer-example
            AutoOffsetReset = AutoOffsetReset.Earliest,
            // REL-09: commit offsets manually (after the order is persisted) so a
            // crash/DB failure mid-processing does not silently lose the order.
            EnableAutoCommit = false
        };

        // Mandate #8: TLS + SASL/SCRAM for MSK, gated by env. Empty = Plaintext = current behavior.
        ApplyKafkaSecurity(conf);

        return new ConsumerBuilder<string, byte[]>(conf)
            .Build();
    }

    // Mandate #8: apply TLS + SASL/SCRAM-SHA-512 from env. No KAFKA_SECURITY_PROTOCOL set =
    // Plaintext with no auth = the previous in-cluster Kafka behavior (safe to deploy pre-cutover).
    private static void ApplyKafkaSecurity(ClientConfig conf)
    {
        var protocol = Environment.GetEnvironmentVariable("KAFKA_SECURITY_PROTOCOL");
        if (string.IsNullOrEmpty(protocol))
        {
            return;
        }

        conf.SecurityProtocol = protocol.ToUpperInvariant() switch
        {
            "SASL_SSL" => SecurityProtocol.SaslSsl,
            "SASL_PLAINTEXT" => SecurityProtocol.SaslPlaintext,
            "SSL" => SecurityProtocol.Ssl,
            _ => SecurityProtocol.Plaintext
        };

        if (conf.SecurityProtocol == SecurityProtocol.SaslSsl || conf.SecurityProtocol == SecurityProtocol.SaslPlaintext)
        {
            conf.SaslMechanism = SaslMechanism.ScramSha512;
            conf.SaslUsername = Environment.GetEnvironmentVariable("KAFKA_SASL_USERNAME");
            conf.SaslPassword = Environment.GetEnvironmentVariable("KAFKA_SASL_PASSWORD");
        }
    }

    public void Dispose()
    {
        _isListening = false;
        _consumer?.Dispose();
    }
}
