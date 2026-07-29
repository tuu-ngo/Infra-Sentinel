# Mandate 17 service access flow scenario

This document describes the intended business communication flows before
NetworkPolicy enforcement. It is a review scenario for confirming that the
allow list is complete and that unnecessary east-west access can be removed
without interrupting the application.

The rule is simple:

- The services in the Allowed column must keep working.
- The services in the Not allowed column have no approved business dependency
  and should be blocked after enforcement.
- A service may still appear reachable before enforcement. The Not allowed
  column describes the desired final state, not the current baseline.

## Critical customer journey

The following flow must remain available:

~~~text
frontend-proxy
  -> frontend
      -> product-catalog
      -> cart
      -> currency
      -> ad
      -> recommendation
      -> product-reviews
      -> checkout
          -> cart
          -> product-catalog
          -> currency
          -> payment
          -> email
          -> shipping
              -> quote
~~~

The checkout service does not call quote directly. The approved path is
checkout -> shipping -> quote.

## Business service access map

### frontend-proxy

Allowed:

- frontend
- image-provider
- flagd
- observability telemetry

Not allowed:

- payment
- checkout directly
- cart directly
- product-catalog directly
- databases, Kafka, or other business data stores

Reason: frontend-proxy is the edge route. It should forward user traffic to
frontend and preserve the protected flag path, but it should not become a
general-purpose business service caller.

### frontend

Allowed:

- product-catalog
- cart
- currency
- ad
- recommendation
- product-reviews
- checkout
- shipping where the storefront needs shipping information
- flagd runtime reads
- observability telemetry

Not allowed:

- payment directly
- quote directly
- accounting
- fraud-detection
- Kafka
- RDS, Valkey, or other managed data stores directly

Reason: frontend orchestrates the customer-facing browsing and checkout entry
points. Payment must be reached through checkout.

### checkout

Allowed:

- cart
- product-catalog
- currency
- payment
- email
- shipping
- flagd runtime reads
- Kafka for the checkout event
- observability telemetry

Not allowed:

- quote directly
- recommendation
- ad
- product-reviews
- frontend
- frontend-proxy
- accounting or fraud-detection by direct request
- Internet without an explicitly reviewed exception

Reason: checkout owns the order flow. Accounting and fraud-detection consume
checkout events through Kafka rather than being called synchronously by
checkout.

### cart

Allowed:

- Valkey
- flagd runtime reads
- observability telemetry

Not allowed:

- payment
- checkout
- product-catalog
- currency
- shipping
- quote
- accounting
- fraud-detection
- Internet

Reason: cart stores cart state. It should not initiate payment or act as a
general caller to other business services.

### product-catalog

Allowed:

- its PostgreSQL datastore
- flagd runtime reads
- observability telemetry

Not allowed:

- payment
- cart
- checkout
- shipping
- quote
- accounting
- fraud-detection
- Internet

Incoming approved callers:

- frontend
- checkout
- recommendation
- product-reviews

Reason: product-catalog provides product data and owns its database access.

### currency

Allowed:

- flagd runtime reads
- observability telemetry

Not allowed:

- payment
- cart
- product-catalog
- checkout
- shipping
- quote
- Internet

Incoming approved callers:

- frontend
- checkout

Reason: currency provides conversion data and should remain a narrow leaf
service.

### payment

Allowed:

- flagd runtime reads
- observability telemetry

Incoming approved caller:

- checkout

Not allowed:

- cart
- frontend
- frontend-proxy
- product-catalog
- currency
- shipping
- quote
- email
- recommendation
- product-reviews
- accounting
- fraud-detection
- Internet

Reason: payment is a protected money-path service. Only checkout should
initiate payment requests.

### shipping

Allowed:

- quote
- observability telemetry

Incoming approved callers:

- frontend
- checkout

Not allowed:

- payment
- cart
- product-catalog
- currency
- email
- recommendation
- product-reviews
- accounting
- fraud-detection
- Internet

Reason: shipping is the approved intermediary between checkout and quote.

### quote

Allowed:

- observability telemetry

Incoming approved caller:

- shipping

Not allowed:

- payment
- checkout directly
- cart
- frontend
- product-catalog
- currency
- email
- recommendation
- product-reviews
- Internet

Reason: quote is a narrow leaf service used by shipping.

### email

Allowed:

- flagd runtime reads
- observability telemetry

Incoming approved caller:

- checkout

Not allowed:

- payment
- cart
- frontend
- product-catalog
- shipping
- quote
- recommendation
- product-reviews
- Internet unless a separately reviewed mail provider exception exists

Reason: email is used for order notification and should not become a general
outbound communication channel.

### recommendation

Allowed:

