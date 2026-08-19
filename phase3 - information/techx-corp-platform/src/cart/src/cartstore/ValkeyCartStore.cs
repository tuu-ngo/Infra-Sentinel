// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
using System;
using System.Linq;
using System.Threading.Tasks;
using Grpc.Core;
using StackExchange.Redis;
using Google.Protobuf;
using Microsoft.Extensions.Logging;
using System.Diagnostics.Metrics;
using System.Diagnostics;

namespace cart.cartstore;

public class ValkeyCartStore : ICartStore
{
    private readonly ILogger _logger;
    private const string CartFieldName = "cart";
    private const int RedisRetryNumber = 30;

    private volatile ConnectionMultiplexer _redis;
    private volatile bool _isRedisConnectionOpened;

    private readonly object _locker = new();
    private readonly byte[] _emptyCartBytes;
    private readonly string _connectionString;

    private static readonly ActivitySource CartActivitySource = new("OpenTelemetry.Demo.Cart");
    private static readonly Meter CartMeter = new Meter("OpenTelemetry.Demo.Cart");
    private static readonly Histogram<double> addItemHistogram = CartMeter.CreateHistogram(
        "app.cart.add_item.latency",
        unit: "s",
        advice: new InstrumentAdvice<double>
        {
            HistogramBucketBoundaries = [ 0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10 ]
        });
    private static readonly Histogram<double> getCartHistogram = CartMeter.CreateHistogram(
        "app.cart.get_cart.latency",
        unit: "s",
        advice: new InstrumentAdvice<double>
        {
            HistogramBucketBoundaries = [ 0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10 ]
        });
    // Mandate #8: dual-write observability. Operator watches errors -> 0 before flipping reads.
    private static readonly Counter<long> dualWriteTotalCounter = CartMeter.CreateCounter<long>(
        "app.cart.dual_write.total");
    private static readonly Counter<long> dualWriteErrorCounter = CartMeter.CreateCounter<long>(
        "app.cart.dual_write.errors");
    private readonly ConfigurationOptions _redisConnectionOptions;

    // Mandate #8: temporary dual-write to a second store (ElastiCache during cutover). Empty = off.
    private readonly bool _dualWriteEnabled;
    private readonly string _dualWriteAddress;
    private readonly ConfigurationOptions _dualWriteConnectionOptions;
    private volatile ConnectionMultiplexer _dualWriteRedis;
    private volatile bool _isDualWriteConnectionOpened;
    private readonly object _dualWriteLocker = new();

    public ValkeyCartStore(ILogger<ValkeyCartStore> logger, string valkeyAddress)
    {
        _logger = logger;
        // Serialize empty cart into byte array.
        var cart = new Oteldemo.Cart();
        _emptyCartBytes = cart.ToByteArray();

        // Mandate #8: TLS + AUTH token from env. Defaults (off / empty) reproduce the previous
        // behavior exactly (ssl=false, no password) so deploying this change is a no-op until cutover.
        bool useTls = string.Equals(Environment.GetEnvironmentVariable("VALKEY_TLS"), "true", StringComparison.OrdinalIgnoreCase);
        string authToken = Environment.GetEnvironmentVariable("VALKEY_AUTH_TOKEN") ?? string.Empty;

        // Connection string kept only for the debug log below - never includes the password.
        _connectionString = $"{valkeyAddress},ssl={(useTls ? "true" : "false")},allowAdmin=true,abortConnect=false";
        _redisConnectionOptions = BuildConnectionOptions(valkeyAddress, useTls, authToken, RedisRetryNumber);

        // Mandate #8: temporary dual-write to a second store during cutover. Empty = disabled.
        // Target has its own TLS/auth (phase 1: ElastiCache with TLS; phase 2: old valkey plaintext).
        _dualWriteAddress = Environment.GetEnvironmentVariable("VALKEY_DUAL_WRITE_ADDR") ?? string.Empty;
        _dualWriteEnabled = !string.IsNullOrEmpty(_dualWriteAddress);
        if (_dualWriteEnabled)
        {
            bool dwTls = string.Equals(Environment.GetEnvironmentVariable("VALKEY_DUAL_WRITE_TLS"), "true", StringComparison.OrdinalIgnoreCase);
            string dwToken = Environment.GetEnvironmentVariable("VALKEY_DUAL_WRITE_AUTH_TOKEN") ?? string.Empty;
            // Fail fast (ConnectRetry=1) so a slow/down secondary never inflates customer latency.
            _dualWriteConnectionOptions = BuildConnectionOptions(_dualWriteAddress, dwTls, dwToken, 1);
            _dualWriteConnectionOptions.ConnectTimeout = 2000;
            _dualWriteConnectionOptions.AsyncTimeout = 1000;
        }
    }

