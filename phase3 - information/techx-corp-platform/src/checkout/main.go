// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
// rebuild-sync (retry - fixed undefined `cs` -> `svc` compile error below): touch to build alongside frontend-proxy/accounting/cart/product-catalog/product-reviews/recommendation under one CI tag
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/log/global"
	semconv "go.opentelemetry.io/otel/semconv/v1.24.0"
	"go.opentelemetry.io/otel/trace"

	"github.com/IBM/sarama"
	"github.com/google/uuid"
	otelhooks "github.com/open-feature/go-sdk-contrib/hooks/open-telemetry/pkg"
	flagd "github.com/open-feature/go-sdk-contrib/providers/flagd/pkg"
	"github.com/open-feature/go-sdk/openfeature"

	"go.opentelemetry.io/contrib/bridges/otelslog"
	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/contrib/instrumentation/runtime"
	"go.opentelemetry.io/otel"
	otelcodes "go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploggrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"

	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdkresource "go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"

	pb "github.com/open-telemetry/techx-corp/src/checkout/genproto/oteldemo"
	"github.com/open-telemetry/techx-corp/src/checkout/kafka"
	"github.com/open-telemetry/techx-corp/src/checkout/money"
)

//go:generate go install google.golang.org/protobuf/cmd/protoc-gen-go
//go:generate go install google.golang.org/grpc/cmd/protoc-gen-go-grpc
//go:generate protoc --go_out=./ --go-grpc_out=./ --proto_path=../../pb ../../pb/demo.proto

var logger *slog.Logger

// stderrLog viết thẳng ra STDERR (kubectl logs). logger chính (otelslog) đẩy log
// qua OTel Collector -> OpenSearch, KHÔNG hiện trong `kubectl logs` và phụ thuộc
// telemetry pipeline khoẻ. Trong sự cố cutover MSK (postmortem 0010) đúng lúc cần
// đọc lỗi sarama thì không thấy gì. stderrLog để lỗi bootstrap/produce Kafka luôn
// đọc được trực tiếp từ pod, không lệ thuộc pipeline.
var stderrLog *slog.Logger
var tracer trace.Tracer
var resource *sdkresource.Resource
var initResourcesOnce sync.Once

func initResource() *sdkresource.Resource {
	initResourcesOnce.Do(func() {
		extraResources, _ := sdkresource.New(
			context.Background(),
			sdkresource.WithOS(),
			sdkresource.WithProcess(),
			sdkresource.WithContainer(),
			sdkresource.WithHost(),
		)
		resource, _ = sdkresource.Merge(
			sdkresource.Default(),
			extraResources,
		)
	})
	return resource
}

func initTracerProvider() *sdktrace.TracerProvider {
	ctx := context.Background()

	exporter, err := otlptracegrpc.New(ctx)
	if err != nil {
		logger.Error(fmt.Sprintf("new otlp trace grpc exporter failed: %v", err))
	}
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(initResource()),
	)
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(propagation.TraceContext{}, propagation.Baggage{}))
	return tp
}

func initMeterProvider() *sdkmetric.MeterProvider {
	ctx := context.Background()

	exporter, err := otlpmetricgrpc.New(ctx)
	if err != nil {
		logger.Error(fmt.Sprintf("new otlp metric grpc exporter failed: %v", err))
	}

	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(exporter)),
		sdkmetric.WithResource(initResource()),
	)
	otel.SetMeterProvider(mp)
	return mp
}

func initLoggerProvider() *sdklog.LoggerProvider {
	ctx := context.Background()

	logExporter, err := otlploggrpc.New(ctx)
	if err != nil {
		return nil
	}

	loggerProvider := sdklog.NewLoggerProvider(
		sdklog.WithProcessor(sdklog.NewBatchProcessor(logExporter)),
	)
	global.SetLoggerProvider(loggerProvider)

	return loggerProvider
}

