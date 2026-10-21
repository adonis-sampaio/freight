# ADR 018: The OpenAI Responses API with strict JSON schema outputs

* **Status:** accepted
* **Slug:** `responses-api-with-structured-outputs`

## Context

Every model call in this system has to return a specific shape: the
gate signals, the fallback decision. Free-form text that is then parsed is
where the silent failures come from - a model that returns one extra field, or
prose where JSON was expected, must be handled at runtime.

## Decision

The Responses API, with the output schema declared to the provider
and `strict: true`. The provider constrains the output to the schema, and
the parsed object is validated again locally, because a provider bug should
not be able to break the engine.

The same API gives access to reasoning effort, which the tiering uses, and
to prompt caching, which the cost model depends on.

## Consequences

Malformed model output is a validation error rather than a runtime
mystery. The strict schema is also a contract the fake model in the test
suite implements, so the tests exercise the same shape as production. The
cost is the model being restricted to schemas the provider can enforce, which
is exactly the set we want it restricted to.

## Alternatives considered

Chat Completions (a direction the provider is migrating away from),
the Assistants API (deprecated), or free-form output plus local parsing
(where the silent failures live).
