// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { CallOptions, ChannelCredentials, Metadata } from '@grpc/grpc-js';
import { dnsTarget, loadBalancedChannelOptions } from './grpcChannel';
import { ListRecommendationsResponse, RecommendationServiceClient } from '../../protos/demo';

const { RECOMMENDATION_ADDR = '' } = process.env;

// Mandate 17 (REL-17-02): bound the recommendation call with a deadline so a
// slow/hung recommendation service cannot hang the frontend request. Recommendations
// are non-critical page enrichment; the caller degrades to none on error/timeout.
const RECO_DEADLINE_MS = Number(process.env.RECOMMENDATION_DEADLINE_MS) || 500;

const client = new RecommendationServiceClient(
  dnsTarget(RECOMMENDATION_ADDR),
  ChannelCredentials.createInsecure(),
  loadBalancedChannelOptions
);

const RecommendationsGateway = () => ({
  listRecommendations(userId: string, productIds: string[]) {
    const options: Partial<CallOptions> = { deadline: Date.now() + RECO_DEADLINE_MS };
    return new Promise<ListRecommendationsResponse>((resolve, reject) =>
      client.listRecommendations({ userId, productIds }, new Metadata(), options, (error, response) =>
        error ? reject(error) : resolve(response)
      )
    );
  },
});

export default RecommendationsGateway();