type checkout struct {
	productCatalogSvcAddr string
	cartSvcAddr           string
	currencySvcAddr       string
	shippingSvcAddr       string
	emailSvcAddr          string
	paymentSvcAddr        string
	kafkaBrokerSvcAddr    string
	pb.UnimplementedCheckoutServiceServer
	KafkaProducerClient     sarama.SyncProducer
	shippingSvcClient       pb.ShippingServiceClient
	productCatalogSvcClient pb.ProductCatalogServiceClient
	cartSvcClient           pb.CartServiceClient
	currencySvcClient       pb.CurrencyServiceClient
	emailSvcClient          pb.EmailServiceClient
	paymentSvcClient        pb.PaymentServiceClient
}

func (cs *checkout) dependencyHealthStatus(ctx context.Context) healthpb.HealthCheckResponse_ServingStatus {
	checkCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()

	deps := []func(context.Context) error{
		func(ctx context.Context) error {
			_, err := cs.cartSvcClient.GetCart(ctx, &pb.GetCartRequest{UserId: "healthcheck"})
			return err
		},
		func(ctx context.Context) error {
			_, err := cs.currencySvcClient.GetSupportedCurrencies(ctx, &pb.Empty{})
			return err
		},
		func(ctx context.Context) error {
			_, err := cs.productCatalogSvcClient.ListProducts(ctx, &pb.Empty{})
			return err
		},
	}

	for _, dep := range deps {
		if err := dep(checkCtx); err != nil {
			logger.Warn(fmt.Sprintf("health: dependency check failed: %v", err))
			return healthpb.HealthCheckResponse_NOT_SERVING
		}
	}

	return healthpb.HealthCheckResponse_SERVING
}

