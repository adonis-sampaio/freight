# ADR 017: Deploy to Render: web service, background worker, cron job, Postgres

* **Status:** accepted
* **Slug:** `render-topology`

## Context

The assessment names AWS as optional and suggests a deployment that
demonstrates the operational shape. The system's shape - an ingest API, a
background worker that processes events, a periodic timer scan, and a
database - maps onto Render's documented primitives.

The stores are in-memory (`persistence/memory.py`), so they belong to a
process. The timers the API arms are visible only to a worker that shares
its memory: a worker in a second container starts with an empty timer store
and the escalation ladder stops after the first rung.

## Decision

A Render blueprint (`render.yaml`) defines a web service for the ingest API,
with the timer worker running on a thread of that same process. One command
creates the whole topology.

The blueprint is in the repository and is the deployment documentation: it is
readable, versioned, and diffable, which a dashboard configuration is not.

When the Postgres stores land (`docs/PROPOSAL.md` §16), the blueprint grows a
background worker for the timer scan, a cron job as a safety net, a Postgres
instance and a key-value store for the budget counters - the topology this
ADR originally described, and kept in `render.yaml` as a comment until then.
Render Key Value instances are declared under `services`, not `databases`;
the `databases` list is for Render Postgres only.

## Consequences

The deployment is reproducible in one step and the topology is visible in
review. Two limits come from the in-memory stores: the worker cannot be
isolated from the ingest path until Postgres exists, and the state does not
outlive the container - a restart, a redeploy or a spin-down loses the event
log, so the blueprint asks for a paid plan rather than the free one.

## Alternatives considered

AWS (more moving parts than the assessment requires), a single Docker process
(the worker would be blocked by a slow request - which is why the worker is
on a thread rather than in the request path), a hand-managed VPS (no
reproducible topology), and a separate worker service now (a worker that
cannot see the timers does nothing, which is worse than no worker because it
looks like it is working).
