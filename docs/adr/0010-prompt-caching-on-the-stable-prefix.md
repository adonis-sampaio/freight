# ADR 010: Prompt caching on the stable prefix

* **Status:** accepted
* **Slug:** `prompt-caching-on-the-stable-prefix`

## Context

Every run for a given load resends the same system instructions, the
same procedure excerpt and the same load context. Paying full price for
identical tokens on every event is the single largest avoidable cost in the
design.

## Decision

The stable prefix is ordered so it can be cached: the system
instructions, then the procedure excerpt, then the load context, and only then
the volatile part (the new event). The gateway sends the stable prefix first
and the volatile part last, so the provider can reuse the cached prefix.

The saving is an order of magnitude on the input side - cached input is a
tenth of the price of fresh input on the fast tier - and the saving applies
to every event of every load.

## Consequences

Input cost drops to near zero for repeat events on the same load. The
latency of a cached prefix is lower as well.

The cost is an ordering constraint that the prompt builder has to respect,
and a dependency on provider-side cache behaviour that we can observe but not
control.

## Alternatives considered

No caching (paying full price for identical context), or a short
context that avoids the problem by making the agent forget (the opposite of
what the assessment asks for).
