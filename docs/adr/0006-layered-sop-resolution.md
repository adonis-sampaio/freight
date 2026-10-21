# ADR 006: Layered SOP resolution: base, then client, then client and load type

* **Status:** accepted
* **Slug:** `layered-sop-resolution`

## Context

The assessment describes a procedure set that is 60-70% shared, with
per-client and per-load-type variations. A per-client copy of the whole
procedure set diverges within two quarters, and the divergences are invisible
until they matter. A single merged document per client is equally bad: the
shared part is duplicated N times and the diff between clients is unreadable.

## Decision

The corpus is stored in layers, and a client's file contains only the
steps it changes. The resolver merges the layers by `policy_key`, and within a
layer it merges by step id: a step with a known id replaces the step it
names, `disable: true` removes it, `merge_into:` merges fields into it. The
result is a resolved procedure that records, per step, which file it came
from.

Because the merge is by step and not by file, a client can change one clause
of one step and inherit the rest. Because the resolved procedure keeps its
provenance, "why does Client B get a Slack alert instead of an email" is
answered by reading two files.

## Consequences

The shared procedure is written once. A client's variation is a
twenty-line file a customer success manager can review. The cost of a change
to the base procedure falls to every client that did not override the step,
and the cost of a client's change falls to nobody else.

The cost is a merge semantics that has to be specified, and a validator that
has to check that overrides refer to steps that exist. Both are implemented.

## Alternatives considered

Copy-and-edit a full procedure per client (diverges, unmaintainable);
one giant merged document per client (expensive to retrieve, unreadable
diffs); storing variations as rules in code (only developers can change
client behaviour).
