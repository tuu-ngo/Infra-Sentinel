// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
package kafka

import (
	"crypto/tls"
	"fmt"
	"log/slog"
	"time"

	"github.com/IBM/sarama"
)

var (
	Topic           = "orders"
	ProtocolVersion = sarama.V3_0_0_0
)

// SecurityConfig gom cấu hình TLS + SASL/SCRAM cho Kafka, đọc từ env (xem main.go).
// Mandate #8: MSK yêu cầu SASL_SSL + SCRAM-SHA-512. Mặc định rỗng = PLAINTEXT =
// hành vi hiện tại với Kafka in-cluster (không TLS, không auth) → deploy an toàn trước cutover.
type SecurityConfig struct {
	// Protocol: "", "PLAINTEXT" (mặc định) | "SASL_SSL" | "SASL_PLAINTEXT" | "SSL".
	Protocol string
	Username string
	Password string
}

func (s SecurityConfig) useSASL() bool {
	return s.Protocol == "SASL_SSL" || s.Protocol == "SASL_PLAINTEXT"
}

func (s SecurityConfig) useTLS() bool {
	return s.Protocol == "SASL_SSL" || s.Protocol == "SSL"
}

type saramaLogger struct {
	logger *slog.Logger
}

func (l *saramaLogger) Printf(format string, v ...interface{}) {
	l.logger.Info(fmt.Sprintf(format, v...))
}
func (l *saramaLogger) Println(v ...interface{}) {
	l.logger.Info(fmt.Sprint(v...))
}
func (l *saramaLogger) Print(v ...interface{}) {
	l.logger.Info(fmt.Sprint(v...))
}

func CreateKafkaProducer(brokers []string, logger *slog.Logger, secCfg SecurityConfig) (sarama.SyncProducer, error) {
	// Set the logger for sarama to use.
	sarama.Logger = &saramaLogger{logger: logger}

	saramaConfig := sarama.NewConfig()
	saramaConfig.Producer.Return.Successes = true
	saramaConfig.Producer.Return.Errors = true

	// Mandate #8: bật TLS + SASL/SCRAM-SHA-512 khi env yêu cầu (MSK). Mặc định tắt = hành vi cũ.
	if secCfg.useTLS() {
		saramaConfig.Net.TLS.Enable = true
		// MSK dùng cert từ CA công cộng (Amazon Trust Services) → root CA hệ thống của
		// image builder là đủ, không cần mount custom CA bundle.
		saramaConfig.Net.TLS.Config = &tls.Config{MinVersion: tls.VersionTLS12}
	}
	if secCfg.useSASL() {
		saramaConfig.Net.SASL.Enable = true
		saramaConfig.Net.SASL.User = secCfg.Username
		saramaConfig.Net.SASL.Password = secCfg.Password
		saramaConfig.Net.SASL.Mechanism = sarama.SASLTypeSCRAMSHA512
		saramaConfig.Net.SASL.SCRAMClientGeneratorFunc = func() sarama.SCRAMClient {
			return &XDGSCRAMClient{HashGeneratorFcn: SHA512}
		}
	}

	// REL-09: order events are financial data - do NOT fire-and-forget.
	// The previous RequiredAcks=NoResponse silently swallowed failed messages,
	// so an order could be charged but never recorded (order lost with no trace).
	// WaitForAll makes the broker acknowledge before we consider the send done;
	// Idempotent + MaxOpenRequests=1 lets us retry safely without producing
	// duplicate order events.
	saramaConfig.Producer.RequiredAcks = sarama.WaitForAll
	// M9-03: Bump Retry.Max 3→10 để chịu được MSK rolling upgrade.
	// Trong quá trình rolling, một broker có thể temporarily unavailable (~10-20s/broker).
	// Retry.Max=10 với backoff mặc định ~100ms/retry ≈ ~1s tổng retry budget.
	// Nằm trong end-to-end deadline 15s của PlaceOrder (checkout context timeout).
	saramaConfig.Producer.Retry.Max = 10
	saramaConfig.Producer.Idempotent = true
	saramaConfig.Net.MaxOpenRequests = 1

	// M9-03: Producer.Timeout - thời gian tối đa một produce request chờ broker ack.
	// End-to-end budget: client→CloudFront→Envoy→frontend→gRPC→DB ≈ 15s (PlaceOrder timeout).
	// Breakdown: gRPC checkout ≤ 10s, Kafka produce ≤ 5s (giữ nguyên từ REL-09).
	// 5s đủ cho MSK rolling (broker leader election ≈ 1-3s) và nằm trong 10s checkout budget.
	saramaConfig.Producer.Timeout = 5 * time.Second

	saramaConfig.Version = ProtocolVersion

	// SyncProducer instead of AsyncProducer: PlaceOrder already awaits the
	// result of every publish synchronously (sendToPostProcessor has no `go`),
	// so there is no async benefit here - only risk. AsyncProducer's
	// Successes()/Errors() are channels shared by the WHOLE producer instance
	// (one per pod, reused by every concurrent PlaceOrder call); waiting on
	// them per-request races across goroutines, since Go delivers each value
	// to exactly one receiver with no correlation to which request produced
	// it. Under concurrent checkout traffic, a request's own ack can be
	// received by a *different* concurrent request's select (or lost to the
	// idle Errors()-draining goroutine below), leaving the original request
	// blocked until ctx.Done() - in practice until the caller's ~15s timeout,
	// which is exactly the symptom this was causing. SyncProducer.SendMessage
	// returns the result of that specific call directly, so there's nothing
	// to race on.
	producer, err := sarama.NewSyncProducer(brokers, saramaConfig)
	if err != nil {
		return nil, err
	}
	return producer, nil
}
