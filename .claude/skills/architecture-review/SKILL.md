---
name: architecture-review
description: "Use before a structural change in ArchAgenticRAG: a new module, interface, config field, graph, retriever composition, provider hook or dependency direction. Finds the smallest compatible design and returns GO, GO WITH CONDITIONS or NO-GO. Prohibits unnecessary rewrites. For finished diffs use change-review instead."
---

# architecture-review

## Purpose
Fit a change into the existing architecture with the least disturbance. Rules: `docs/ai-development/ARCHITECTURE_RULES.md`.

## When to use
Before implementing anything that adds or moves code structure, config fields, graph nodes or dependencies; after `reuse-audit` picked an option.

## Inputs
The reuse-audit decision; the area of the code involved; the experiment or baseline that must stay reproducible.

## Workflow
1. **Trace the current flow** for the area (question → retriever → Qdrant → documents → graph state → generator → trace → metrics). Name the files and functions.
2. **Place the change** using the "Where a change goes" table in `ARCHITECTURE_RULES.md`. Query-side logic is a graph node; ranked-list logic is retriever composition; index changes need a new collection and qrels; provider logic stays in `providers.py` and `provider_fallback.py`.
3. **Check dependency direction.** `evaluation/` must not import `graphs/` or `rag/`; graphs must not know about providers' fallback, the judge or ranking metrics.
4. **Check contracts** that other code or stored data depends on: `build_graph(system) -> graph`, the `question`/`answer`/`documents` keys, trace fields, manifest keys, factory strings, collection and `run_name` names.
5. **Check baseline impact.** Print the baseline fingerprint before and after the design; a new optional config field must be excluded from `EvalConfig.fingerprint()` while unset.
6. **Check testability.** How is it tested offline (fake LLM, fake embeddings, in-memory Qdrant)? What needs real Qdrant?
7. **List the files touched.** Flag every move, rename or rewrite.

## Required checks
- No `RAGExperiment` class, no `common/`/`experiments/` reorganisation, no file moves for tidiness.
- A new abstraction has at least two current callers.
- The change is additive: existing tests stay as they are.

## Output
`GO`, `GO WITH CONDITIONS` or `NO-GO`; the placement; the files touched; the contracts checked; the tests planned; the risks. Do not implement.

## STOP
- The design needs a major rewrite or changes a frozen contract: NO-GO and report why.
- The baseline fingerprint would change.
- A custom build is proposed for something reusable: back to `reuse-audit`.
