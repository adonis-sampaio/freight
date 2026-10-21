---
policy_key: delay_risk.high
title: High delay risk - get an ETA from the driver, then escalate
scope: base
load_types: [any]
stages: [to_pickup, to_delivery]
event_types: [location_ping, timer_fired]
situations: []
priority: 50
version: 1
effective_from: 2026-01-01
description: Standard escalation ladder when the system says the load is likely to miss its appointment.
---

## What to do when the delay risk becomes high

The driver is the cheapest and fastest source of an updated ETA, so ask the driver
first. Do not contact the dispatcher before we have asked the driver twice: the
dispatcher rarely knows more than the driver, and escalating early erodes the
relationship with both of them.

The ladder has three rungs:

1. Ask the driver for the ETA by SMS.
2. If there is still no ETA 30 minutes later, ask the driver again.
3. If there is still no ETA 30 minutes after the second ask, email the dispatcher in
   the main thread and open a task for the Hero team to call the driver.

Each rung is armed by a timer, so the system does not have to poll. The next rung
only fires when the ETA request is *still open*, which is exactly what we want:
if the driver answers, the ladder stops.

```policy
- id: ask_driver_first
  description: First ask. Only when the risk has just gone high and we have not asked yet.
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

- id: ask_driver_again
  description: Second ask. 30 minutes after the first ask, if the request is still open.
  when:
    open_request:
      key: eta
      attempts: 1
      elapsed_since_last_ask_minutes: ">=30"
  do:
    action: send_sms
    to_role: driver
    template: ask_eta
    reason: We asked the driver for an ETA 30 minutes ago and have not received one.
  effect:
    increment_attempts: eta
  also:
    - action: set_timer
      request_key: eta
      after_minutes: 30
      reason: Re-check the ETA request 30 minutes from now.

- id: escalate_to_dispatcher_and_hero
  description: Third rung. Two asks with no ETA, and 30 minutes have passed since the second.
  when:
    open_request:
      key: eta
      min_attempts: 2
      elapsed_since_last_ask_minutes: ">=30"
  do:
    action: send_email
    to_role: dispatcher
    in_thread: main
    template: dispatcher_no_eta
    reason: The driver did not give us an ETA after two requests.
  also:
    - action: create_hero_task
      template: call_driver_for_eta
      urgent: true
      reason: A human needs to call the driver.
```
