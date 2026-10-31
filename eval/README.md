# Evaluation

```
eval/
├── datasets/peps-v1/golden.json    golden QA set (versioned; schema in src/archagenticrag/evaluation/dataset.py)
├── datasets/peps-v1/qrels/         chunk/document relevance labels per Qdrant collection (build_qrels.py)
├── configs/*.yaml                  one versioned config per experiment
├── experiments.yaml                experiment registry: run names -> lab experiments 01-11 and controls
├── pricing.yaml                    optional price book (documented prices only; empty = cost null)
├── runners/
│   ├── validate_dataset.py         checks the schema, and that every evidence quote exists in the corpus
│   ├── sync_langfuse_dataset.py    uploads the golden set to Langfuse (idempotent)
│   ├── build_qrels.py              derives relevance labels from the evidence quotes (no LLM)
│   ├── run_eval.py                 preflight → Langfuse run_experiment → Ragas scores → results/ [--defer-judge]
│   ├── resume_eval.py              finishes a run that stopped part-way (e.g. a daily quota)
│   └── benchmark.py                compares runs: ranking metrics, Ragas metrics, latency, cost [--all]
└── results/<run_id>/               manifest.json, config.yaml, items.jsonl, summary.json
```

## Contract for the system under test

`target.factory` in the config names a function `build_graph(system: dict, **kwargs)` that returns anything with `invoke` or `ainvoke` (a compiled LangGraph graph qualifies).

- **Input:** `{"question": str}`.
- **Output:** `{"answer": str, "documents": list[Document] | list[str]}`.
- **Document ids:** the doc id is taken from `Document.metadata["doc_id"]`, `["source"]` or `["file_path"]`, using the file stem (for example `pep-0484`). It is needed for the source-document recall check.
- **Callbacks:** pass `config` through to retrievers and models, so LangChain callbacks can count tokens, LLM calls and retriever time.

## Reproducibility

The run id is `<UTC timestamp>-<run_name>-<config fingerprint>-<random>`. `manifest.json` records:

- the git commit and dirty flag (or why git was unavailable)
- the Python and platform versions, and the versions of the evaluation packages
- the full config and its fingerprint
- the dataset version and sha256
- the corpus id, source commit and manifest hash

Re-running the same config against the same commit, dataset and pinned packages reproduces the run, up to LLM non-determinism.

## Resuming a run (free-tier quotas)

A full Ragas pass over the 42 questions needs roughly 800k–1M judge tokens. Groq's free tier allows 200,000 tokens per day per model, so one session cannot finish it. When a run stops part-way:

```bash
python eval/runners/resume_eval.py eval/results/<run_id>
```

What the resume command does:

- Keeps every recorded answer, context and metric value.
- Re-runs only failed system calls and re-scores only metrics that have no value.
- Saves after every item.
- Stops at the first *daily*-quota error. Run it again after the quota resets.
- Uses the run's own `config.yaml`, and refuses to continue if the golden dataset changed.
- Appends each session (time, git state, what was redone) to `manifest["resumes"]`.

## Comparing experiments (Phase 3.0)

```bash
python eval/runners/run_eval.py eval/configs/<experiment>.yaml --defer-judge   # answers + retrieval, no judge
python eval/runners/benchmark.py --all                                          # every experiment, NOT RUN included
python eval/runners/resume_eval.py eval/results/<run_id>                        # judge later, one quota day at a time
```

Each item records `retrieval_results` (final ranked contexts: rank, doc_id, chunk_id, score or null, method) and `retrieval_calls` (every retriever call with latency). Ranking metrics (Recall@K, MRR, nDCG) use the qrels and need no judge. Details: [docs/PHASE-3.0-EXPERIMENT-LAB.md](../docs/PHASE-3.0-EXPERIMENT-LAB.md).

## Environment variables

| Variable | Used for |
|---|---|
| `GEMINI_API_KEY` / `OPENROUTER_API_KEY` / `NVIDIA_API_KEY` / `XAI_API_KEY` / `GROQ_API_KEY` / `OPENAI_API_KEY` | Provider named in the config |
| `CEREBRAS_API_KEY` / `SAMBANOVA_API_KEY` / `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | Optional fallback providers ([docs/MULTI-PROVIDER-FALLBACK.md](../docs/MULTI-PROVIDER-FALLBACK.md)) |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Only when `langfuse.enabled: true` (also turns on graph/retrieval/LLM tracing) |
| `RAGAS_DO_NOT_TRACK` | Defaults to `true` (set by the runner) |
