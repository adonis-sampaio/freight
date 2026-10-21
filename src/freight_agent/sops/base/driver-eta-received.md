---
policy_key: driver.eta_received
title: The driver gave us an ETA
scope: base
load_types: [any]
event_types: [sms, email]
situations: []
priority: 80
version: 1
effective_from: 2026-01-01
description: Closes the ETA request as soon as the driver actually provides an ETA.
---

## When the driver gives an ETA

An ETA request stays open until the driver actually provides an ETA. The driver may
answer with something else entirely - a question, a complaint, "ok" - and in that case
the request stays open, because we still do not know when the truck will arrive.

This step is what makes the escalation ladder honest: the ladder only advances while
the request is open, and only this step closes it.

```policy
- id: close_eta_request
  description: Close the ETA request and stop the escalation ladder.
  when:
    last_inbound_from: driver
  gate:
    name: message_signals
    condition: $gate.has_eta
    description: Does the driver message contain a time of arrival?
  do:
    action: update_load_state
    reason: The driver supplied an ETA, so the ETA request is answered.
  effect:
    close_request:
      key: eta
      answer: $gate.eta
```
