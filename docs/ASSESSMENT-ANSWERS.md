# Agent design: assessment answers

This guide answers the architecture, SOP, memory, evaluation, and scale
questions for the freight agent. It separates the implementation in this
repository from production design recommendations in
[`PROPOSAL.md`](PROPOSAL.md). The proposal describes a fuller target system;
not every component in it is implemented.

## Agent architecture

### 1. Architecture and alternatives

The agent is event-driven and hybrid: a deterministic policy engine executes
known procedures, while a language model is used for narrow language
classification and for situations no procedure covers. A model output is
structured data (validated against a schema), not an instruction to take an
action. The policy engine checks the procedure, current state, and guardrails;
adapters are responsible for external side effects.

For each event, the runtime:

1. Deduplicates the event when it has a provider event ID.
2. Adds it to that load's event history and folds the history into current
   state.
3. Resolves and matches applicable SOPs.
4. Evaluates any required LLM gates, with results reused within the event.
5. Evaluates deterministic predicates and builds permitted actions.
6. Records actions and their rationale, then passes actions to an integration
   adapter.

For example, code tracks how many ETA requests have been sent and whether one
is still open. A model may classify an inbound message as an ETA, a question,
or an acknowledgement; it does not decide whether the escalation ladder has
reached its second rung. Outbound text comes from reviewed templates.

The main alternatives are:

| Approach | Advantages | Disadvantages for freight procedures |
| --- | --- | --- |
| Pure LLM agent interpreting SOP prose | Flexible when an unfamiliar situation occurs; less policy compilation | Re-interprets rules on every event; counting attempts and timing are less reliable; higher and less predictable cost and latency; harder to test and audit |
| Pure deterministic rules | Fast, inexpensive, predictable, and straightforward to test | Cannot classify ambiguous natural-language messages well and has no principled path for situations not anticipated in rules |
| Hybrid policy engine with narrow LLM gates and a constrained fallback | Deterministic for known workflows; uses language understanding only where needed; unknown cases can be surfaced to a human | Requires a maintained policy vocabulary, validator, scenario coverage, and careful boundaries around model output |

The hybrid is the choice implemented by the engine and runtime. The fallback
agent is constrained to existing templates and known contacts, with a human
task available when it should not act autonomously.

### 2. Reading documents, identifying their type, and extracting values

There are two different meanings of "document" in this application:

* **SOP documents are implemented.** They are Markdown files. The loader reads
  YAML front matter for metadata such as `policy_key`, scope, client, load
  types, event types, and stages. It parses an optional fenced `policy` YAML
  block into typed steps. Remaining prose is preserved separately for people
  and fallback context.
* **Freight attachments are not yet processed end-to-end.** The event model
  can record attachment IDs, and LLM schemas define document labels and
  structured fields for Bills of Lading, Proofs of Delivery, and rate
  confirmations. But the current runtime does not ingest attachment bytes,
  perform OCR/vision classification, extract those values, or persist
  document facts. Those schemas are building blocks, not a shipped
  attachment pipeline.

The proposed attachment pipeline is: validate file bytes and detect format;
combine filename and deterministic file-type hints with a model choosing from
a fixed set of document labels; then extract type-specific fields into a
strict schema. Check confidence and required fields; route low-confidence or
conflicting results to a human rather than silently treating them as facts.
Store the source document reference, extracted values, confidence, and review
status so policy logic can use validated facts later. OCR or a vision-capable
model is needed to read images and scanned PDFs; text PDFs may use text
extraction first. This pipeline remains future work.

## Instructions and SOPs

### 1. Organizing procedures for many clients

Use three inheritance layers:

```text
base procedure
  + client-specific overrides
  + client-and-load-type overrides
  = effective procedure for the load
```

The base procedure applies unless a more specific matching document changes
it. Documents are matched by `policy_key` and metadata, including client and
load type. Overrides are applied by step ID: a matching ID replaces a step;
`merge_into` can patch fields; `disable: true` removes a step. Unmodified steps
remain inherited. The resolver keeps source/provenance information for
resolved steps.

For instance, a standard delay procedure can ask the driver for an ETA and
escalate after a timeout. A client may override only the escalation step,
without copying the base procedure or changing another client's behavior.
This layered resolver is implemented; version effective dates and promotion
controls described in the proposal are not fully enforced by the current
runtime.

### 2. Finding the SOPs for an event

The runtime gets the load's client and load type from registered load
metadata. It resolves policies for those identifiers, then filters using
structured policy metadata: event type, load stage, load type, declared
situation, and priority. Only matched steps are considered for execution.
This is deterministic metadata selection, not semantic search.

Advantages:

* Exact matches are fast, explainable, and repeatable.
* Client and load-type boundaries are explicit.
* No embedding or model call is required just to locate a known policy.
* The resolved policy can show which file supplied each step.

Tradeoffs:

