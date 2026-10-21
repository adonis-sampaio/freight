# ADR 015: Mock integrations behind a stable interface

* **Status:** accepted
* **Slug:** `mock-integrations-behind-a-stable-interface`

## Context

The assessment permits mocks, and building real integrations adds
cost, credentials and failure modes without adding design insight. But a mock
that does not look like the real thing is worthless, because the interface
bakes in the wrong assumptions.

## Decision

Each integration has a protocol, a mock implementation, and a
contract test that both satisfy. The mock records what it was asked to send
and returns a delivery result, exactly as the real adapter would. When a real
adapter arrives, it implements the same protocol, and the contract test that
the mock passes is the test the real adapter has to pass too.

`MockAdapter` is the default in this repository, which is why the entire
system - including the CLI demo and the whole eval suite - runs with no
credentials at all.

## Consequences

The system is fully demonstrable and testable offline, and adding a
real provider is a contained change. The cost is that the mocks are only as
faithful as the interface, and a real provider will expose interface gaps
that the mock could not.

## Alternatives considered

Building real integrations now (out of scope, more cost, less
insight), or no abstraction at all (the engine becomes untestable).