func main() {
	var port string
	mustMapEnv(&port, "CHECKOUT_PORT")

	tp := initTracerProvider()
	defer func() {
		if err := tp.Shutdown(context.Background()); err != nil {
			logger.Error(fmt.Sprintf("Error shutting down tracer provider: %v", err))
		}
	}()

	mp := initMeterProvider()
	defer func() {
		if err := mp.Shutdown(context.Background()); err != nil {
			logger.Error(fmt.Sprintf("Error shutting down meter provider: %v", err))
		}
	}()

	lp := initLoggerProvider()
	defer func() {
		if err := lp.Shutdown(context.Background()); err != nil {
			logger.Error(fmt.Sprintf("Error shutting down logger provider: %v", err))
		}
	}()

	// this *must* be called after the logger provider is initialized
	// otherwise the Sarama producer in kafka/producer.go will not be
	// able to log properly
	logger = otelslog.NewLogger("checkout")
	slog.SetDefault(logger)

	// Logger STDERR song song để lỗi Kafka/MSK đọc được qua `kubectl logs` ngay cả
	// khi telemetry pipeline (OTel Collector/OpenSearch) không sẵn sàng.
	stderrLog = slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo}))

	err := runtime.Start(runtime.WithMinimumReadMemStatsInterval(time.Second))
	if err != nil {
		logger.Error((err.Error()))
	}

	provider, err := flagd.NewProvider()
	if err != nil {
		logger.Error(fmt.Sprintf("Error creating flagd provider: %v", err))
	}

	openfeature.SetProvider(provider)
	openfeature.AddHooks(otelhooks.NewTracesHook())

	tracer = tp.Tracer("checkout")

	svc := new(checkout)

	mustMapEnv(&svc.shippingSvcAddr, "SHIPPING_ADDR")
	c := mustCreateClient(svc.shippingSvcAddr)
	svc.shippingSvcClient = pb.NewShippingServiceClient(c)
	defer c.Close()

	mustMapEnv(&svc.productCatalogSvcAddr, "PRODUCT_CATALOG_ADDR")
	c = mustCreateClient(svc.productCatalogSvcAddr)
	svc.productCatalogSvcClient = pb.NewProductCatalogServiceClient(c)
	defer c.Close()

	mustMapEnv(&svc.cartSvcAddr, "CART_ADDR")
	c = mustCreateClient(svc.cartSvcAddr)
	svc.cartSvcClient = pb.NewCartServiceClient(c)
	defer c.Close()

	mustMapEnv(&svc.currencySvcAddr, "CURRENCY_ADDR")
	c = mustCreateClient(svc.currencySvcAddr)
	svc.currencySvcClient = pb.NewCurrencyServiceClient(c)
	defer c.Close()

	mustMapEnv(&svc.emailSvcAddr, "EMAIL_ADDR")
	c = mustCreateClient(svc.emailSvcAddr)
	svc.emailSvcClient = pb.NewEmailServiceClient(c)
	defer c.Close()

	mustMapEnv(&svc.paymentSvcAddr, "PAYMENT_ADDR")
	c = mustCreateClient(svc.paymentSvcAddr)
	svc.paymentSvcClient = pb.NewPaymentServiceClient(c)
	defer c.Close()

	svc.kafkaBrokerSvcAddr = os.Getenv("KAFKA_ADDR")

	if svc.kafkaBrokerSvcAddr != "" {
		// Mandate #8: cấu hình TLS + SASL/SCRAM cho MSK, đọc từ env. Mặc định rỗng =
		// PLAINTEXT = hành vi cũ với Kafka in-cluster. Cutover chỉ cần đổi env, không rebuild.
		secCfg := kafka.SecurityConfig{
			Protocol: os.Getenv("KAFKA_SECURITY_PROTOCOL"),
			Username: os.Getenv("KAFKA_SASL_USERNAME"),
			Password: os.Getenv("KAFKA_SASL_PASSWORD"),
		}
		// NGUYÊN NHÂN GỐC sự cố 0010: KAFKA_ADDR có thể chứa NHIỀU broker phân tách bằng
		// dấu phẩy (MSK trả 3 bootstrap broker). Phải tách thành từng phần tử. Trước đây
		// nhét cả chuỗi CSV vào một phần tử ([]string{addr}) -> sarama net.Dial nguyên
		// chuỗi "b-1:9096,b-2:9096,b-3:9096" -> lỗi "too many colons in address",
		// không bao giờ tới bước TLS/SASL. Kafka in-cluster cũ chỉ có 1 broker nên bug
		// này bị ẩn hoàn toàn cho tới khi lên MSK.
		brokers := make([]string, 0, 3)
		for _, b := range strings.Split(svc.kafkaBrokerSvcAddr, ",") {
			if b = strings.TrimSpace(b); b != "" {
				brokers = append(brokers, b)
			}
		}
		// Truyền stderrLog để chẩn đoán kết nối của sarama (metadata/SASL/TLS) rơi vào
		// `kubectl logs`, không chỉ OTel. Đây chính là log đã biến mất trong sự cố 0010.
		svc.KafkaProducerClient, err = kafka.CreateKafkaProducer(brokers, stderrLog, secCfg)
		if err != nil {
			// FAIL FAST. checkout không được nhận đơn nếu không phát được order event
			// (REL-09: order là dữ liệu tài chính, không được charge mà mất bản ghi).
			// Trước đây lỗi này bị nuốt -> producer nil -> PlaceOrder panic khi có
			// traffic thật -> outage (postmortem 0010). Thoát ngay để pod KHÔNG BAO GIỜ
			// Ready: Argo Rollouts dừng canary thay vì promote pod sẽ panic. Config sai =
			// rollout đứng an toàn, không phải sự cố khách hàng.
			stderrLog.Error(fmt.Sprintf("FATAL: khong tao duoc Kafka producer cho %q (protocol=%q): %v",
				svc.kafkaBrokerSvcAddr, secCfg.Protocol, err))
			logger.Error(fmt.Sprintf("FATAL: khong tao duoc Kafka producer: %v", err))
			os.Exit(1)
		}
	}

	logger.Info(fmt.Sprintf("service config: %+v", svc))

	lis, err := net.Listen("tcp", fmt.Sprintf(":%s", port))
	if err != nil {
		logger.Error(err.Error())
	}

	var srv = grpc.NewServer(
		grpc.StatsHandler(otelgrpc.NewServerHandler()),
	)
	pb.RegisterCheckoutServiceServer(srv, svc)

	healthcheck := health.NewServer()
	healthpb.RegisterHealthServer(srv, healthcheck)
	logger.Info(fmt.Sprintf("starting to listen on tcp: %q", lis.Addr().String()))

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM, syscall.SIGKILL)
	defer cancel()

	// REL-02: stop reporting a static SERVING status. checkout depends on
	// cart/currency/product-catalog to even start building an order, so make the
	// gRPC health endpoint reflect those real upstreams before REL-03 wires
	// readiness probes to it.
	go func() {
		ticker := time.NewTicker(5 * time.Second)
		defer ticker.Stop()
		for {
			healthcheck.SetServingStatus("", svc.dependencyHealthStatus(ctx))
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
			}
		}
	}()

	go func() {
		if err := srv.Serve(lis); err != nil {
			logger.Error(err.Error())
		}
	}()

	<-ctx.Done()

	srv.GracefulStop()
	logger.Info("Checkout gRPC server stopped")
}