* Authors must use the supported metadata and predicate vocabulary.
* A new kind of situation may need a policy taxonomy or engine change.
* Similar-sounding prose is not automatically recognized as equivalent.
* Semantic retrieval for fallback reasoning (BM25/vector search) is described
  in ADR-008 and the proposal, but the retrieval index is not implemented.

For this workflow the policy corpus is executable instruction, so an exact
metadata filter is safer than relying on a vector search to choose what rules
to execute. Semantic retrieval can still be useful later for contextual
explanation or fallback, but should not replace deterministic policy matching.

### 3. Safe SOP authoring for non-technical people

The design keeps readable explanation and executable policy together in
Markdown. Editors change prose and small values in a constrained YAML block,
using documented conditions, actions, and copyable examples. The executable
block is parsed and validated before it can be used. The current CLI supports
`freight validate`, which checks the packaged SOP corpus and reports invalid
actions, unknown predicate keys, missing requirements, and other policy
issues. The authoring guide is
[`../src/freight_agent/sops/schema/sop-authoring-guide.md`](../src/freight_agent/sops/schema/sop-authoring-guide.md).

For safe operational change management, the recommended workflow is:

1. Propose SOP edits as a version-controlled change, scoped to one client or
   load type where possible.
2. Run the validator and show the resolved policy after inheritance.
3. Replay scenarios for the changed client plus shared base and do-nothing
   scenarios.
4. Have an authorized reviewer approve the change; record a version and
   effective date.
5. Promote deliberately, monitor actions and divergences, and retain a
   rollback path.

The validator, resolver, and CLI validation command exist. A non-technical
web editor, resolved-policy preview command, automated change-aware CI,
approval workflow, candidate-SOP queue, and per-client shadow rollout are
design recommendations in the proposal, not all shipped features.

## Memory

### 1. Past actions and messages

Each event has a canonical envelope. Inbound email, SMS, Slack, location
pings, timer firings, and agent actions are represented as events for a load.
Agent actions are also recorded as events and in an action ledger. The runtime
rebuilds `LoadState` by folding events in order. State therefore includes
facts needed for decisions, recent inbound-message details, and open requests.
Action records contain the action, idempotency key, policy and step, predicate,
gate result, and rationale.

In the current application, these stores are in memory and belong to the
process. The API and timer worker run together in one Render service so they
can see the same timers. A restart or redeploy loses the in-memory event
history, action ledger, registered load metadata, and timers. Durable Postgres
storage and independent workers are future work; the current behavior should
not be described as durable event sourcing.

### 2. Why the ETA request is still open at 07:13

When the first ETA SMS is sent, its state effect opens the `eta` request and
records the attempt count and send time. The 07:12 driver message is classified
by the message gate. A PO-number question is not an ETA, so it does not close
the request; the application can answer the PO question from load facts while
keeping the ETA request open. At the next decision point, the policy reads the
structured `open_requests["eta"]` state rather than asking a model to remember
what happened in the conversation.

The tests exercise this sequence: an unrelated question is answered while the
ETA request remains open; an actual ETA closes it and stops the escalation
ladder.

### 3. Follow-up timers

The policy schedules a timer for the open request. A timer has a load ID,
request key, due time, reason, and status. When it is due, the timer worker
marks it fired and supplies a `timer_fired` event to the same runtime used for
webhooks. The event carries request context such as the request key and
elapsed time. The runtime folds that event into state and evaluates the
applicable policy; the timer itself does not make an escalation decision.

Today, timer storage and scanning are in-process/in-memory, and the worker is
started as a thread in the API process. The timer and event handling are
implemented, but durable timer rows and a separate cron/worker topology
require shared persistent stores that are not yet implemented.

## Evals

### 1. Confidence that production behavior is correct

The implemented foundation is a deterministic replay harness using the real
runtime, real SOP files, and real templates, with a fake model and mock
integrations. Scenarios assert observable outcomes: actions, targets, message
contents, open/answered requests, and forbidden actions. The suite includes
the escalation timeline, ETA response behavior, and cases where doing nothing
is correct. Run it with `freight eval` or `make eval`; the project tests also
cover components and API behavior.

For stronger production assurance, add layered gates:

* Fast unit and deterministic scenario tests on every change.
* Live-model tests on a fixed golden set before model promotion and on a
  schedule, comparing structured outputs and dangerous classification flips.
* Shadow evaluation on sampled production events before activating a changed
  policy or model.
* Cost, latency, no-action false-positive, and action-divergence monitoring.
* Auditable decision traces and a per-client kill switch/rollback procedure.

The deterministic harness and seven scenario definitions are implemented;
live model promotion gates, production shadow mode, dashboards, and per-client
kill switches are not part of the current application.

### 2. Preventing a client SOP change from breaking other clients

