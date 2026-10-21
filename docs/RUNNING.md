# Running the agent

Everything below works with no API key, no database and no network.

## Local development

```bash
uv venv
uv pip install -e ".[dev]"
```

Or with plain pip:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

### The commands

```bash
freight demo                              # replay the assessment's situation
freight eval                              # run the seven evaluation scenarios
freight validate                          # check the procedure corpus
freight sop client_b --load-type refrigerated
freight event '{"load_id": "481207", "type": "sms", "occurred_at": "2026-10-13T07:12:00",
                "body": "What time will you arrive?", "source_role": "driver"}'
```

The same things through the Makefile: `make demo`, `make eval`,
`make eval-live`, `make validate`, `make sop CLIENT=client_b`, `make test`,
`make check` (lint, typecheck, test), `make api`, `make worker`.

`freight demo` and `freight eval` use the fake model, so they are
deterministic and free. Add `--real-llm` to talk to OpenAI - that needs
`OPENAI_API_KEY`, and the two commands then cost a fraction of a cent.

### The tests

```bash
pytest -q                 # 69 tests, about 15 seconds
pytest -q tests/test_evals.py
pytest -q -k "not llm"    # the suite never calls the network
```

The suite is the same code path as production: the fake model implements the
OpenAI Responses contract, the fake adapter implements the integration
protocol, and the assertions are made against the action ledger - what the
agent did, and why.

### Running without a model

The deterministic path needs no API key. Without one, the escalation ladder
still works - the delay-risk procedure has no gate, so it sends the SMS, arms
the timer and escalates on time. What stops working is the classification:
the steps that need to understand a driver's message cannot run, and they are
recorded as skipped with the reason "the gate could not be evaluated, so the
step was not run". The agent does not guess.

### The API

```bash
uvicorn freight_agent.api.app:app --reload --port 8000
```

| Endpoint | What it does |
| --- | --- |
| `GET /healthz` | liveness |
| `GET /readyz` | readiness |
| `POST /loads` | register a load's metadata |
| `POST /webhooks/{provider}` | ingest an event (`twilio`, `sendgrid`, `slack`, `tms`) |
| `GET /loads/{load_id}` | the folded state: stage, delay risk, open requests |
| `GET /loads/{load_id}/events` | the event log |
| `GET /loads/{load_id}/actions` | the audit trail: what was sent, and why |
| `GET /sops?client=client_b` | the procedures that apply to a client |

A webhook is a JSON body with the event's fields. The provider's `id` becomes
`provider_event_id`, which is the deduplication key, so a redelivered webhook
is ignored.

```bash
curl -s localhost:8000/loads/481207 | jq
curl -s localhost:8000/loads/481207/actions | jq '.[].rationale'
```

If `WEBHOOK_SECRET` is set to something other than `change-me`, the endpoint
requires an `X-Signature` header holding the HMAC-SHA256 of the raw body.

### The worker

The worker fires the timers - the escalation ladder's waits.

```bash
python -m freight_agent.workers.timer_worker              # every 30 seconds
python -m freight_agent.workers.timer_worker --once       # a single scan
```

The API also runs the worker, on a thread of its own process, unless
`TIMER_WORKER_ENABLED=false`. That is not a convenience: the stores are
in-memory, so they belong to a process. A worker in a second process - a
second container, a second Render service - starts with an empty timer store,
never sees the timers the API armed, and the escalation ladder stops after
the first rung. Run `make api` on its own and the ladder advances.

The `--once` mode is what a scheduled job would run, once a minute, as a
safety net next to the long-running worker. It only makes sense once the
stores are shared between processes.

## Configuration

Settings come from the environment, or from a `.env` file in the working
directory. `.env.example` lists everything.

| Variable | Default | Meaning |
| --- | --- | --- |
| `OPENAI_API_KEY` | - | without it, the LLM layer is off and the deterministic path still works |
| `LLM_ENABLED` | `true` | turn the model layer off entirely |
| `LLM_TIER_FAST_MODEL` | `gpt-6-luna` | gates |
| `LLM_TIER_BALANCED_MODEL` | `gpt-6.1-sol` | the fallback agent |
| `LLM_TIER_FRONTIER_MODEL` | `gpt-6-astra` | novel situations |
| `SOP_DIR` | the packaged corpus | where the procedures live |
| `AGENT_REACTION_SECONDS` | `60` | how long the agent takes to react to an inbound message |
| `RUN_DEADLINE_SECONDS` | `240` | a run stops calling the model after this long |
| `PER_LOAD_BUDGET_USD` | `0.50` | the model's budget per load |
| `INTEGRATIONS_MODE` | `mock` | `mock` records instead of sending |
| `WEBHOOK_SECRET` | `change-me` | set it, and the webhook requires a signature |
| `TIMER_WORKER_ENABLED` | `true` | run the timer worker inside the API process |
| `TIMER_WORKER_POLL_SECONDS` | `30` | how often that worker scans for due timers |
| `DATABASE_URL` | `sqlite:///./freight.db` | for the Postgres implementation |
| `REDIS_URL` | `redis://localhost:6379/0` | for the budget counters and the queue |

