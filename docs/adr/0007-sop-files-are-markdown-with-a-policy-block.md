# ADR 007: SOP files are Markdown with front matter and a fenced policy block

* **Status:** accepted
* **Slug:** `sop-files-are-markdown-with-a-policy-block`

## Context

The people who write procedures are not programmers, and the
assessment is explicit that the procedures should be editable without
engineering help. A YAML file with a rigid schema is hostile to them. A prose
document is friendly but not machine-checkable, and a machine that must
interpret prose is a machine that interprets it differently on Tuesday than
on Monday.

## Decision

Each procedure is a Markdown file: human prose at the top, a fenced
`policy` block with the machine-readable steps underneath, and YAML front
matter for the metadata. The prose is not decoration - it is what the
fallback agent reads when no procedure matches, and it is what a new starter
reads when they ask "why does the agent do this?".

The policy block is validated against a JSON schema and against a closed
vocabulary, so an unsupported condition is a clear error message rather than a
step that silently never fires.

## Consequences

Non-technical editors keep writing prose, and the machine-checkable
part lives next to the explanation of it. A validator gives them a safe
editing loop: `freight validate` before a pull request, with messages written
for humans. The prose and the steps cannot drift apart, because they are one
file.

The cost is a format with two halves and a parser for both, and a rule that
the prose must be kept meaningful because the fallback agent depends on it.

## Alternatives considered

Pure prose (non-deterministic and expensive to interpret), pure YAML
(hostile to non-technical editors, no room for nuance), or a wiki with a
separate rules table (the two drift immediately).
