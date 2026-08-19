// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { CallOptions, ChannelCredentials, Metadata } from '@grpc/grpc-js';
import { dnsTarget, loadBalancedChannelOptions } from './grpcChannel';
import { ListProductsResponse, Product, ProductCatalogServiceClient } from '../../protos/demo';

const { PRODUCT_CATALOG_ADDR = '' } = process.env;

// Mandate 17 (REL-17-02): bound product-catalog calls with a deadline. This is
// fail-fast, NOT a fallback — product-catalog is a critical dependency (we must never
// fabricate a product), but it must never HANG. gRPC-js has no default deadline, so a
// hung product-catalog would hold EVERY browse/recommendation request indefinitely and
// exhaust connection pools. On timeout the call rejects fast and the caller surfaces the
// error instead of hanging.
const PRODUCT_CATALOG_DEADLINE_MS = Number(process.env.PRODUCT_CATALOG_DEADLINE_MS) || 500;

const client = new ProductCatalogServiceClient(
  dnsTarget(PRODUCT_CATALOG_ADDR),
  ChannelCredentials.createInsecure(),
  loadBalancedChannelOptions
);

const callOptions = (): Partial<CallOptions> => ({ deadline: Date.now() + PRODUCT_CATALOG_DEADLINE_MS });

const ProductCatalogGateway = () => ({
  listProducts() {
    return new Promise<ListProductsResponse>((resolve, reject) =>
      client.listProducts({}, new Metadata(), callOptions(), (error, response) =>
        error ? reject(error) : resolve(response)
      )
    );
  },
  getProduct(id: string) {
    return new Promise<Product>((resolve, reject) =>
      client.getProduct({ id }, new Metadata(), callOptions(), (error, response) =>
        error ? reject(error) : resolve(response)
      )
    );
  },
});

export default ProductCatalogGateway();
