# ADR 008: Retrieval: metadata filter, then BM25, then embedding rerank

* **Status:** accepted
* **Slug:** `metadata-filter-then-bm25-then-embedding`

## Context

The corpus is small enough to fit in a prompt, and will not stay
that way. It also contains a lot of exact-match metadata - `stage:
at_pickup`, `load_type: refrigerated` - which is the case vector search is
worst at, because "at_pickup" and "at the pickup" are not close in embedding
space but are identical to a filter.

## Decision

Metadata filtering removes almost the entire corpus for the cost of
a SQL predicate. Only the survivors are ranked, first with full-text search
and then with embeddings, and only the top few are placed in the prompt. The
embedding step is what catches the paraphrase; the filter is what guarantees
the exact matches are never missed.

The practical consequence is that a procedure that only applies to
refrigerated loads never reaches the model when the load is dry van, and the
cost of that is zero.

## Consequences

Retrieval stays cheap as the corpus grows, and exact-match
requirements remain exact. The cost is three components instead of one, and
the embedding step needs an index.

The current implementation resolves procedures by metadata and step, without
embeddings, because the corpus is small enough that the answer is exact. The
retrieval stage in this ADR is the design for when it is not.

## Alternatives considered

Pure vector search (fails on exact metadata), pure keyword search
(misses paraphrases), or embedding the whole corpus on every event (wasteful
and slow).
