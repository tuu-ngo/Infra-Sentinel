// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { CallOptions, ChannelCredentials, Metadata } from '@grpc/grpc-js';
import { dnsTarget, loadBalancedChannelOptions } from './grpcChannel';
import {ProductReview, ProductReviewServiceClient} from '../../protos/demo';

const { PRODUCT_REVIEWS_ADDR = '' } = process.env;

// Mandate 17 (REL-17-02): bound product-review calls (fail-fast). Reviews are
// non-critical browse-page enrichment (loaded client-side via react-query, which
// degrades on its own) — a hung review service must not hold the request.
const PRODUCT_REVIEWS_DEADLINE_MS = Number(process.env.PRODUCT_REVIEWS_DEADLINE_MS) || 500;
// The AI assistant calls an LLM (Bedrock) and is slow BY DESIGN — a 500ms deadline
// would make it always time out. Give it a generous ceiling that still bounds an
// infinite hang. It is user-initiated (not on the browse SLO path), so a longer wait
// is acceptable.
const PRODUCT_AI_DEADLINE_MS = Number(process.env.PRODUCT_AI_DEADLINE_MS) || 15000;

const client = new ProductReviewServiceClient(
  dnsTarget(PRODUCT_REVIEWS_ADDR),
  ChannelCredentials.createInsecure(),
  loadBalancedChannelOptions
);

const deadlineOf = (ms: number): Partial<CallOptions> => ({ deadline: Date.now() + ms });

const ProductReviewGateway = () => ({

    getProductReviews(productId: string) {
        return new Promise<ProductReview []>((resolve, reject) =>
            client.getProductReviews({ productId }, new Metadata(), deadlineOf(PRODUCT_REVIEWS_DEADLINE_MS), (error, response) => (error ? reject(error) : resolve(response.productReviews)))
        );
    },
    getAverageProductReviewScore(productId: string) {
        return new Promise<string>((resolve, reject) =>
            client.getAverageProductReviewScore({ productId }, new Metadata(), deadlineOf(PRODUCT_REVIEWS_DEADLINE_MS), (error, response) => (error ? reject(error) : resolve(response.averageScore)))
        );
    },
    askProductAIAssistant(productId: string, question: string) {
        return new Promise<string>((resolve, reject) =>
            client.askProductAiAssistant({ productId, question }, new Metadata(), deadlineOf(PRODUCT_AI_DEADLINE_MS), (error, response) => (error ? reject(error) : resolve(response.response)))
        );
    },
});

export default ProductReviewGateway();
