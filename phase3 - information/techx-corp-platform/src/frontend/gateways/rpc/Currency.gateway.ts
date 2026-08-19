// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { CallOptions, ChannelCredentials, Metadata } from '@grpc/grpc-js';
import { dnsTarget, loadBalancedChannelOptions } from './grpcChannel';
import { GetSupportedCurrenciesResponse, CurrencyServiceClient, Money } from '../../protos/demo';

const { CURRENCY_ADDR = '' } = process.env;

// Mandate 17 (REL-17-02): bound currency calls with a deadline (fail-fast). A hung
// currency service must not hold the request — it sits on the browse/product path via
// ProductCatalogService.getProductPrice. gRPC-js has no default deadline; on timeout the
// call rejects fast instead of hanging.
const CURRENCY_DEADLINE_MS = Number(process.env.CURRENCY_DEADLINE_MS) || 500;

const client = new CurrencyServiceClient(
  dnsTarget(CURRENCY_ADDR),
  ChannelCredentials.createInsecure(),
  loadBalancedChannelOptions
);

const callOptions = (): Partial<CallOptions> => ({ deadline: Date.now() + CURRENCY_DEADLINE_MS });

const CurrencyGateway = () => ({
  convert(from: Money, toCode: string) {
    return new Promise<Money>((resolve, reject) =>
      client.convert({ from, toCode }, new Metadata(), callOptions(), (error, response) =>
        error ? reject(error) : resolve(response)
      )
    );
  },
  getSupportedCurrencies() {
    return new Promise<GetSupportedCurrenciesResponse>((resolve, reject) =>
      client.getSupportedCurrencies({}, new Metadata(), callOptions(), (error, response) =>
        error ? reject(error) : resolve(response)
      )
    );
  },
});

export default CurrencyGateway();
