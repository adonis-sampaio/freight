# Architecture

This document describes how the agent works. The *why* is in
[`PROPOSAL.md`](PROPOSAL.md) and the twenty decisions are in
[`ADRs.md`](ADRs.md).

## 1. The shape of the system

```
  SMS webhook ─┐
  email ───────┤
  location ────┼──▶ ┌──────────────┐
  timer scan ──┘    │  ingest API  │  FastAPI, validates the envelope,
                     └──────┬───────┘  verifies the provider signature
                            │
                            ▼
                     ┌──────────────┐
                     │   runtime    │  dedupe, fold, decide, execute
                     └──────┬───────┘
                            │        the only place that talks to the
              ┌─────────────┼──────────────┐  outside world
              ▼             ▼              ▼
       ┌────────────┐ ┌───────────┐ ┌───────────┐
       │ policy     │ │  fallback │ │  action   │
       │ engine     │ │  agent    │ │  ledger   │  audit trail
       └─────┬──────┘ └─────┬─────┘ └─────┬─────┘
             │              │             │
             ▼              ▼             │
       ┌──────────┐   ┌──────────┐       │
       │  gates   │   │  model   │       │  classifies a driver message
       │ (LLM)    │   │  gateway │       │  only, never decides
       └─────┬────┘   └────┬─────┘       │
             │             │              │
             ▼             ▼              ▼
       ┌─────────────────────────────────────┐
       │  SOP corpus (Markdown + policy)     │  base → client → client+load type
       └─────────────────────────────────────┘

       ┌─────────────────────────────────────┐
       │  adapters: SMS, email, Slack, TMS   │  the only side effects
       └─────────────────────────────────────┘

       ┌─────────────────────────────────────┐
       │  event log (append only)             │  the state is a fold over this
       └─────────────────────────────────────┘
```

Two rules make the picture simpler than it looks:

* **The engine decides, the adapters deliver.** Nothing in the engine performs
  a side effect. It produces an `Action`; an adapter sends it.
* **The model classifies, it does not decide.** The only model call on the hot
  path is a gate: a small JSON object that answers "does this message contain
  an ETA?". Whether to send a message is decided by code.

## 2. The run loop

An event arrives. The runtime does five things, in this order.

```
1. dedupe        has this provider_event_id been seen for this load?
2. fold          state = fold(apply, events + [this event], empty)
3. match         which procedures apply to this load, in this stage, for this event?
4. gate          for each candidate step with a gate, ask the model (cached per event)
5. decide        evaluate the step's predicates against the state, build the action,
                 check the guardrails, append the events
```

The order matters. Dedupe comes first because a redelivered webhook must not
count as a second attempt. The fold comes before matching because a procedure
may depend on the state the event itself produced - a driver message that says
"the gate code is 1234" changes the facts, and the procedure that answers
questions about the gate code must see the new facts. Gating comes before
deciding because the gate output is an input to the predicates.

The result of a run is a list of `Decision`s, each one carrying the action, the
procedure and step it came from, and the reason. The action ledger is
append-only, and a second attempt with the same idempotency key is suppressed
before the adapter is called.

## 3. State is a fold over the event log

```python
def state_after(events: list[Event]) -> LoadState:
    state = LoadState.empty()
    for event in events:
        state = apply_event(state, event)
    return state
```

`apply_event` is pure: the same event list always produces the same state.
That gives three things for free.

* **Replay.** Rebuilding a load's memory from its event stream answers "what
  did the agent know at 07:12?".
* **Audit.** The rationale of a decision is the state immediately before it.
* **Tests.** The evaluation harness builds a load from a list of events and
  asserts on the result, with no fixture files and no mocking of the state.

The state carries what a procedure needs to decide: the delay risk, the
stage, the facts extracted from the load metadata, the open requests (with
their attempt counts and when they were last asked), and the answers we have
received.

### Open requests are the heart of it

