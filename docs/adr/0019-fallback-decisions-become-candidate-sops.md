# ADR 019: Fallback decisions are captured as candidate procedures

* **Status:** accepted
* **Slug:** `fallback-decisions-become-candidate-sops`

## Context

The fallback agent exists because the written procedures do not cover
everything. If its decisions vanish into a log, the coverage gap stays open
forever and the fallback agent's share of traffic never shrinks. If it is
allowed to write to the live procedure set, the review process is gone.

## Decision

Every fallback decision is recorded with the situation that produced
it, the template it chose, and the load it happened on. The recurring
situations become a review queue for the procedure editors, who write a
proper procedure; the new procedure then takes over that traffic, and the
fallback rate becomes a number the team works to reduce.

This is the mechanism that makes the system get better without anyone
re-engineering it: the gap is visible, prioritised by frequency, and closes
through the ordinary editing workflow.

## Consequences

The fallback agent's cost and its share of the traffic both decline
over time, and the improvement is driven by real traffic rather than by
guesswork. The cost is a piece of process, and the discipline to actually
work the queue.

The alternative - letting the fallback agent write procedures itself - is
explicitly rejected: an unreviewed rule that reaches a driver is not a
feature, it is an incident waiting for a specific load.

## Alternatives considered

Letting the fallback agent write to the live procedure set
(dangerous, unauditable), or logging the gaps with no workflow to close them
(the gap never closes).
