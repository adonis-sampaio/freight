# ADR 014: Adapters are the only things that talk to the outside world

* **Status:** accepted
* **Slug:** `adapters-own-the-outside-world`

## Context

A core that calls Twilio directly cannot be tested without a Twilio
account, cannot be replayed offline, and cannot be evaluated against a
recorded transcript. Every integration also has a different failure shape,
and they should not all be handled in the same place.

## Decision

The engine produces actions; a set of adapters performs them. Each
adapter is a small object with a single method, a typed result, and a mock
implementation that records instead of sending. The action ledger and the
audit trail are written by the core, so the record of what was *attempted*
exists even if the delivery failed.

## Consequences

The whole system runs offline, which is what makes the evaluation
harness possible. A real Twilio, Slack or TMS adapter is a new class and a
new entry in a registry, with no change to the engine. Contract tests run
against the mock and against the real adapter.

The cost is a layer of indirection, and the discipline to keep every side
effect behind an adapter boundary.

## Alternatives considered

Direct calls from the engine (untestable, not replayable), or a
single mega-adapter (all the failure modes in one place).
