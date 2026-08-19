// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { CallOptions, ChannelCredentials, Metadata } from '@grpc/grpc-js';
import { dnsTarget, loadBalancedChannelOptions } from './grpcChannel';
import { AdResponse, AdServiceClient } from '../../protos/demo';

const { AD_ADDR = '' } = process.env;

// Mandate 17 (REL-17-02): bound the ad call with a deadline so a slow/hung ad
// service can never hang the frontend request. gRPC-js has NO default deadline —
// without this a hung downstream blocks the Next.js request indefinitely. Ads are
// non-critical page enrichment; the caller degrades to no-ads on error/timeout.
const AD_DEADLINE_MS = Number(process.env.AD_DEADLINE_MS) || 300;

const client = new AdServiceClient(
  dnsTarget(AD_ADDR),
  ChannelCredentials.createInsecure(),
  loadBalancedChannelOptions
);

const AdGateway = () => ({
  listAds(contextKeys: string[]) {
    const options: Partial<CallOptions> = { deadline: Date.now() + AD_DEADLINE_MS };
    return new Promise<AdResponse>((resolve, reject) =>
      client.getAds({ contextKeys: contextKeys }, new Metadata(), options, (error, response) =>
        error ? reject(error) : resolve(response)
      )
    );
  },
});

export default AdGateway();