    // Mandate #8: build StackExchange.Redis options with optional TLS + AUTH token.
    // Retry policy giữ nguyên; KeepAlive hạ 180->5s cho AZ failover (REL-17-07, xem dưới).
    // Defaults keep ssl off and no password.
    private static ConfigurationOptions BuildConnectionOptions(string address, bool useTls, string authToken, int connectRetry)
    {
        var options = ConfigurationOptions.Parse($"{address},allowAdmin=true,abortConnect=false");
        options.Ssl = useTls;
        if (!string.IsNullOrEmpty(authToken))
        {
            options.Password = authToken;
        }
        options.ConnectRetry = connectRetry;
        options.ReconnectRetryPolicy = new ExponentialRetry(1000);
        // REL-17-07 (Mandate 17/21 AZ failover): 180 -> 5s. KeepAlive là chu kỳ ping để
        // StackExchange.Redis phát hiện kết nối chết. Khi ElastiCache failover, node cũ
        // tụt xuống replica nhưng TCP cũ vẫn mở; với 180s client mất tới ~3 phút mới nhận
        // ra -> cart 500 suốt 70s+ (đo drill M17 30/07 + test-failover). 5s rút thời gian
        // gãy về xấp xỉ cửa sổ failover thật của ElastiCache (~30s). Ping mỗi 5s rẻ.
        options.KeepAlive = 5;
        return options;
    }

    public ConnectionMultiplexer GetConnection()
    {
        EnsureRedisConnected();
        return _redis;
    }

    public void Initialize()
    {
        EnsureRedisConnected();
    }

    private void EnsureRedisConnected()
    {
        if (_isRedisConnectionOpened)
        {
            return;
        }

        // Connection is closed or failed - open a new one but only at the first thread
        lock (_locker)
        {
            if (_isRedisConnectionOpened)
            {
                return;
            }

            if (_logger.IsEnabled(LogLevel.Debug))
            {
                _logger.LogDebug("Connecting to Redis: {connectionString}", _connectionString);
            }

            _redis = ConnectionMultiplexer.Connect(_redisConnectionOptions);

            if (_redis == null || !_redis.IsConnected)
            {
                _logger.LogError("Wasn't able to connect to redis");

                // We weren't able to connect to Redis despite some retries with exponential backoff.
                throw new ApplicationException("Wasn't able to connect to redis");
            }

            _logger.LogInformation("Successfully connected to Redis");
            var cache = _redis.GetDatabase();

            _logger.LogDebug("Performing small test");
            cache.StringSet("cart", "OK" );
            object res = cache.StringGet("cart");

            if (_logger.IsEnabled(LogLevel.Debug))
            {
                _logger.LogDebug("Small test result: {result}", res);
            }

            _redis.InternalError += (_, e) => { Console.WriteLine(e.Exception); };
            _redis.ConnectionRestored += (_, _) =>
            {
                _isRedisConnectionOpened = true;
                _logger.LogInformation("Connection to redis was restored successfully.");
            };
            _redis.ConnectionFailed += (_, _) =>
            {
                _logger.LogInformation("Connection failed. Disposing the object");
                _isRedisConnectionOpened = false;
            };

            _isRedisConnectionOpened = true;
        }
    }

    // Mandate #8: mirror a write to the dual-write target (best-effort, bounded latency).
    // Never throws - a failure here must not break the customer path. Errors are logged and
    // counted so the operator can confirm convergence (errors -> 0) before flipping reads.
    private async Task DualWriteAsync(string userId, HashEntry[] entries)
    {
        if (!_dualWriteEnabled)
        {
            return;
        }

        try
        {
            if (!_isDualWriteConnectionOpened)
            {
                lock (_dualWriteLocker)
                {
                    if (!_isDualWriteConnectionOpened)
                    {
                        _dualWriteRedis = ConnectionMultiplexer.Connect(_dualWriteConnectionOptions);
                        _isDualWriteConnectionOpened = _dualWriteRedis != null && _dualWriteRedis.IsConnected;
                    }
                }
            }

            var db = _dualWriteRedis.GetDatabase();
            await db.HashSetAsync(userId, entries);
            // Same 60-minute TTL as the primary so the convergence-window proof holds on both stores.
            await db.KeyExpireAsync(userId, TimeSpan.FromMinutes(60));
            dualWriteTotalCounter.Add(1);
        }
        catch (Exception ex)
        {
            _isDualWriteConnectionOpened = false;
            dualWriteErrorCounter.Add(1);
            _logger.LogError(ex, "Dual-write to {address} failed for user {userId}", _dualWriteAddress, userId);
        }
    }

