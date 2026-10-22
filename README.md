# Freight load agent

An agent for a freight brokerage. It watches a load, decides what to do when
something goes wrong, and shows its work.

The situation the system was built for: a load's delay risk goes high, the
driver does not give an ETA, and the dispatcher has to know about it. The
assessment for this repo is
[`AI Engineer System Design Assessment.md`](AI%20Engineer%20System%20Design%20Assessment.md).

```
$ freight demo
Load 481207: the delay risk goes high and the driver never gives an ETA  (load 481207)
┏━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Time  ┃ Event         ┃ Decision                  ┃ Message                  ┃
┡━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 07:01 │ location_ping │ delay_risk.high /         │ What time will you       │
│       │               │ ask_driver_first          │ arrive at Riverbend      │
│       │               │                           │ plant?                   │
│ 07:13 │ sms           │ driver.question /         │ The PO number for load   │
│       │               │ answer_from_load_facts    │ 481207 is 55821.         │
│ 07:31 │ timer_fired   │ delay_risk.high /         │ What time will you       │
│       │               │ ask_driver_again          │ arrive at Riverbend      │
│       │               │                           │ plant?                   │
│ 08:01 │ timer_fired   │ delay_risk.high /         │ Your driver on load      │
│       │               │ escalate_to_dispatcher_a… │ 481207 has not answered  │
│       │               │                           │ two requests for an ETA. │
│       │               │                           │ Please send us the ETA.  │
│ 08:01 │ timer_fired   │ delay_risk.high /         │ Call the driver on load  │
│       │               │ escalate_to_dispatcher_a… │ 481207. We asked for an  │
│       │               │                           │ ETA twice and got no     │
│       │               │                           │ answer.                  │
└───────┴───────────────┴───────────────────────────┴──────────────────────────┘
```

The driver asked about the PO number at 07:12. We answered it - and the
escalation ladder kept going, because an unrelated question is not an ETA.

## The idea

Most of the work is a **procedure that a person already wrote down**: when
the delay risk goes high, ask the driver for an ETA, wait thirty minutes,
ask again, then escalate to the dispatcher and open a task for the Hero team.
That part is executed by a deterministic policy engine, because a counter that
knows it has asked twice is worth more than a model that might remember to
count.

The part a procedure cannot cover - a situation nobody wrote down - is handled
by a **fallback agent**, under strict limits: it may choose a reviewed
template and a known contact, and it may open a Human task. It never writes
its own message to a driver, and it never decides to escalate on its own.

The model is used where it is genuinely good and cheap: reading a driver
message and deciding whether it contains an ETA, whether it is a question,
and which fact it is asking about. The decision to send, and the count of how
many times we have asked, live in code.

## Try it

No API key, no database, no network.

```bash
uv venv && uv pip install -e ".[dev]"
freight demo        # replay the assessment's situation, step by step
freight eval        # run the seven evaluation scenarios
freight validate    # check the SOP corpus
freight sop client_b --load-type refrigerated   # what applies to a client
```

Or through the Makefile:

```bash
make demo      make eval      make validate      make test      make check
```

`freight demo` and `freight eval` use a fake model, so they are
deterministic. Add `--real-llm` to use OpenAI instead (needs
`OPENAI_API_KEY`).

## What is in the box

| | |
| --- | --- |
| **Procedures** | Markdown with a machine-checkable policy block, layered `base → client → client+load type`, merged step by step |
| **Engine** | template rendering, LLM gates, guardrails, an action builder, a policy engine, a template-only fallback agent |
| **Runtime** | deduplication, a state fold over the event log, timers, an action ledger with idempotency keys |
| **Integrations** | SMS, email, Slack, TMS and Hero tasks, behind one adapter interface, with mocks |
| **Model** | one gateway with tiering, a per-load budget guard, a deadline and per-call accounting |
| **Evals** | seven scenarios, a fake model, and assertions on what was sent and why |
| **Docs** | a proposal, an architecture document, twenty ADRs, and a guide for non-engineers writing procedures |

## The repository

```
src/freight_agent/
  domain/       events, the state fold, predicates, the facts of a load
  sop/          loader, models, resolver, validator
  engine/       templates, gates, guardrails, action builder, policy engine,
                fallback agent
  llm/          gateway, tiers, prompts, schemas
  persistence/  the storage protocols and their in-memory implementation
  integrations/ the adapter interface and the mocks
  evals/        fixtures, scenarios, the runner, the fake model
  sops/         the procedure corpus, packaged with the code
  runtime.py    the run loop
  cli.py        the command line interface
tests/          69 tests
docs/           PROPOSAL, ARCHITECTURE, ADRs, RUNNING
```

## Writing a procedure

Procedures are written by people, not by engineers, in Markdown, next to the
prose that explains them. The authoring guide is
[`src/freight_agent/sops/schema/sop-authoring-guide.md`](src/freight_agent/sops/schema/sop-authoring-guide.md).

```markdown
---
policy_key: delay_risk.high
scope: base
---

Ask the driver for an ETA when the delay risk goes high.

```policy
- id: ask_driver_first
  when: {delay_risk_changed: high, no_open_request: eta}
  do: {action: send_sms, to_role: driver, template: ask_eta}
  effect: {open_request: {key: eta, kind: eta, addressed_to_role: driver, attempts: 1}}
```
```

Client B wants a different escalation, and writes twenty lines:

```markdown
---
policy_key: delay_risk.high
scope: client
client_id: client_b
---

Client B: one SMS, then a Slack alert to the broker.

```policy
- id: escalate_to_dispatcher_and_hero
  when: {open_request: {key: eta, attempts: 1, elapsed_since_last_ask_minutes: ">=30"}}
  do: {action: send_slack, to_channel: broker, template: broker_delay_alert}
```
```

The override replaces one step. Everything else is inherited from the base
procedure, and the resolved procedure records which file each step came from.

## Cost and speed

* **$0.07 per load** projected, against the assessment's $1.00 budget. The
  model writes no prose; it classifies.
* **Under 4 seconds** typical, against the 5-minute budget.
* **One model call per event**, cached across the candidate steps of that
  event.

## Reading order

1. [`docs/PROPOSAL.md`](docs/PROPOSAL.md) - the full design, the cost model,
   the deployment plan and what is deliberately not built.
2. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - how a run works, in
   detail.
3. [`docs/ADRs.md`](docs/ADRs.md) - the twenty decisions, each with the
   alternative that was rejected.
4. [`docs/RUNNING.md`](docs/RUNNING.md) - running it locally, deploying it,
   operating it.
5. [`docs/ASSESSMENT-ANSWERS.md`](docs/ASSESSMENT-ANSWERS.md) - direct answers
   about agent architecture, SOPs, memory, evals, and scale.
