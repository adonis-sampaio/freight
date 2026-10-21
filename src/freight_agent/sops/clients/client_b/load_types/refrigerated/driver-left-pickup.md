---
policy_key: driver.left_pickup
title: Refrigerated load - check the trailer temperature and the seal number
scope: client_load_type
client_id: client_b
load_types: [refrigerated]
stages: [to_delivery]
event_types: [location_ping]
situations: []
priority: 40
version: 1
effective_from: 2026-01-01
description: Only applies to Client B's refrigerated loads, when the driver leaves the pickup.
---

## Refrigerated loads: check the trailer when the driver leaves the pickup

For refrigerated loads the trailer has to stay in range for the whole trip, and the
receiver needs the seal number to open it. When the driver leaves the pickup we ask for
both in one message, because the driver is still parked and reachable at that point.

This rule only exists for refrigerated loads. A dry-van load on the same lane does not
need a temperature check, so we do not ask.

```policy
- id: ask_trailer_temperature_and_seal
  description: Ask for the trailer temperature and the seal number in one message.
  when:
    stage: to_delivery
  do:
    action: send_sms
    to_role: driver
    template: ask_trailer_temp_and_seal
    reason: The driver left the pickup on a refrigerated load, so we need the trailer temperature and the seal number.
  effect:
    open_request:
      key: trailer_check
      kind: trailer_check
      addressed_to_role: driver
      attempts: 1
  also:
    - action: set_timer
      request_key: trailer_check
      after_minutes: 60
      reason: Follow up on the trailer check after an hour.
```
