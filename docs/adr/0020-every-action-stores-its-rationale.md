# ADR 020: Every action stores its rationale

* **Status:** accepted
* **Slug:** `every-action-stores-its-rationale`

## Context

The assessment requires the agent to show what it did. It also
requires an evaluation harness that can assert on behaviour, and on
*why* - two runs that send the same message for different reasons are
different outcomes, and only the rationale tells them apart.

## Decision

Each recorded action carries the procedure key and step id that
produced it, the predicates that matched, the model's gate output when a
gate was involved, the template that was rendered, and the resulting message.
The eval harness asserts on this record rather than on a side effect, and
the UI can show the same record to a human.

Because the rationale is stored rather than logged, it is queryable, and the
question "why did this load get a Slack alert" has an answer that is a row,
not a log line to be grepped.

## Consequences

The audit trail is a first-class artefact and the eval harness can
assert on reasoning. Debugging a misbehaving load is a lookup. The cost is
storage, and the discipline to fill the fields in - which the code does by
construction, because the record is built at the point of the decision.

## Alternatives considered

Log lines only (not queryable, not assertable), or no audit trail at
all (the assessment's central requirement unmet).
