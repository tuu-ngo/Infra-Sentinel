# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

FROM envoyproxy/envoy:v1.34.10@sha256:3343a698c1bdfdbb174f1bd907dea789d728692f4f99a943e3e6f0bc5ef6513f

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y gettext-base && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

USER envoy

WORKDIR /home/envoy

COPY ./src/frontend-proxy/envoy.tmpl.yaml envoy.tmpl.yaml
COPY --chmod=755 ./src/frontend-proxy/entrypoint.sh entrypoint.sh

# validate config
RUN ENVOY_ADDR=0.0.0.0 \
    ENVOY_ADMIN_PORT=10000 \
    ENVOY_PORT=8080 \
    FLAGD_HOST=localhost \
    FLAGD_PORT=8013 \
    FLAGD_UI_HOST=localhost \
    FLAGD_UI_PORT=8080 \
    FRONTEND_HOST=localhost \
    FRONTEND_PORT=8080 \
    GRAFANA_HOST=localhost \
    GRAFANA_PORT=8080 \
    IMAGE_PROVIDER_HOST=localhost \
    IMAGE_PROVIDER_PORT=8080 \
    JAEGER_HOST=localhost \
    JAEGER_UI_PORT=8080 \
    LOCUST_WEB_HOST=localhost \
    LOCUST_WEB_PORT=8080 \
    OTEL_COLLECTOR_HOST=localhost \
    OTEL_COLLECTOR_PORT_GRPC=8080 \
    OTEL_COLLECTOR_PORT_HTTP=8080 \
    OTEL_SERVICE_NAME=frontend-proxy \
    BROWSE_RATE_LIMIT_MAX_TOKENS=66 \
    BROWSE_RATE_LIMIT_TOKENS_PER_FILL=33 \
    BROWSE_RATE_LIMIT_FILL_INTERVAL=1s \
    BROWSE_RATE_LIMIT_ENABLED_PERCENT=100 \
    BROWSE_RATE_LIMIT_ENFORCED_PERCENT=100 \
    LOCAL_RATE_LIMIT_ENABLED_PERCENT=100 \
    LOCAL_RATE_LIMIT_ENFORCED_PERCENT=0 \
    envsubst < envoy.tmpl.yaml > /tmp/envoy-rendered.yaml && envoy --mode validate -c /tmp/envoy-rendered.yaml

EXPOSE ${ENVOY_PORT}
EXPOSE ${ENVOY_ADMIN_PORT}
ENTRYPOINT ["./entrypoint.sh"]
