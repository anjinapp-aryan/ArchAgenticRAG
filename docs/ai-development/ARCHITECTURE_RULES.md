# Architecture rules

What an agent must know about this codebase's shape before changing it. Verified against the code on 2026-11-03; if the code disagrees with this file, the code wins and this file needs a fix.

## Layers and dependency direction

```text
provider_fallback.py   leaf: httpx transport for opt-in fallback
providers.py           provider presets, ProviderStrategy, client builders
rag/                   settings, ingestion, Qdrant store, rerank adapter
graphs/                LangGraph graphs (basic_rag, decompose_rag)
evaluation/            config, runner, target adapter, metrics, ranking, benchmark
eval/runners/          CLI entry points (outside the package)
```

- `graphs/` imports `rag/` and `providers`. `rag/` imports `providers`. `providers` imports `provider_fallback` lazily.
- `evaluation/` imports `providers` and `provider_fallback` only. It **never imports `graphs/` or `rag/`**: it loads the system under test from the string in `target.factory` (`module:function`).
- One accepted exception: `rag/ingest.py` (a CLI) reads the run config through `evaluation.config`. Do not add more.
- Graphs never know about provider fallback, ranking metrics, Langfuse or the judge.

## The experiment contract

```python
build_graph(system: dict, *, client=None, embeddings=None, llm=None, ...) -> compiled graph
# input  {"question": str}
# output {"answer": str, "documents": list[Document]}   # metadata has doc_id and chunk_id
# graph.eval_metadata: dict recorded in the run manifest
```

- **The graph is the unit of an experiment.** Do not introduce a mandatory `RAGExperiment` class, a `common/` + `experiments/` reorganisation, or per-experiment evaluators. Loops and conditional edges (CRAG, Self-RAG, agents) must remain expressible in a graph.
- Extra graph state worth recording is listed in `target.record_keys` in the config, not hard-coded in the runner.
- The baseline manifest records `archagenticrag.graphs.basic_rag:build_graph`. **Do not move or rename modules, functions, collections or `run_name`s that manifests, configs or `eval/experiments.yaml` reference.**

## Where a change goes

| Kind of change | Where | Example |
|---|---|---|
| Rewrites or splits the question | A graph node | `graphs/decompose_rag.py` |
| Re-ranks or re-fuses a ranked list | Retriever composition in `make_retriever` (`graphs/basic_rag.py`), below the graph | hybrid labelling, `rag/rerank.py` with `ContextualCompressionRetriever` |
| Changes what is indexed | New ingestion recipe, **new collection**, then `build_qrels.py` for it | `peps_v1_..._hybrid_bm25` |
| Provider, retry or fallback logic | `providers.py`, `provider_fallback.py` only | `ProviderStrategy` |
| New metric or comparison | `evaluation/ranking.py`, `benchmark.py` | candidate-stage metrics |
| New setting | Pydantic model in `rag/settings.py` (and `evaluation/config.py` if it is run-level) | `candidate_k`, `reranker` |

## Config rules

- Settings models are strict (`extra="forbid"`); validate combinations in a `model_validator`.
- **A new optional field must not change existing fingerprints.** `EvalConfig.fingerprint()` drops fields that are unset; add the new field to that list. A test pins the baseline fingerprint, and each experiment has a config-diff test that fixes exactly which keys differ from its control.
- Each experiment gets its own YAML in `eval/configs/`, copied from its control with a commented diff, and its own entry in `eval/experiments.yaml`.

## Minimal-change rules

- Add, do not rewrite. Prefer composing installed components over a new abstraction; introduce an abstraction only when two current callers need it.
- No moves, renames or reformatting of untouched files.
- A change that cannot be tested offline (fake LLM, fake embeddings, in-memory Qdrant) needs a stated reason.

## Hazards

- `index_documents` recreates its collection by default, and `python -m archagenticrag.rag.ingest <cfg>` calls it. Running ingestion with the baseline or any earlier experiment's config deletes that index. It refuses only a retrieval-mode mismatch.
- Hybrid (RRF) retrieval has exact score ties, so its ordering is not deterministic between calls. Dense retrieval is. Experiments that use hybrid must measure repeat variance (`EXPERIMENT_RULES.md`).
- `onnxruntime-gpu` would replace the CPU runtime the frozen embeddings use. Do not install it without an explicit decision.
