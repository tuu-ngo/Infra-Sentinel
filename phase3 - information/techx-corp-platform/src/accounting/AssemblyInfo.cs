// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

// M9-03: Grant the unit-test assembly access to internal types
// (OrderEntity, OrderItemEntity, ShippingEntity, IdempotencyChecker, IdempotencyResult, etc.)
// without changing their visibility in production code.
//
// This attribute is resolved by the C# compiler from the assembly name declared in
// tests/Accounting.Tests.csproj — no local path involved, works in any CI/CD environment.
using System.Runtime.CompilerServices;

[assembly: InternalsVisibleTo("Accounting.Tests")]
