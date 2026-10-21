# ADR 003: Event-sourced load state; the state is a fold over the log

* **Status:** accepted
* **Slug:** `event-sourced-state-as-a-fold`

## Context

The assessment asks the agent to remember past actions and messages
across a load that lives for two weeks. The obvious implementation is a table
of mutable columns per load, updated in place. That works until the first
question of "why did the agent do that?" or "what did it know at 07:12?", and
those are the questions the whole exercise is about. It also makes every
non-trivial bug a state-reconciliation bug, and it makes replay - the thing
that makes evaluation possible - impossible without a separate code path.

## Decision

Every input and every decision is an immutable event appended to a
per-load log. The current state is `fold(apply, events, empty)`, a pure
function from a list of events to a `LoadState`. Nothing writes to the state
directly; the only way to change the state is to append an event that implies
the change.

The consequences are worth stating plainly: a load can be replayed exactly,
the "why" of every action is answerable by replaying to the moment before it,
and two events processed in a different order produce the same state, because
the fold is commutative over independent updates.

## Consequences

Replay becomes a feature rather than a debugging technique, and the
evaluation harness can rebuild a load's memory from nothing but the event
stream. The audit trail is the primary artefact rather than a by-product.

The costs: the event log grows without bound and needs compaction; the fold
must be deterministic; and the storage layer is more complex than a mutable
table. The in-memory implementation in this repository is the simplest
possible version of that layer, and the protocol is small enough that a real
database is a drop-in.

## Alternatives considered

A mutable state table (drift, no replay, harder debugging), or keeping
the conversation in the prompt (unbounded cost, no structured queries).
