# ADR 002: Hybrid: a deterministic policy engine with an LLM fallback agent

* **Status:** accepted
* **Slug:** `hybrid-policy-engine-with-llm-fallback`

## Context

The assessment is explicit that the team does not know every situation
before it occurs, so a pure rules engine cannot ship. It also sets a five
minute response budget and a $1 per load budget, and asks for an agent that
"does some tasks alone and shows what it did". A pure ReAct agent meets the
first requirement and misses the other two, because a model that counts
attempts, remembers what it already asked, and decides to stay silent fails
often enough to be operationally useless in a live freight operation.

## Decision

Two components with a clear boundary. The policy engine executes SOP
procedures that have been written down, reviewed, and compiled into steps; it
decides by evaluating predicates over the load's state. The fallback agent
handles everything the engine does not recognise, and it is deliberately
limited: it may choose a template and a target, never write its own message,
and it may open a Hero task, never contact a driver on its own judgement.

The boundary is observable. Every action in the ledger records which component
produced it, so the coverage of the written procedures is a number we can
report and improve.

## Consequences

The system can be trusted with a live load today, because the part that
talks to drivers is reviewed, deterministic and auditable. Novel situations
are still handled rather than dropped, and every one of them leaves a trace
that can become a procedure. The cost is two components to build and a seam to
maintain, and the fallback agent's quality depends on how good the template
catalogue is.

The temptation this ADR guards against is letting the fallback agent's
capability grow until it is doing the work of the engine, one exception at a
time. That is why it is template-only.

## Alternatives considered

A pure ReAct agent (too slow, too expensive, too unreliable on counters
and on "do nothing"), or a pure rules engine (cannot handle novelty, and the
assessment would be answered with a lookup table).