func mustMapEnv(target *string, envKey string) {
	v := os.Getenv(envKey)
	if v == "" {
		panic(fmt.Sprintf("environment variable %q not set", envKey))
	}
	*target = v
}

func (cs *checkout) Check(ctx context.Context, req *healthpb.HealthCheckRequest) (*healthpb.HealthCheckResponse, error) {
	return &healthpb.HealthCheckResponse{Status: cs.dependencyHealthStatus(ctx)}, nil
}

func (cs *checkout) Watch(req *healthpb.HealthCheckRequest, ws healthpb.Health_WatchServer) error {
	return status.Errorf(codes.Unimplemented, "health check via Watch not implemented")
}

func (cs *checkout) PlaceOrder(ctx context.Context, req *pb.PlaceOrderRequest) (*pb.PlaceOrderResponse, error) {
	span := trace.SpanFromContext(ctx)
	span.SetAttributes(
		attribute.String("app.user.id", req.UserId),
		attribute.String("app.user.currency", req.UserCurrency),
	)
	logger.LogAttrs(
		ctx,
		slog.LevelInfo, "[PlaceOrder]",
		slog.String("user_id", req.UserId),
		slog.String("user_currency", req.UserCurrency),
	)

	var err error
	defer func() {
		if err != nil {
			span.AddEvent("error", trace.WithAttributes(semconv.ExceptionMessageKey.String(err.Error())))
		}
	}()

	orderID, err := uuid.NewUUID()
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to generate order uuid")
	}

	prep, err := cs.prepareOrderItemsAndShippingQuoteFromCart(ctx, req.UserId, req.UserCurrency, req.Address)
	if err != nil {
		return nil, status.Error(codes.Internal, err.Error())
	}
	span.AddEvent("prepared")

	total := &pb.Money{CurrencyCode: req.UserCurrency,
		Units: 0,
		Nanos: 0}
	total = money.Must(money.Sum(total, prep.shippingCostLocalized))
	for _, it := range prep.orderItems {
		multPrice := money.MultiplySlow(it.Cost, uint32(it.GetItem().GetQuantity()))
		total = money.Must(money.Sum(total, multPrice))
	}

	// REL-04: ship BEFORE charging. The payment service exposes no Refund/Void
	// RPC, so once a card is charged there is no way to compensate a later
	// failure - the previous charge-then-ship order left customers "charged but
	// not shipped" when shipOrder failed. Shipping here only allocates a tracking
	// id (mock fulfilment, no real cost), so doing it first means a shipping
	// failure aborts the order with the card untouched, and a later charge failure
	// leaves only a harmless unused tracking id.
	shippingTrackingID, err := cs.shipOrder(ctx, req.Address, prep.cartItems)
	if err != nil {
		return nil, status.Errorf(codes.Unavailable, "shipping error: %+v", err)
	}

	txID, err := cs.chargeCard(ctx, total, req.CreditCard)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to charge card: %+v", err)
	}

	span.AddEvent("charged",
		trace.WithAttributes(attribute.String("app.payment.transaction.id", txID)))
	logger.LogAttrs(
		ctx,
		slog.LevelInfo, "payment went through",
		slog.String("transaction_id", txID),
	)
	shippingTrackingAttribute := attribute.String("app.shipping.tracking.id", shippingTrackingID)
	span.AddEvent("shipped", trace.WithAttributes(shippingTrackingAttribute))

	_ = cs.emptyUserCart(ctx, req.UserId)

	orderResult := &pb.OrderResult{
		OrderId:            orderID.String(),
		ShippingTrackingId: shippingTrackingID,
		ShippingCost:       prep.shippingCostLocalized,
		ShippingAddress:    req.Address,
		Items:              prep.orderItems,
	}

	shippingCostFloat, _ := strconv.ParseFloat(fmt.Sprintf("%d.%02d", prep.shippingCostLocalized.GetUnits(), prep.shippingCostLocalized.GetNanos()/1000000000), 64)
	totalPriceFloat, _ := strconv.ParseFloat(fmt.Sprintf("%d.%02d", total.GetUnits(), total.GetNanos()/1000000000), 64)

	span.SetAttributes(
		attribute.String("app.order.id", orderID.String()),
		attribute.Float64("app.shipping.amount", shippingCostFloat),
		attribute.Float64("app.order.amount", totalPriceFloat),
		attribute.Int("app.order.items.count", len(prep.orderItems)),
		shippingTrackingAttribute,
	)
	logger.LogAttrs(
		ctx,
		slog.LevelInfo, "order placed",
		slog.String("app.order.id", orderID.String()),
		slog.Float64("app.shipping.amount", shippingCostFloat),
		slog.Float64("app.order.amount", totalPriceFloat),
		slog.Int("app.order.items.count", len(prep.orderItems)),
		slog.String("app.shipping.tracking.id", shippingTrackingID),
	)

	if err := cs.sendOrderConfirmation(ctx, req.Email, orderResult); err != nil {
		logger.Warn(fmt.Sprintf("failed to send order confirmation to %q: %+v", req.Email, err))
	} else {
		logger.Info(fmt.Sprintf("order confirmation email sent to %q", req.Email))
	}

	// send to kafka only if kafka broker address is set
	if cs.kafkaBrokerSvcAddr != "" {
		logger.Info("sending to postProcessor")
		cs.sendToPostProcessor(ctx, orderResult)
	}

	resp := &pb.PlaceOrderResponse{Order: orderResult}
	return resp, nil
}

