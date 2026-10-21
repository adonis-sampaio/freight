# ADR 012: Database-backed timers, scanned by a cron worker

* **Status:** accepted
* **Slug:** `database-backed-timers`

## Context

The agent's escalation ladder is a sequence of waits. Those waits
have to survive a deploy, be visible to a human who asks "what is scheduled
for this load?", and be cancellable when the driver finally answers at 07:13
instead of 07:31. A queue with delayed messages can do the first, but not the
second.

## Decision

A timer is a row: a load, a request key, a fire time, and the
action to take when it fires. A background worker scans for due timers once a
minute, fires them, and marks them done. A timer is state, not a message in
a queue, so "what is scheduled?" is a query and "cancel it" is a delete.

This also makes the ladder's timing inspectable, which is what makes the
assessment's timeline reproducible in a test rather than in a demo.

## Consequences

Timers survive restarts and are queryable and cancellable. Firing is
idempotent, because the scan is a query over due rows and firing marks them.
The cost is a polling worker, up to a minute of delay, and a table to
maintain.

## Alternatives considered

Celery ETA tasks (opaque, awkward to inspect, zombie-task
management), an in-process `asyncio` timer (lost on restart), or a
per-message sleep (ties up a worker and cannot be cancelled).