An *open request* is a promise to come back: "we asked the driver for an ETA
and have not heard yet". It has a key, a status, a count of attempts, and the
time of the last ask. The escalation ladder is then a pure function of the
request's attempt count, and the attempt count is incremented by an event, not
by a model.

The rule that keeps it honest: a request is closed only when a gate
*positively* detects the answer. Silence, a change of subject, or an
unrelated question does not close it. This is why the driver who replies
"ok" at 07:13 does not stop the ladder, and why an ETA that arrives as a
lone number in an unrelated message does not either.

## 4. The SOP corpus

A procedure is a Markdown file with three parts:

```markdown
---
policy_key: delay_risk.high
scope: base
stages: [to_pickup, to_delivery]
---

What to do when the delay risk becomes high.

The driver has not given us an ETA. We ask once, wait 30 minutes, ask again,
and then escalate to the dispatcher and to the Hero team.

```policy
- id: ask_driver_first
  when: {delay_risk_changed: high, no_open_request: eta}
  do: {action: send_sms, to_role: driver, template: ask_eta}
  effect: {open_request: {key: eta, kind: eta, addressed_to_role: driver, attempts: 1}}
```
```

Resolution is layered:

```
base/delay-risk-high.md
  + clients/client_b/delay-risk-high.md        (replaces a step by id)
  + clients/client_b/load_types/refrigerated/… (replaces a step by id)
  = the procedure that runs for this load
```

A client override names the step it changes:

```yaml
- id: escalate_to_dispatcher_and_hero
  do: {action: send_slack, to_channel: broker, template: broker_delay_alert}
```

Because the merge is by step id and not by file, a client changes one clause
and inherits everything else, and the resolved procedure records which file
each step came from.

The prose is not decoration. It is what the fallback agent reads when no
procedure matches, and it is what a new starter reads to understand why the
agent behaves as it does.

Writing procedures is documented for non-engineers in
[`../src/freight_agent/sops/schema/sop-authoring-guide.md`](../src/freight_agent/sops/schema/sop-authoring-guide.md).

## 5. Gates: where the model is used

A gate is a small classifier with a strict schema:

```json
{
  "is_question": true,
  "has_eta": false,
  "kind": "question",
  "topic": "po_number",
  "confidence": 0.94
}
```

A step may require the gate output to satisfy a condition:

```yaml
gate:
  name: message_signals
  condition: $gate.is_question and $gate.topic_fact_present
```

The conditions are closed and small: `has_eta`, `is_question`,
`kind == '…'`, `topic_fact_present`, `topic_fact_missing`, composed with
`and` / `or`. If the model cannot answer, the step does not run. The agent
never guesses.

The gate is cached per event, so a load with four candidate steps pays for one
gate call, not four.

## 6. The fallback agent

When no procedure matches, the fallback agent takes over - under strict
constraints:

* it may choose a **template**, never write a message;
* it may choose a **target** from the load's known contacts;
* it may open a **Hero task** when it is not confident;
* it may send at most **one** outbound message per event;
* it never contacts a driver with anything that is not a reviewed template.

Its decisions are recorded with the situation that produced them, so the
recurring ones become a work queue for the procedure editors
(ADR 0019). The fallback rate is the coverage metric for the corpus.

## 7. The LLM gateway

One place that talks to OpenAI, with:

* **tiering** - a fast tier for gates, a balanced tier for the fallback agent,
  a frontier tier for genuinely novel situations;
* **a budget guard** - once a load has spent `per_load_budget_usd`, no further
  model calls happen on that load;
* **a deadline** - a run that has taken `run_deadline_seconds` stops calling
  the model and finishes on the deterministic path;
* **caching** - the stable prefix of the prompt is ordered for provider-side
  prompt caching;
* **accounting** - every call records its model, tokens, purpose and cost.

The gateway is behind a protocol, so the evaluation harness can substitute a
fake model. The fake model implements the same structured-output contract,
which is why the tests exercise the same shape as production.