- product-catalog
- flagd runtime reads
- observability telemetry

Incoming approved caller:

- frontend

Not allowed:

- payment
- checkout
- cart
- shipping
- quote
- email
- product-reviews
- accounting
- fraud-detection
- Internet

Reason: recommendation reads product information but does not participate in
checkout or payment.

### ad

Allowed:

- flagd runtime reads
- observability telemetry

Incoming approved caller:

- frontend

Not allowed:

- payment
- checkout
- cart
- product-catalog
- shipping
- quote
- email
- recommendation
- product-reviews
- Internet

Reason: ad is a narrow frontend dependency.

### product-reviews

Allowed:

- product-catalog
- its PostgreSQL datastore
- its ElastiCache Valkey guardrail cache
- flagd runtime reads
- observability telemetry
- AWS Bedrock through the approved production provider

Incoming approved caller:

- frontend
- shopping-copilot

Not allowed:

- local llm in the current production provider mode
- payment
- checkout
- cart
- shipping
- quote
- email
- recommendation
- accounting
- fraud-detection
- unrestricted Internet

Reason: product-reviews needs product data and Bedrock, but the Bedrock
exception must not become unrestricted public egress.

### image-provider

Allowed:

- observability telemetry

Incoming approved caller:

- frontend-proxy

Not allowed:

- payment
- checkout
- cart
- product-catalog
- shipping
- quote
- email
- recommendation
- product-reviews
- Internet

Reason: image-provider is reached through the edge proxy only.

### llm

Allowed:

- flagd runtime reads

Incoming approved caller:

- none in the current production configuration

Not allowed:

- product-reviews while Bedrock is the active provider
- payment
- checkout
- frontend
- cart
- product-catalog
- shipping
- quote
- email
- recommendation
- Internet

Reason: the local LLM is retained as a controlled rollback option, not an
active production dependency.

### accounting

Allowed:

- PostgreSQL datastore
- Kafka checkout events
- observability telemetry

Incoming approved caller:

- Kafka event stream rather than a synchronous business request

Not allowed:

- payment
- checkout direct request
- cart
- frontend
- product-catalog
- shipping
- quote
- email
- recommendation
- product-reviews
- Internet

Reason: accounting consumes order events and should not be reachable as a
general synchronous service.

### fraud-detection

Allowed:

- Kafka checkout events
- flagd runtime reads
- observability telemetry

Incoming approved caller:

- Kafka event stream rather than a synchronous business request

Not allowed:

- payment
- checkout direct request
- cart
- frontend
- product-catalog
- shipping
- quote
- email
- recommendation
- product-reviews
- Internet

Reason: fraud-detection evaluates checkout events asynchronously.

### flagd

Allowed:

- runtime flag reads from the approved business services
- frontend-proxy protected runtime path
- the exact approved flag synchronization source
- observability telemetry

Not allowed:

- payment or other business-service calls
- arbitrary Internet destinations
- changing or removing the /flagservice route

Reason: flagd is a shared runtime dependency. Its read path must remain
available, but it must not become a general network bridge.

## Platform communication

The platform services have a separate narrow communication group:

- OTel Gateway may receive telemetry and send it to Jaeger, Prometheus, and
  OpenSearch.
- Grafana may read Prometheus, Jaeger, and OpenSearch.
- Jaeger may query Prometheus and send telemetry to OTel Gateway.
- Prometheus may reach the private Kubernetes API for discovery.
- OpenSearch needs DNS and receives data from approved observability writers.
- Load-generator may reach frontend-proxy, flagd, and OTel Gateway.
- Cloudflared may reach the approved frontend-proxy and protected operations
  routes, plus its Cloudflare tunnel endpoints.
- AIOps may read Prometheus, Jaeger, and OpenSearch, plus its approved Slack
  notification endpoint.

These platform services should not reach payment or arbitrary business
datastores.

## Egress policy summary

Business services have no general Internet access. The reviewed exceptions are:

- product-reviews to the production Bedrock provider.
- flagd to its exact synchronization source.
- cloudflared to Cloudflare tunnel endpoints.
- AIOps to its approved Slack notification endpoint.

All other public egress should be treated as not allowed unless a new
dependency is audited and added through a separate reviewed change.

## Review acceptance

Before enforcement, confirm that every Allowed flow works in the current
system. After each policy promotion, confirm that the same Allowed flow still
works and that at least one Not allowed flow is blocked. After the final
default-deny policy, repeat the customer journey:

~~~text
browse -> add to cart -> checkout -> payment
~~~

Also confirm:

- shipping -> quote still works.
- checkout does not call quote directly.
- product-reviews can reach Bedrock.
- /flagservice remains available.
- no business pod can use an unrelated service as a lateral hop.
