# ADR 013: At-least-once execution with an idempotency key per action

* **Status:** accepted
* **Slug:** `at-least-once-with-an-idempotency-key`

## Context

Webhooks retry. Email providers retry. A driver who receives the
same ETA request twice is a real complaint, and a dispatcher who receives the
same escalation email twice is a real escalation. At-most-once delivery is
not available: the alternative to sending twice is not sending, and a lost
escalation is worse than a duplicate one.

## Decision

Every outbound action carries an idempotency key derived from the
load, the event that caused it, the procedure and the step. The action
ledger records the key, and a second attempt with the same key is suppressed
before the adapter is called. The same key is sent to the provider as a
provider-side idempotency token, so the suppression survives our own crash
between "recorded" and "sent".

## Consequences

Duplicates are prevented at two levels, ours and the provider's, and
the ledger says which actions were attempted. Delivery is at-least-once, which
is the honest description of what any of these systems provides.

The cost is that the key must be deterministic, so it is built from stable
inputs rather than a random id, and the same logical action must be built the
same way on a retry - which is another argument for the fold being
deterministic.

## Alternatives considered

At-most-once (silent message loss, unacceptable for escalations),
exactly-once (not achievable without distributed transactions), or a
deduplication window in the provider (crude, and it does not help with
in-process retries).
