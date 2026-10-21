# ADR 011: Long-thread compaction: recent messages verbatim, older ones summarised

* **Status:** accepted
* **Slug:** `long-thread-compaction`

## Context

A load lives for about two weeks and can accumulate fifty to a
hundred messages. Sending the whole history on every event makes the cost
grow with the age of the load, and the latency budget does not allow it.

## Decision

The context window is the last N messages verbatim, plus a rolling
summary of everything before them, plus the structured state extracted from
the event log. The structured state is the important part: the facts that
matter for a decision - attempts, open requests, delay risk - are already in
the fold, so the model does not have to re-read the history to count them.

## Consequences

Cost and latency stay flat over the life of a load. The model still
sees the recent conversation in full, and the decisions that depend on the
distant past depend on it through the structured state instead of through
prose.

The cost is a summary that can be wrong, and a summarisation step that is
itself a model call. The summary is therefore advisory: the fold is
authoritative.

## Alternatives considered

Sending the full history every time (cost and latency grow with load
age), or dropping history entirely (the agent forgets and repeats itself).
