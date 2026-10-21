# ADR 004: Outbound messages are templates, not model-written prose

* **Status:** accepted
* **Slug:** `outbound-messages-are-templates`

## Context

A driver asking for an ETA needs a short, correct message with the
load's actual stop name in it. The words are formulaic. A model that writes
them adds cost, latency, tone drift, and a compliance problem, in exchange for
nothing a freight dispatcher would miss. The audit requirement also argues
for it: the reviewer must be able to see exactly what was sent.

## Decision

Every outbound message is rendered from a Markdown template with
explicit placeholders. Templates live next to the procedures that use them
and can be overridden per client, so a client can change the wording without
touching the logic. A template that needs a value the load does not have is
not sent at all: a message with a hole in it is worse than no message, and the
missing value is exactly what a human should look at.

## Consequences

Cost per message falls to zero. Tone is consistent and reviewable.
The sent text is knowable before it is sent, which is what makes the eval
harness able to assert on it. The fallback agent gets its variety from
choosing among templates rather than from inventing sentences, which keeps
its output inside the same review process.

The limit is obvious: a template cannot improvise. The answer is a template
catalogue, and a process for growing it from what the fallback agent found
missing.

## Alternatives considered

Free-form LLM drafting for every message (roughly 10x the cost, no
stable tone, not auditable), or human-written per load (does not scale).