The two that change the agent's behaviour rather than its infrastructure are
`AGENT_REACTION_SECONDS` and `PER_LOAD_BUDGET_USD`. Setting the reaction to
zero makes the agent answer immediately; setting it to 60 reproduces the
assessment's timeline (07:01, 07:13, 07:31, 08:01).

## Deployment

### Render

Push the repository to GitHub, then launch the blueprint:

```bash
render blueprint launch
```

| Service | Kind | What it runs |
| --- | --- | --- |
| `freight-agent-api` | web | the ingest API and, on a thread of the same process, the timer scan |

The blueprint is one service, not three, because the stores are in-memory.
`render.yaml` carries the three-service topology in a comment, ready for the
day the Postgres stores land.

Set `OPENAI_API_KEY` when the blueprint asks for it. Render generates
`WEBHOOK_SECRET` for you.

Two things to know before you send it real traffic:

* **The state is in the container.** The event log, the action ledger and the
  open requests live in the process's memory. A restart, a redeploy or a
  spin-down loses them. The free plan spins down after fifteen minutes of
  inactivity, which is why the blueprint asks for a paid one.
* **Nothing is actually sent.** `INTEGRATIONS_MODE=mock` records what would
  have gone out. A real Twilio, Slack or TMS adapter implements the same
  protocol (`integrations/base.py`) and is not written yet.

### Docker

```bash
docker build -t freight-agent .
docker run --rm -p 8000:8000 freight-agent
```

The image runs the API, with the timer worker on a thread of the same
process. For a worker on its own - which only makes sense with shared
stores:

```bash
docker run --rm freight-agent python -m freight_agent.workers.timer_worker
```

### Procfile

`Procfile` declares the two processes, for a host that reads it:

```
web: uvicorn freight_agent.api.app:app --host 0.0.0.0 --port ${PORT:-8000}
worker: python -m freight_agent.workers.timer_worker
```

## Operating it

### What to look at

```bash
# What did the agent do on this load, and why?
curl -s localhost:8000/loads/481207/actions | jq '.[] | {action_type, policy_key, step_id, rationale}'

# What is the agent's memory of this load right now?
curl -s localhost:8000/loads/481207 | jq '.open_requests'

# What is scheduled?
```

The action ledger is the primary operational surface. Every row says which
procedure and step produced it, which predicate matched, what the gate said,
and what was sent.

### When the agent does something surprising

1. Look at the action's `policy_key` and `step_id`. That is the procedure
   that fired.
2. Read that procedure in `src/freight_agent/sops/`. The prose at the top
   says what it is for.
3. If the predicate matched but the message was wrong, the fix is in the
   procedure. If no procedure matched, the fallback agent handled it, and
   that is a candidate for a new procedure (ADR-0019).

### Cost

Every model call is recorded with its model, tokens and cost. The projected
cost is about $0.07 per load against the $1 budget. The guard that enforces
it is `PER_LOAD_BUDGET_USD`: once a load has spent it, the model is not
called again for that load.

### The fallback rate

A fallback decision means no procedure covered the event. It is a coverage
metric, not an error: the recurring ones become new procedures. The fallback
agent's decisions are recorded with the situation that produced them, which
is the work queue for whoever writes procedures.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `LlmUnavailable` in the log | no `OPENAI_API_KEY` | expected: the deterministic path does not need the model. Set the key to enable the gates |
| The agent answers nothing | no procedure matched, and the fallback agent had no budget | check `PER_LOAD_BUDGET_USD`, and check the action ledger for a `fallback` decision |
| The driver got the same message twice | two different events produced the same text | the idempotency key includes the event id, so this is two genuine events. Check the event log |
| `freight validate` fails | a condition, action or template the engine does not know | the message names the field and the file. The authoring guide lists the vocabulary |
| A step never fires | its `when` never matched, or its gate never passed | run `freight sop <client>` to see the resolved procedure, and check the `gate` output in the ledger |
| The timers never fire | the worker is not running | the API runs it on a thread: check `TIMER_WORKER_ENABLED`. A worker in another process cannot see the API's timers - that is what the in-memory stores mean |

## What the mocks hide

The default `INTEGRATIONS_MODE=mock` records what would have been sent
instead of sending it. That is what makes the demo and the evaluation suite
runnable offline, and it is also the limit: a real Twilio, Slack or TMS
adapter implements the same protocol
(`integrations/base.py`), and the contract test that the mock passes is the
test the real adapter has to pass too.

The same is true of storage: the in-memory stores implement the protocols in
`persistence/protocols.py`, and the Postgres implementation is the production
work item called out in `docs/PROPOSAL.md` §16.

Storage is also the limit on the deployment's shape. The in-memory stores
belong to a process, so one process has to own the API and the timer scan.
That is why the blueprint is one service, and why the state is gone when the
container restarts. Postgres moves both problems at once: the worker becomes
its own service, and the event log outlives the container.