    public async Task AddItemAsync(string userId, string productId, int quantity)
    {
        var stopwatch = Stopwatch.StartNew();

        if (_logger.IsEnabled(LogLevel.Information))
        {
            _logger.LogInformation("AddItemAsync called with userId={userId}, productId={productId}, quantity={quantity}", userId, productId, quantity);
        }

        try
        {
            EnsureRedisConnected();

            var db = _redis.GetDatabase();

            // Access the cart from the cache
            var value = await db.HashGetAsync(userId, CartFieldName);

            Oteldemo.Cart cart;
            if (value.IsNull)
            {
                cart = new Oteldemo.Cart
                {
                    UserId = userId
                };
                cart.Items.Add(new Oteldemo.CartItem { ProductId = productId, Quantity = quantity });
            }
            else
            {
                cart = Oteldemo.Cart.Parser.ParseFrom(value);
                var existingItem = cart.Items.SingleOrDefault(i => i.ProductId == productId);
                if (existingItem == null)
                {
                    cart.Items.Add(new Oteldemo.CartItem { ProductId = productId, Quantity = quantity });
                }
                else
                {
                    existingItem.Quantity += quantity;
                }
            }

            var cartEntries = new[]{ new HashEntry(CartFieldName, cart.ToByteArray()) };
            await db.HashSetAsync(userId, cartEntries);
            await db.KeyExpireAsync(userId, TimeSpan.FromMinutes(60));

            // Mandate #8: mirror to the dual-write target after the primary write succeeds.
            await DualWriteAsync(userId, cartEntries);
        }
        catch (Exception ex)
        {
            throw new RpcException(new Status(StatusCode.FailedPrecondition, $"Can't access cart storage. {ex}"));
        }
        finally
        {
            addItemHistogram.Record(stopwatch.Elapsed.TotalSeconds);
        }
    }

    public async Task EmptyCartAsync(string userId)
    {
        if (_logger.IsEnabled(LogLevel.Information))
        {
            _logger.LogInformation("EmptyCartAsync called with userId={userId}", userId);
        }
        try
        {
            EnsureRedisConnected();
            var db = _redis.GetDatabase();

            // Update the cache with empty cart for given user
            var emptyEntries = new[] { new HashEntry(CartFieldName, _emptyCartBytes) };
            await db.HashSetAsync(userId, emptyEntries);
            await db.KeyExpireAsync(userId, TimeSpan.FromMinutes(60));

            // Mandate #8: mirror the empty-cart write to the dual-write target.
            await DualWriteAsync(userId, emptyEntries);
        }
        catch (Exception ex)
        {
            throw new RpcException(new Status(StatusCode.FailedPrecondition, $"Can't access cart storage. {ex}"));
        }
    }

    public async Task<Oteldemo.Cart> GetCartAsync(string userId)
    {
        var stopwatch = Stopwatch.StartNew();

        if (_logger.IsEnabled(LogLevel.Information))
        {
            _logger.LogInformation("GetCartAsync called with userId={userId}", userId);
        }

        try
        {
            EnsureRedisConnected();

            var db = _redis.GetDatabase();

            // Access the cart from the cache
            var value = await db.HashGetAsync(userId, CartFieldName);

            if (!value.IsNull)
            {
                return Oteldemo.Cart.Parser.ParseFrom(value);
            }

            // We decided to return empty cart in cases when user wasn't in the cache before
            return new Oteldemo.Cart();
        }
        catch (Exception ex)
        {
            throw new RpcException(new Status(StatusCode.FailedPrecondition, $"Can't access cart storage. {ex}"));
        }
        finally
        {
            getCartHistogram.Record(stopwatch.Elapsed.TotalSeconds);
        }
    }

    public bool Ping()
    {
        try
        {
            var cache = _redis.GetDatabase();
            var res = cache.Ping();
            return res != TimeSpan.Zero;
        }
        catch (Exception)
        {
            return false;
        }
    }
}