type orderPrep struct {
	orderItems            []*pb.OrderItem
	cartItems             []*pb.CartItem
	shippingCostLocalized *pb.Money
}

func (cs *checkout) prepareOrderItemsAndShippingQuoteFromCart(ctx context.Context, userID, userCurrency string, address *pb.Address) (orderPrep, error) {

	ctx, span := tracer.Start(ctx, "prepareOrderItemsAndShippingQuoteFromCart")
	defer span.End()

	var out orderPrep
	cartItems, err := cs.getUserCart(ctx, userID)
	if err != nil {
		return out, fmt.Errorf("cart failure: %+v", err)
	}

	// Mandate #16: after the cart is loaded, item enrichment and shipping quote do
	// not depend on each other. Run them in parallel to shorten the checkout
	// critical path without adding capacity.
	var (
		orderItems  []*pb.OrderItem
		shippingUSD *pb.Money
		orderErr    error
		shippingErr error
		wg          sync.WaitGroup
	)
	wg.Add(2)
	go func() {
		defer wg.Done()
		orderItems, orderErr = cs.prepOrderItems(ctx, cartItems, userCurrency)
	}()
	go func() {
		defer wg.Done()
		shippingUSD, shippingErr = cs.quoteShipping(ctx, address, cartItems)
	}()
	wg.Wait()

	if orderErr != nil {
		return out, fmt.Errorf("failed to prepare order: %+v", orderErr)
	}
	if shippingErr != nil {
		return out, fmt.Errorf("shipping quote failure: %+v", shippingErr)
	}

	shippingPrice, err := cs.convertCurrency(ctx, shippingUSD, userCurrency)
	if err != nil {
		return out, fmt.Errorf("failed to convert shipping cost to currency: %+v", err)
	}

	out.shippingCostLocalized = shippingPrice
	out.cartItems = cartItems
	out.orderItems = orderItems

	var totalCart int32
	for _, ci := range cartItems {
		totalCart += ci.Quantity
	}
	shippingCostFloat, _ := strconv.ParseFloat(fmt.Sprintf("%d.%02d", shippingPrice.GetUnits(), shippingPrice.GetNanos()/1000000000), 64)

	span.SetAttributes(
		attribute.Float64("app.shipping.amount", shippingCostFloat),
		attribute.Int("app.cart.items.count", int(totalCart)),
		attribute.Int("app.order.items.count", len(orderItems)),
	)
	return out, nil
}

