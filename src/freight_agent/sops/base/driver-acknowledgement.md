---
policy_key: driver.acknowledgement
title: The driver sent an acknowledgement we did not ask for
scope: base
load_types: [any]
event_types: [sms]
situations: []
priority: 70
version: 1
effective_from: 2026-01-01
description: The canonical do-nothing case.
---

## When the driver says "ok" and we did not ask anything

Drivers reply "ok", "sure", "yes" all the time. If we did not ask a question, there is
nothing to answer. Replying "thanks" to an "ok" trains drivers to ignore us, and it
costs money on every load.

The correct action is to do nothing. We still record that decision so that it can be
audited and tested - doing nothing is a decision, not an absence.

The same applies when we *are* waiting for an ETA and the driver says "ok" instead of
giving one: an acknowledgement is not an answer, so we still do not reply, and the ETA
request stays open. The escalation ladder is driven by the timer, not by the driver
answering something else.

```policy
- id: no_reply_to_acknowledgement
  description: Do nothing. An acknowledgement is never worth a reply.
  when:
    last_inbound_from: driver
  gate:
    name: message_signals
    condition: $gate.kind == 'acknowledgement'
    description: Is this just an acknowledgement such as "ok" or "sure"?
  do:
    action: no_action
    reason: The driver sent an acknowledgement, and there is nothing in it to answer.
```
