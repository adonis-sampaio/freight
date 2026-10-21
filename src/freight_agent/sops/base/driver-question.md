---
policy_key: driver.question
title: The driver asked a question
scope: base
load_types: [any]
event_types: [sms, email]
situations: []
priority: 60
version: 1
effective_from: 2026-01-01
description: Answers driver questions from the load metadata when we have the answer.
---

## When the driver asks us something

Drivers ask practical questions all day: the PO number, the gate code, the dock. When
the answer is in the load metadata, we answer it. The answer is taken from the load
facts, which come from the load metadata the TMS gave us.

Answering a question is **not** the same as receiving the ETA. This step must not close
the ETA request, and it must not move the escalation ladder forward. The ladder only
advances on a timer.

If we do not have the answer, the right thing is to escalate rather than to guess. A
driver that gets a wrong number at the gate is worse than a driver that gets no answer,
so the two steps below are mutually exclusive: exactly one of them fires.

```policy
- id: answer_from_load_facts
  description: Answer from the load metadata if we know the answer.
  when:
    last_inbound_from: driver
  gate:
    name: message_signals
    condition: $gate.is_question and $gate.topic_fact_present
    description: Do we have the fact the driver asked about?
  do:
    action: send_sms
    to_role: driver
    template: answer_from_facts
    reason: The driver asked a question and we have the answer in the load metadata.

- id: escalate_unanswerable_question
  description: We do not have the answer, so a person has to look it up.
  when:
    last_inbound_from: driver
  gate:
    name: message_signals
    condition: $gate.is_question and $gate.topic_fact_missing
    description: Do we have the fact the driver asked about?
  do:
    action: create_hero_task
    template: hero_unanswerable_question
    reason: The driver asked a question we cannot answer from the load metadata.
```
