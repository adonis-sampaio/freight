# Architecture decision records

Every decision that shapes this system has its own file in `docs/adr/`, written
in the standard Context / Decision / Consequences / Alternatives format. The
index below is the summary; the files are the record. A decision that is later
reversed gets a new ADR that supersedes the old one, rather than an edit.

The full rationale, including the rejected alternatives, is in `docs/PROPOSAL.md`.

| # | Decision | ADR |
| --- | --- | --- |
| 001 | Record architectural decisions as ADRs | [`0001-record-decisions-as-adrs.md`](adr/0001-record-decisions-as-adrs.md) |
| 002 | Hybrid: a deterministic policy engine with an LLM fallback agent | [`0002-hybrid-policy-engine-with-llm-fallback.md`](adr/0002-hybrid-policy-engine-with-llm-fallback.md) |
| 003 | Event-sourced load state; the state is a fold over the log | [`0003-event-sourced-state-as-a-fold.md`](adr/0003-event-sourced-state-as-a-fold.md) |
| 004 | Outbound messages are templates, not model-written prose | [`0004-outbound-messages-are-templates.md`](adr/0004-outbound-messages-are-templates.md) |
| 005 | The LLM is a classifier behind typed gates, not the decision maker | [`0005-llm-as-gate-classifier.md`](adr/0005-llm-as-gate-classifier.md) |
| 006 | Layered SOP resolution: base, then client, then client and load type | [`0006-layered-sop-resolution.md`](adr/0006-layered-sop-resolution.md) |
| 007 | SOP files are Markdown with front matter and a fenced policy block | [`0007-sop-files-are-markdown-with-a-policy-block.md`](adr/0007-sop-files-are-markdown-with-a-policy-block.md) |
| 008 | Retrieval: metadata filter, then BM25, then embedding rerank | [`0008-metadata-filter-then-bm25-then-embedding.md`](adr/0008-metadata-filter-then-bm25-then-embedding.md) |
| 009 | Model tiering with a hard per-load budget guard | [`0009-model-tiering-with-a-budget-guard.md`](adr/0009-model-tiering-with-a-budget-guard.md) |
| 010 | Prompt caching on the stable prefix | [`0010-prompt-caching-on-the-stable-prefix.md`](adr/0010-prompt-caching-on-the-stable-prefix.md) |
| 011 | Long-thread compaction: recent messages verbatim, older ones summarised | [`0011-long-thread-compaction.md`](adr/0011-long-thread-compaction.md) |
| 012 | Database-backed timers, scanned by a cron worker | [`0012-database-backed-timers.md`](adr/0012-database-backed-timers.md) |
| 013 | At-least-once execution with an idempotency key per action | [`0013-at-least-once-with-an-idempotency-key.md`](adr/0013-at-least-once-with-an-idempotency-key.md) |
| 014 | Adapters are the only things that talk to the outside world | [`0014-adapters-own-the-outside-world.md`](adr/0014-adapters-own-the-outside-world.md) |
| 015 | Mock integrations behind a stable interface | [`0015-mock-integrations-behind-a-stable-interface.md`](adr/0015-mock-integrations-behind-a-stable-interface.md) |
| 016 | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Postgres | [`0016-python-fastapi-pydantic-stack.md`](adr/0016-python-fastapi-pydantic-stack.md) |
| 017 | Deploy to Render: web service, background worker, cron job, Postgres | [`0017-render-topology.md`](adr/0017-render-topology.md) |
| 018 | The OpenAI Responses API with strict JSON schema outputs | [`0018-responses-api-with-structured-outputs.md`](adr/0018-responses-api-with-structured-outputs.md) |
| 019 | Fallback decisions are captured as candidate procedures | [`0019-fallback-decisions-become-candidate-sops.md`](adr/0019-fallback-decisions-become-candidate-sops.md) |
| 020 | Every action stores its rationale | [`0020-every-action-stores-its-rationale.md`](adr/0020-every-action-stores-its-rationale.md) |