## 8. Cost model

OpenAI list prices used (per million tokens, October 2026):

| Tier | Model | In | Cached in | Out |
| --- | --- | --- | --- | --- |
| Fast | `gpt-6-luna` | $0.10 | $0.01 | $0.50 |
| Balanced | `gpt-6.1-sol` | $2.00 | $0.10 | $10.00 |
| Frontier | `gpt-6-astra` | $10.00 | $1.00 | $50.00 |

A typical load generates three gate calls and no fallback call:

```
3 gate calls ≈ 6,000 input tokens (mostly cached) + 400 output tokens
             ≈ 6,000 × $0.01 + 400 × $0.50 / 1,000,000
             ≈ $0.0003 per load
```

With a fallback call on one load in ten, and the balanced tier, the projection
is **≈ $0.07 per load** against the assessment's **$1.00** budget - roughly a
fifteenth of the allowance.

The levers, in order of impact: the fast tier (10-100x), prompt caching (10x
on input), not sending messages (the model never writes prose), and the
fallback rate (a procedure that covers a situation removes a fallback call
entirely).

## 9. Latency budget

The assessment allows five minutes. The budget is spent like this:

| Stage | Budget | Notes |
| --- | --- | --- |
| Ingest and validation | 50 ms | the envelope is validated against a schema |
| Fold and match | 100 ms | metadata filtering plus step merge |
| Gate | 2 s | cached per event; the fast tier |
| Fallback agent | 8 s | only when no procedure matched |
| Rendering and delivery | 1 s | templates are local |
| **Total typical** | **< 4 s** | |
| **Total worst case** | **< 15 s** | inside the 5-minute budget with room for retries |

The agent also waits on purpose: `agent_reaction_seconds` (60 s) is the delay
between an inbound message and the agent's response, which is what makes the
07:01 / 07:13 / 07:31 / 08:01 timeline in the assessment reproducible. A
timer that fires is our own scheduled work and is handled without the delay.

## 10. Safety

* **Guardrails.** A message is suppressed when the agent is replying to
  something nobody asked about. "Do nothing" is a recorded decision with a
  reason, not an absence of one.
* **Idempotency.** Every action carries a key derived from the load, the
  event, the procedure and the step. A duplicate is suppressed before the
  adapter runs, and the same key is sent to the provider.
* **Budget and deadline.** Both are checked before a model call, never after.
* **Templates only.** Nothing reaches a driver that was not written by a
  human and reviewed.
* **Escalation.** The ladder ends in a Human task. The agent is explicitly
  allowed to be insufficient, and there is always a route to a person.
* **Audit.** Every action stores its rationale: the procedure, the step, the
  predicates, the gate output, the template and the rendered text.

## 11. Scaling

At the current volume (10k loads/month, ~0.4 events/s) one worker process
handles everything. The topology on Render is a web service, a background
worker, a cron job for the timer scan, Postgres and a key-value store.

At 10x (1M loads/month, ~40 events/s peak) the changes are: partition the
event log by load, move timer scanning to a claim-based worker pool, keep the
budget counters in Redis, and shard the work by `load_id` so a load is always
processed by the same worker. The design does not change - only the storage
implementations do, behind the protocols in `persistence/protocols.py`.

## 12. What is built and what is not

Built and exercised by the test suite: the event model and the fold, the SOP
loader, resolver and validator, the template renderer, the gates, the
guardrails, the action builder, the policy engine, the fallback agent, the
runtime, the action ledger, the adapter interface with mocks, the LLM gateway
with tiering, budget and accounting, the evaluation harness with seven
scenarios, the CLI, and the authoring guide.

Not built, and called out in `PROPOSAL.md` §16: a real database behind the
persistence protocols, a real provider behind the adapter interfaces, the
FastAPI ingest service, the production worker, the candidate-SOP review
queue, and the retrieval index described in ADR 0008.