Scope overrides by client and load type, then test the actual resolved policy.
For each change, replay the affected client's cases, shared base cases, and
negative/do-nothing cases. Test that other clients resolve to the same
effective policy when they should be unaffected. Snapshot tests and
change-aware CI can make that blast radius visible to reviewers.

The resolver's scoping and merge behavior and client-specific scenarios exist.
The complete change-aware CI and resolved-policy snapshot workflow is a
recommended extension, not an existing automated guarantee.

### 3. Changing the LLM safely

Keep model IDs configurable, run the same golden messages against the new
model, and compare the structured fields that affect behavior—not just
free-form quality. In particular, test:

* A PO question is not classified as an ETA.
* An explicit arrival time is classified as an ETA.
* A bare "ok" is an acknowledgement and does not close an ETA request.
* Invalid, missing, or low-confidence output cannot authorize an unsafe
  action.

Require no regression in escalation and do-nothing outcomes before promotion.
Record model ID, schema version, tokens, cost, and latency per call; use a
small shadow sample and keep a rollback path. The gateway, structured
schemas, configurable model tiers, and fake model are implemented. Automated
model-version comparison, shadow deployment, and a promotion/rollback
controller are not.

### 4. Evals for different clients and complexity

Organize scenario coverage along the same dimensions as policy resolution:
shared base, client, load type, and situation. Keep common behavior in base
scenarios; a client suite adds only override-specific cases; load-type suites
cover additional constraints. Run applicable base and negative cases against
each resolved client policy, and track which policy/step combinations have
no coverage. This shares behavior without duplicating the entire suite for
every client.

The current code keeps seven scenario factories in
[`../src/freight_agent/evals/scenarios.py`](../src/freight_agent/evals/scenarios.py)
rather than a full directory of independently selectable client/load-type
suites. The scenario runner creates a fresh runtime per scenario, and
`freight eval` runs the registered scenarios. Coverage reports and automated
suite selection by changed SOP are future improvements.

## Scale, response time, and cost

### 1. Keeping a run within five minutes

The intended approach is to keep the common path deterministic and place
strict timeouts, bounded retries, and an overall wall-clock deadline around
model and adapter work. A per-run budget should stop new model calls as the
deadline approaches, finish safe deterministic work, and escalate unresolved
cases to a person. Slow outbound integrations should be queued or handled
outside the critical path.

The application already has bounded model request timeouts and retry behavior,
and settings expose `RUN_DEADLINE_SECONDS=240`. However, that setting is not
currently enforced as an overall runtime deadline, and the API processes the
event within the webhook handler rather than enqueueing it for asynchronous
processing. The five-minute end-to-end limit is therefore a design target,
not a production guarantee in this version. Implement and measure an overall
deadline plus asynchronous processing before claiming that SLO.

### 2. What must change at ten times the volume

The current implementation uses per-process in-memory stores, so simply
adding API or worker instances would split load state and timers. Before
horizontal scaling, replace these with shared durable implementations and
ensure events for a load are processed consistently. At roughly ten times the
volume, the design should:

* Put events, actions, timers, and load metadata in durable shared storage.
* Make webhook ingestion stateless and enqueue work to a durable queue.
* Scale worker instances based on queue depth and partition work by `load_id`.
* Add indexes/partitioning and efficient per-load snapshots or incremental
  state updates.
* Use claim-based, indexed due-timer processing or a durable timer service.
* Add rate limits, backpressure, dead-letter handling, and observability.
* Reassess LLM quotas, retrieval throughput, database connections, and
  per-client fairness under load testing.

These are scale-out design recommendations. The Render blueprint shipped in
this repository runs one API service with an in-process timer thread because
state is not shared across processes. Postgres, Redis, and distributed worker
processing are not yet wired to the runtime stores.

### 3. Keeping model cost near or below $1 per load

The main cost controls are architectural: use deterministic rules for known
cases; call the model only for language classification or genuinely uncovered
events; choose a low-cost model for routine gates; use strict structured
outputs; render outbound messages from templates instead of generating prose;
cache stable prompt prefixes; bound fallback iterations; and keep accounting
and a hard per-load budget guard. Non-urgent extraction and evaluation work
can use batch processing. Unknown cases should route to human review instead
of repeatedly prompting an expensive model.

The proposal estimates about $0.07 per load under its stated workload,
comfortably below the $1 target, but actual cost depends on model rates,
token counts, cache hits, and event volume. The repository includes tiered
model settings, a per-load model-call budget check, call accounting, and
template-based messages. Its current in-memory accounting is not durable and
does not cover billing outside the configured model gateway; production
costs still need to be measured from provider usage.

## Related documentation

* [`ARCHITECTURE.md`](ARCHITECTURE.md) — implemented run loop and components.
* [`PROPOSAL.md`](PROPOSAL.md) — broader target design, scaling, and cost
  projections.
* [`ADRs.md`](ADRs.md) — decisions and alternatives.
* [`RUNNING.md`](RUNNING.md) — local run and deployment instructions.
