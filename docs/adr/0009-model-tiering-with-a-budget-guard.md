# ADR 009: Model tiering with a hard per-load budget guard

* **Status:** accepted
* **Slug:** `model-tiering-with-a-budget-guard`

## Context

The assessment sets $1 per load. A single frontier model on every
event would cost more than that on the loads that generate many events, and a
single small model would be unreliable on the situations that are hard by
definition. Choosing one model for both is choosing to be either too expensive
or not good enough.

## Decision

Three tiers, chosen per call by the difficulty of the job: a fast
tier for classification, a balanced tier for the fallback agent, a frontier
tier for genuinely novel situations. A hard budget guard sits in front of the
gateway: once a load has spent its budget, no further model calls happen on
that load and the fallback is the deterministic, template-only path.

The projected cost with the fast tier doing the work is about $0.07 per load,
roughly a fifteenth of the budget. The budget is a guardrail, not a target.

## Consequences

Cost is a tenth of what the assessment allows, with a capability path
for the hard cases. The budget cannot be exceeded by accident, because the
guard is checked before the call.

The cost is a tiering decision to get wrong: a gate that is too hard gets the
cheap model and fails, and a gate that is too easy gets the expensive model
and wastes money. The mitigation is that gates are narrow, and the tier
choice is visible in the ledger.

## Alternatives considered

One flagship model for everything (over budget), one small model for
everything (falls apart on novelty), no budget guard (the bill arrives with
the invoice).
