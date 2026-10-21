# ADR 005: The LLM is a classifier behind typed gates, not the decision maker

* **Status:** accepted
* **Slug:** `llm-as-gate-classifier`

## Context

The rules that actually matter in a live operation - "we already
asked twice, so escalate", "the driver just acknowledged, so stay silent" -
are counters and predicates. A model asked to honour them in prose will
eventually not: it loses count, it re-asks a driver it just asked, it replies
to a message that did not need replying to. At the volume this system is
designed for, that is a real incident rate, not a theoretical one.

## Decision

The model is used for the narrow jobs it is good at: reading a driver
message and deciding whether it contains an ETA, whether it is a question, and
which fact it is asking about. The result is a small JSON object validated
against a strict schema, cached per event, and consumed by the policy engine
as a boolean. The decision to send, and the counter that tracks it, live in
code.

Gates are the only place the model touches the hot path, and they are the
cheapest possible calls: a short prompt, a narrow schema, a fast tier.

## Consequences

The escalation ladder becomes a counter that cannot drift. Gate
behaviour is testable in isolation, and a gate that is wrong is wrong in one
place. The cost per load drops by an order of magnitude, because a gate call
costs a fraction of a cent and a full agent run costs cents.

The cost is that gates need to be defined, and a procedure that needs
judgement no gate can express has to be written as code, or handled by the
fallback agent.

## Alternatives considered

Letting the model count attempts from the conversation history
(the reliability problem above), or deciding to send at all (an unnecessary
risk given that the cost of a wrong message is a phone call to a driver).