func mustCreateClient(svcAddr string) *grpc.ClientConn {
	c, err := grpc.NewClient(svcAddr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithStatsHandler(otelgrpc.NewClientHandler()),
	)
	if err != nil {
		logger.Error(fmt.Sprintf("could not connect to %s service, err: %+v", svcAddr, err))
	}

	return c
}

func (cs *checkout) quoteShipping(ctx context.Context, address *pb.Address, items []*pb.CartItem) (*pb.Money, error) {
	quotePayload, err := json.Marshal(map[string]interface{}{
		"address": address,
		"items":   items,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to marshal ship order request: %+v", err)
	}

	resp, err := otelhttp.Post(ctx, cs.shippingSvcAddr+"/get-quote", "application/json", bytes.NewBuffer(quotePayload))
	if err != nil {
		return nil, fmt.Errorf("failed POST to shipping service: %+v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("failed POST to email service: expected 200, got %d", resp.StatusCode)
	}

	shippingQuoteBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read shipping quote response: %+v", err)
	}

	var quoteResp struct {
		CostUsd *pb.Money `json:"cost_usd"`
	}
	if err := json.Unmarshal(shippingQuoteBytes, &quoteResp); err != nil {
		return nil, fmt.Errorf("failed to unmarshal shipping quote: %+v", err)
	}
	if quoteResp.CostUsd == nil {
		return nil, fmt.Errorf("shipping quote missing cost_usd field")
	}

	return quoteResp.CostUsd, nil
}

func (cs *checkout) getUserCart(ctx context.Context, userID string) ([]*pb.CartItem, error) {
	cart, err := cs.cartSvcClient.GetCart(ctx, &pb.GetCartRequest{UserId: userID})
	if err != nil {
		return nil, fmt.Errorf("failed to get user cart during checkout: %+v", err)
	}
	return cart.GetItems(), nil
}

func (cs *checkout) emptyUserCart(ctx context.Context, userID string) error {
	if _, err := cs.cartSvcClient.EmptyCart(ctx, &pb.EmptyCartRequest{UserId: userID}); err != nil {
		return fmt.Errorf("failed to empty user cart during checkout: %+v", err)
	}
	return nil
}

func (cs *checkout) prepOrderItems(
	ctx context.Context,
	items []*pb.CartItem,
	userCurrency string,
) ([]*pb.OrderItem, error) {

	out := make([]*pb.OrderItem, len(items))
	errCh := make(chan error, len(items))
	var wg sync.WaitGroup

	// Mandate #16: each cart line is independent, so enrich them concurrently to
	// reduce tail latency on larger carts while keeping response ordering stable.
	for i, item := range items {
		wg.Add(1)
		go func(i int, item *pb.CartItem) {
			defer wg.Done()

			product, err := cs.productCatalogSvcClient.GetProduct(ctx, &pb.GetProductRequest{Id: item.GetProductId()})
			if err != nil {
				errCh <- fmt.Errorf("failed to get product #%q", item.GetProductId())
				return
			}

			price, err := cs.convertCurrency(ctx, product.GetPriceUsd(), userCurrency)
			if err != nil {
				errCh <- fmt.Errorf("failed to convert price of %q to %s", item.GetProductId(), userCurrency)
				return
			}

			out[i] = &pb.OrderItem{
				Item: item,
				Cost: price,
			}
		}(i, item)
	}

	wg.Wait()
	close(errCh)

	for err := range errCh {
		if err != nil {
			return nil, err
		}
	}

	return out, nil
}

func (cs *checkout) convertCurrency(ctx context.Context, from *pb.Money, toCurrency string) (*pb.Money, error) {
	// Mandate #16: USD is already the source currency for catalog/shipping
	// prices. Skip the RPC when no conversion is needed.
	if from == nil || toCurrency == "" || from.GetCurrencyCode() == toCurrency {
		return from, nil
	}

	result, err := cs.currencySvcClient.Convert(ctx, &pb.CurrencyConversionRequest{
		From:   from,
		ToCode: toCurrency})
	if err != nil {
		return nil, fmt.Errorf("failed to convert currency: %+v", err)
	}
	return result, err
}

func (cs *checkout) chargeCard(ctx context.Context, amount *pb.Money, paymentInfo *pb.CreditCardInfo) (string, error) {
	paymentService := cs.paymentSvcClient
	if cs.isFeatureFlagEnabled(ctx, "paymentUnreachable") {
		badAddress := "badAddress:50051"
		c := mustCreateClient(badAddress)
		paymentService = pb.NewPaymentServiceClient(c)
	}

	paymentResp, err := paymentService.Charge(ctx, &pb.ChargeRequest{
		Amount:     amount,
		CreditCard: paymentInfo})
	if err != nil {
		return "", fmt.Errorf("could not charge the card: %+v", err)
	}
	return paymentResp.GetTransactionId(), nil
}

func (cs *checkout) sendOrderConfirmation(ctx context.Context, email string, order *pb.OrderResult) error {
	emailPayload, err := json.Marshal(map[string]interface{}{
		"email": email,
		"order": order,
	})
	if err != nil {
		return fmt.Errorf("failed to marshal order to JSON: %+v", err)
	}

	resp, err := otelhttp.Post(ctx, cs.emailSvcAddr+"/send_order_confirmation", "application/json", bytes.NewBuffer(emailPayload))
	if err != nil {
		return fmt.Errorf("failed POST to email service: %+v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("failed POST to email service: expected 200, got %d", resp.StatusCode)
	}

	return err
}

func (cs *checkout) shipOrder(ctx context.Context, address *pb.Address, items []*pb.CartItem) (string, error) {
	shipPayload, err := json.Marshal(map[string]interface{}{
		"address": address,
		"items":   items,
	})
	if err != nil {
		return "", fmt.Errorf("failed to marshal ship order request: %+v", err)
	}

	resp, err := otelhttp.Post(ctx, cs.shippingSvcAddr+"/ship-order", "application/json", bytes.NewBuffer(shipPayload))
	if err != nil {
		return "", fmt.Errorf("failed POST to shipping service: %+v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("failed POST to email service: expected 200, got %d", resp.StatusCode)
	}

	trackingRespBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("failed to read ship order response: %+v", err)
	}

	var shipResp struct {
		TrackingID string `json:"tracking_id"`
	}
	if err := json.Unmarshal(trackingRespBytes, &shipResp); err != nil {
		return "", fmt.Errorf("failed to unmarshal ship order response: %+v", err)
	}
	if shipResp.TrackingID == "" {
		return "", fmt.Errorf("ship order response missing tracking_id field")
	}

	return shipResp.TrackingID, nil
}

func (cs *checkout) sendToPostProcessor(ctx context.Context, result *pb.OrderResult) {
	// Phòng thủ nhiều lớp: bootstrap đã fail-fast (xem main) nên producer không thể
	// nil ở production. Vẫn guard để nếu có bug logic khiến producer nil thì degrade
	// thành log lỗi ồn ào thay vì panic giữa đơn hàng (nguyên nhân outage 0010).
	if cs.KafkaProducerClient == nil {
		stderrLog.Error("order event KHONG duoc phat: Kafka producer nil")
		logger.Error("order event KHONG duoc phat: Kafka producer nil")
		return
	}

	message, err := proto.Marshal(result)
	if err != nil {
		logger.Error(fmt.Sprintf("Failed to marshal message to protobuf: %+v", err))
		return
	}

	// M9-03: SET message key = order_id
	// Kafka partition theo key → cùng order_id luôn vào cùng partition (ordering).
	// Consumer idempotency cũng dựa vào order_id làm dedup key.
	msg := sarama.ProducerMessage{
		Topic: kafka.Topic,
		Key:   sarama.StringEncoder(result.OrderId), // M9-03: BẮT BUỘC set key
		Value: sarama.ByteEncoder(message),
	}

	// Inject tracing info into message
	span := createProducerSpan(ctx, &msg)
	defer span.End()

	// Send message and handle response. SyncProducer.SendMessage blocks until
	// this specific message is acked (or fails/times out per
	// saramaConfig.Producer.Timeout) - the result belongs to this call only,
	// unlike AsyncProducer's shared Successes()/Errors() channels which used
	// to race across concurrent PlaceOrder calls on the same pod (see
	// kafka/producer.go for the full explanation of why that hung requests).
	startTime := time.Now()
	partition, offset, err := cs.KafkaProducerClient.SendMessage(&msg)
	if err != nil {
		span.SetAttributes(
			attribute.Bool("messaging.kafka.producer.success", false),
			attribute.Int("messaging.kafka.producer.duration_ms", int(time.Since(startTime).Milliseconds())),
		)
		span.SetStatus(otelcodes.Error, err.Error())
		logger.Error(fmt.Sprintf("Failed to write message: %v", err))
		// Không nuốt: tee ra stderr để lỗi produce hiện trong `kubectl logs` khi cutover.
		stderrLog.Error(fmt.Sprintf("Failed to write order event to Kafka: %v", err))
	} else {
		span.SetAttributes(
			attribute.Bool("messaging.kafka.producer.success", true),
			attribute.Int("messaging.kafka.producer.duration_ms", int(time.Since(startTime).Milliseconds())),
			attribute.KeyValue(semconv.MessagingKafkaMessageOffset(int(offset))),
			attribute.KeyValue(semconv.MessagingKafkaDestinationPartition(int(partition))),
		)
		logger.Info(fmt.Sprintf("Successful to write message. offset: %v, duration: %v", offset, time.Since(startTime)))
	}

	ffValue := cs.getIntFeatureFlag(ctx, "kafkaQueueProblems")
	if ffValue > 0 {
		logger.Info("Warning: FeatureFlag 'kafkaQueueProblems' is activated, overloading queue now.")
		for i := 0; i < ffValue; i++ {
			m := msg // own copy per goroutine - SendMessage may mutate the message it's given
			go func(i int, m sarama.ProducerMessage) {
				if _, _, err := cs.KafkaProducerClient.SendMessage(&m); err != nil {
					logger.Error(fmt.Sprintf("kafkaQueueProblems overload message #%d failed: %v", i, err))
				}
			}(i, m)
		}
		logger.Info(fmt.Sprintf("Done with #%d messages for overload simulation.", ffValue))
	}
}

func createProducerSpan(ctx context.Context, msg *sarama.ProducerMessage) trace.Span {
	spanContext, span := tracer.Start(
		ctx,
		fmt.Sprintf("%s publish", msg.Topic),
		trace.WithSpanKind(trace.SpanKindProducer),
		trace.WithAttributes(
			semconv.PeerService("kafka"),
			semconv.NetworkTransportTCP,
			semconv.MessagingSystemKafka,
			semconv.MessagingDestinationName(msg.Topic),
			semconv.MessagingOperationPublish,
			semconv.MessagingKafkaDestinationPartition(int(msg.Partition)),
		),
	)

	carrier := propagation.MapCarrier{}
	propagator := otel.GetTextMapPropagator()
	propagator.Inject(spanContext, carrier)

	for key, value := range carrier {
		msg.Headers = append(msg.Headers, sarama.RecordHeader{Key: []byte(key), Value: []byte(value)})
	}

	return span
}

func (cs *checkout) isFeatureFlagEnabled(ctx context.Context, featureFlagName string) bool {
	client := openfeature.NewClient("checkout")

	// Default value is set to false, but you could also make this a parameter.
	featureEnabled, _ := client.BooleanValue(
		ctx,
		featureFlagName,
		false,
		openfeature.EvaluationContext{},
	)

	return featureEnabled
}

func (cs *checkout) getIntFeatureFlag(ctx context.Context, featureFlagName string) int {
	client := openfeature.NewClient("checkout")

	// Default value is set to 0, but you could also make this a parameter.
	featureFlagValue, _ := client.IntValue(
		ctx,
		featureFlagName,
		0,
		openfeature.EvaluationContext{},
	)

	return int(featureFlagValue)
}
