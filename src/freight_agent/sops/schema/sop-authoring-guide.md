# Writing an SOP

This guide is for the people who write the procedures: Heroes, customer success
staff, operations. You do not need to know anything about Python, YAML or
machine learning. You edit Markdown files.

Every SOP file has two parts:

1. **The prose.** Ordinary English, for the humans who read it. It is also what
   the fallback agent reads when no procedure matches, so write it as instructions.
2. **The policy block.** A YAML list of steps the engine executes. This is where
   the machine-readable part lives.

Both live in the same file so they can never drift apart.

## The file layout

```
sops/
  base/                        applies to every client
    delay-risk-high.md
  clients/
    client_b/                  applies to one client
      delay-risk-high.md
      templates/               this client's wording of a message
        ask_eta.md
      load_types/
        refrigerated/          applies to one client and one load type
          driver-left-pickup.md
  templates/                   the default wording of a message
    ask_eta.md
```

The engine resolves a procedure in three layers, most specific last:

```
base  ->  client  ->  client + load type
```

A layer may change **individual steps**, not whole files. If Client B only wants
a different escalation target, they write one short file with one step.

## The front matter

```yaml
---
policy_key: delay_risk.high
title: High delay risk - get an ETA from the driver, then escalate
scope: base            # base | client | client_load_type
client_id: client_b    # required for client and client_load_type
load_types: [any]      # any, or a list like [refrigerated]
stages: [to_pickup, to_delivery]
event_types: [location_ping, timer_fired]
situations: []
priority: 50
version: 1
effective_from: 2026-01-01
description: One line, for the people who search the procedures.
---
```

* `policy_key` - the situation's name. Use `client.policy_key` for a client
  specific situation.
* `scope` - `base`, `client` or `client_load_type`.
* `stages` - the load stages the procedure applies in. Empty means all of them.
* `event_types` - the events that can trigger it. Empty means all of them.
* `priority` - higher runs first when several procedures match.

## The policy block

```yaml
```policy
- id: ask_driver_first
  description: First ask. Only when the risk has just gone high.
  when:
    delay_risk_changed: high
    no_open_request: eta
  do:
    action: send_sms
    to_role: driver
    template: ask_eta
    reason: The delay risk went high and we have not asked the driver for an ETA yet.
  effect:
    open_request:
      key: eta
      kind: eta
      addressed_to_role: driver
      attempts: 1
  also:
    - action: set_timer
      request_key: eta
      after_minutes: 30
      reason: Re-check the ETA request 30 minutes from now.
```
```

Every step has:

| Field | Meaning |
| --- | --- |
| `id` | The step's name. Unique inside the file. A client override refers to it. |
| `description` | What the step does, in one line. |
| `when` | The conditions under which the step runs. |
| `gate` | A question the model has to answer before the step runs. |
| `do` | The action. |
| `also` | Extra actions taken at the same time. |
| `effect` | How the load's memory changes. |
| `merge_into` | In an override: merge this step into an existing one. |
| `disable: true` | In an override: remove this step entirely. |

### `when` - the conditions

The vocabulary is closed. These are all of them:

| Condition | Means |
| --- | --- |
| `delay_risk: high` | the current delay risk |
| `delay_risk_changed: high` | **this event** changed the delay risk to high |
| `stage: to_pickup` | the current stage of the load |
| `load_type: refrigerated` | the load type |
| `client_id: client_b` | the client |
| `event_type: location_ping` | the type of the event being handled |
| `no_open_request: eta` | nothing is open under the key `eta` |
| `open_request: {...}` | the state of an open request (see below) |
| `never_acted: <signature>` | the agent has never done this before |
| `last_inbound_from: driver` | the last message came from this role |
| `last_inbound_contains: "gate code"` | the last message contains this text |
| `all: [...]` | every listed condition must hold |
| `any: [...]` | at least one must hold |
| `not: {...}` | the condition must not hold |

An `open_request` condition understands:

```yaml
open_request:
  key: eta              # the request key
  status: open          # open | answered | cancelled (default: open)
  attempts: 1           # exactly this many attempts so far
  min_attempts: 2       # at least this many
  max_attempts: 3       # at most this many
  elapsed_since_last_ask_minutes: ">=30"   # how long ago we asked
  responses_seen: 1     # how many answers we have seen
```

### `gate` - the question the model has to answer

A gate is a small classifier. It runs once per event, and several steps can
share the result.

```yaml
gate:
  name: message_signals
  condition: $gate.has_eta
  description: Does the driver message contain a time of arrival?
```

The conditions you can use:

