# ADR 016: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Postgres

* **Status:** accepted
* **Slug:** `python-fastapi-pydantic-stack`

## Context

The work is dominated by structured model output, typed settings and
a webhook surface. Those are exactly the strengths of the Python data stack,
and the OpenAI SDK's structured-output support is the best of the available
options.

## Decision

Python 3.12+ with FastAPI for ingest, Pydantic v2 for every boundary
(the model schemas, the event envelope, the settings), SQLAlchemy 2 with
Postgres for storage, and Redis where a queue is needed. Strict typing
throughout, with mypy in CI.

The event envelope, the model schemas and the settings are all validated by
the same library, which means one set of rules for "is this input sane".

## Consequences

Strong typed schemas for structured outputs, a mature ecosystem for
webhooks and background work, and a deployment story that matches Render's
documented stack. The cost is runtime performance compared with Go, which
does not matter at this volume.

## Alternatives considered

TypeScript (decent, but weaker structured-output and eval
ergonomics), Go (faster, but slower to iterate on an evaluation harness), or
a pure-LLM workflow framework (opaque control flow, harder to test).
