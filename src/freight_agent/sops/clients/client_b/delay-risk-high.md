---
policy_key: delay_risk.high
title: High delay risk - ask the driver, then alert the broker in Slack
scope: client
client_id: client_b
load_types: [any]
stages: [to_pickup, to_delivery]
event_types: [location_ping, timer_fired]
situations: []
priority: 50
version: 1
effective_from: 2026-01-01
description: Client B overrides the escalation rung. No dispatcher contact, ever.
---

## Client B change: alert the broker in Slack, never contact the dispatcher

Client B does not want us to contact the carrier dispatcher. Their dispatcher forwards
everything to the driver anyway, and the broker would rather handle the delay themselves
than have two parties chasing the same driver.

So the ladder is shorter than the standard one. Client B wants exactly one SMS to the
driver, and if there is still no ETA 30 minutes later, an alert in the broker's Slack
channel. There is no second SMS and no dispatcher email, ever.

The first rung is unchanged - we still ask the driver once, 30 minutes before the second
rung would fire.

```policy
- id: ask_driver_again
  description: Client B does not want a second SMS. The ladder goes to the broker instead.
  disable: true

- id: escalate_to_dispatcher_and_hero
  description: "Client B: Slack alert to the broker. No dispatcher email."
  when:
    open_request:
      key: eta
      attempts: 1
      elapsed_since_last_ask_minutes: ">=30"
  do:
    action: send_slack
    to_channel: broker
    template: broker_delay_alert
    reason: The driver did not give us an ETA 30 minutes after we asked. Client B asked us to alert the broker instead of the dispatcher.
  also:
    - action: internal_slack
      to_channel: hero_delay
      template: hero_delay_alert
      reason: The Hero team needs to know that the driver is not responding.
```