| Condition | Means |
| --- | --- |
| `$gate.has_eta` | the message states an arrival time |
| `$gate.is_question` | the message asks us something |
| `$gate.kind == 'acknowledgement'` | the message is just "ok" or "sure" |
| `$gate.topic_fact_present` | we have the fact the driver asked about |
| `$gate.topic_fact_missing` | we do not have it |
| `$gate.is_question and $gate.topic_fact_present` | both must hold |
| `$gate.is_question or $gate.kind == 'eta'` | either is enough |

If the model cannot answer, the step does not run. The agent never guesses.

### `do` - the action

| Action | What it does |
| --- | --- |
| `send_sms` | sends a message to a person |
| `send_email` | sends an email, optionally in the load's main thread |
| `send_slack` | posts in a channel |
| `internal_slack` | posts in one of our own channels |
| `tms_note` | writes a note on the load in the TMS |
| `create_hero_task` | opens a task for the Hero team |
| `update_load_state` | changes the load's memory, sends nothing |
| `update_load_stage` | moves the load to another stage |
| `set_timer` | wakes the agent up later |
| `no_action` | deliberately does nothing (and records that decision) |

A message action needs a `template` (the wording to use) or a literal `body`,
and it needs to say who it is for:

```yaml
do:
  action: send_sms
  to_role: driver          # driver | dispatcher | broker | hero
  template: ask_eta
  reason: Why we are doing this. It is shown in the audit trail.
```

An email in the load's main thread says so explicitly:

```yaml
do:
  action: send_email
  to_role: dispatcher
  in_thread: main
  template: dispatcher_no_eta
```

### `effect` - how the memory changes

| Effect | What it does |
| --- | --- |
| `open_request: {key, kind, addressed_to_role, attempts}` | remembers that we are waiting for something |
| `increment_attempts: eta` | counts another attempt |
| `close_request: {key, answer}` | the request was answered |
| `cancel_request: eta` | the request is no longer needed |
| `set_timer: {request_key, fires_at}` | remembers when the next check is |
| `set_delay_risk: high` | changes the delay risk |
| `set_stage: to_delivery` | moves the load to another stage |
| `record_fact: {key, value}` | remembers a fact about the load |

The `open_request` effect is the important one. A request stays open until a
gate *positively* detects the answer. A driver who asks an unrelated question
does not close it, and the escalation ladder keeps going.

### `also` - extra actions

```yaml
also:
  - action: create_hero_task
    template: call_driver_for_eta
    urgent: true
    reason: A human needs to call the driver.
```

## Overriding a base procedure

Write a file in `clients/<client_id>/` with the same `policy_key`. Then, for
each step you want to change, write a step with the same `id`:

```yaml
```policy
- id: escalate_to_dispatcher_and_hero
  description: Client B: Slack alert to the broker. No dispatcher email.
  when:
    open_request:
      key: eta
      attempts: 1
      elapsed_since_last_ask_minutes: ">=30"
  do:
    action: send_slack
    to_channel: broker
    template: broker_delay_alert
    reason: The driver did not give us an ETA. Client B asked us to alert the broker.
```
```

The step with the same `id` **replaces** the base step. The other steps of the
base procedure are untouched.

Two other ways to override:

```yaml
- id: ask_driver_again
  disable: true            # remove the step entirely
```

```yaml
- id: escalate_to_dispatcher_and_hero
  merge_into: escalate_to_dispatcher_and_hero   # merge fields into a step
  description: A better description.
```

## Templates

A template is a Markdown file with `{{placeholders}}`:

```markdown
What time will you arrive at {{next_stop_name}}?
```

Placeholders you can use:

| Placeholder | Value |
| --- | --- |
| `load_id` | the load number |
| `client_id` | the client |
| `next_stop_name` | the name of the next stop |
| `next_stop_address` | its address |
| `next_stop_appointment` | its appointment time |
| `stage` | the current stage |
| `delay_risk` | the current delay risk |
| `load_type` | the load type |
| `value` | the answer to the driver's question |
| `topic_label` | the question in words, e.g. "PO number" |
| any fact | any fact in the load metadata, e.g. `po_number` |

If a template needs a value the load does not have, the message is **not** sent.
This is deliberate: a message with a hole in it is worse than no message.

A client can change the wording of a template by putting a file with the same
name in `clients/<client_id>/templates/`.

## Checking your work

Always run the validator before you open a pull request:

```bash
freight validate
```

It checks that every step has an id, that every condition and action is one the
engine knows, that every template exists, and that every override refers to a
step that really exists in the base procedure. The messages are written for
humans, not for the compiler.
