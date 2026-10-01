# Phase 2: Evaluation Reuse Audit

Date: 2026-10-01. This audit re-checks the Phase 0 evaluation choices before any evaluation code was written.

**How things were verified**

| Tag | Meaning |
|---|---|
| **[PYPI]** | Version, release date and Python range taken from the PyPI JSON API. |
| **[GH]** | License, stars, last push and archived flag taken from the GitHub REST API. |
| **[INSTALLED]** | Package installed in a clean Python 3.12 venv and its API inspected or executed. |
| **[DOC]** | Taken from vendor documentation only. |

## 1. Summary

| Framework | Decision | One-line reason |
|---|---|---|
| **Ragas 0.4.3** | **REUSE** (primary metrics) | It is the only library with the four required RAG metrics as maintained, non-deprecated objects. **Caveats:** the repo has been frozen since 2026-02-24, and the latest release is incompatible with the latest langchain-community. |
| **Langfuse 4.16.0 (SDK)** | **REUSE** (runner + dataset store) | `run_experiment()` already provides the experiment loop, concurrency, per-item and run-level evaluators, and dataset linking. We wrote no runner loop of our own. |
| **DeepEval 4.2.7** | **REFERENCE** (not installed in Phase 2) | Its RAG metrics duplicate Ragas one for one. Telemetry is on by default. Keep it as the designated fallback if Ragas breaks, and for CI gates in Phase 9. |
| **FlashRAG** | **REFERENCE** (Phase 8 benchmarks) | The repo is active, but the PyPI package (`flashrag-dev` 0.1.2) dates from 2024-10. Its value is its benchmark datasets, not its library. |
| Opik (Comet) | REFERENCE | Active and Apache-2.0, but it overlaps Langfuse (datasets, experiments, UI) and would be a second platform. |
| TruLens | REFERENCE | Active and MIT, but its RAG triad overlaps Ragas. |
| MLflow GenAI evaluate | REFERENCE | Apache-2.0 and capable, but it brings the MLflow platform. Not needed. |
| Phoenix evals | REJECT | Elastic License 2.0 (not OSI). Already rejected in Phase 0. |
| promptfoo | REJECT | Node-first. The Python package is a thin wrapper. Wrong fit for a Python harness. |
| RAGChecker | REJECT | No push since 2024-12-13, and the last release was 2024-09. |
| continuous-eval | REJECT | Requires Python <3.13, and the last release was 2025-01. |
| BEIR | REFERENCE | Retrieval-only benchmarks. No push since 2025-10-16. |

**Phase 0 decisions revalidated:** Ragas and Langfuse are kept. DeepEval is downgraded from COMPOSE to REFERENCE for this phase (reasons in §3). FlashRAG stays deferred to Phase 8.

## 2. Verified facts

### 2.1 Package and repository status

| Package | Latest version (release date) [PYPI] | Python [PYPI] | License [GH] | Stars [GH] | Last push [GH] |
|---|---|---|---|---|---|
| ragas | 0.4.3 (2026-01-13) | >=3.9 | Apache-2.0 | 15,892 | **2026-02-24** |
| deepeval | 4.2.7 (2026-09-29) | >=3.9,<4.0 | Apache-2.0 | 18,525 | 2026-09-29 |
| langfuse (Python SDK) | 4.16.0 (2026-09-30) | >=3.10,<4.0 | MIT (SDK repo) | 495 (SDK) / 35,244 (server) | 2026-09-30 |
| flashrag-dev | 0.1.2 (2024-10-29) | >=3.9 | MIT | 3,587 | 2026-10-01 |
| trulens | 2.14.0 (2026-09-03) | >=3.10,<4.0 | MIT | 3,579 | 2026-09-30 |
| opik | 2.2.86 (2026-09-30) | >=3.10 | Apache-2.0 | 22,314 | 2026-10-01 |
| arize-phoenix-evals | 3.9.0 (2026-09-21) | >=3.10,<3.15 | Elastic-2.0 | 11,668 | 2026-10-01 |
| mlflow | 3.16.1 (2026-09-16) | >=3.10 | Apache-2.0 | 28,205 | 2026-10-01 |
| promptfoo (Python) | 0.2.0 (2026-09-18) | >=3.10 | MIT | 25,602 | 2026-10-01 |
| ragchecker | 0.1.9 (2024-09-25) | >=3.9,<4.0 | Apache-2.0 | 1,124 | 2024-12-13 |
| continuous-eval | 0.3.14.post2 (2025-01-06) | >=3.10,**<3.13** | Apache-2.0 | 517 | 2026-08-10 |
| beir | — | — | Apache-2.0 | 2,305 | 2025-10-16 |

### 2.2 Ragas: compatibility findings [INSTALLED]

1. **The latest Ragas fails to import against the latest langchain-community.** On a fresh install (ragas 0.4.3, langchain 1.4.3, langchain-core 1.6.6, langchain-community 0.4.2), this failed:
   ```
   import ragas
   ModuleNotFoundError: No module named 'langchain_community.chat_models.vertexai'
   ```
   `ragas/llms/base.py` line 12 imports a module that langchain-community 0.4 removed. **Workaround verified:** pin `langchain-community>=0.3.31,<0.4`. `uv pip check` then reports all packages compatible, and ragas 0.4.3 imports and runs alongside langchain-core 1.6.6.
2. **Repository activity has stopped.** The last commit is 2026-02-24, there are 621 open issues, and the repo moved from `explodinggradients/ragas` to `vibrantlabsai/ragas`. Nobody has fixed the incompatibility above. This is the main risk of the evaluation stack (see ADR 008).
3. **The API is in transition.** Importing `Faithfulness` etc. from `ragas.metrics` emits *"deprecated and will be removed in v1.0. Please use 'ragas.metrics.collections'"*. We use **`ragas.metrics.collections`** only. These metrics take an `InstructorBaseRagasLLM` from `ragas.llms.llm_factory(model, provider="openai", client=AsyncOpenAI(...))`.
4. **These metrics exist in 0.4.3, with the inputs they need:**

   | Our name | Ragas class (`ragas.metrics.collections`) | `ascore` inputs | Needs |
   |---|---|---|---|
   | faithfulness | `Faithfulness` | user_input, response, retrieved_contexts | LLM |
   | answer_relevancy | `AnswerRelevancy` | user_input, response | LLM + **embeddings** |
   | context_precision | `ContextPrecisionWithReference` | user_input, reference, retrieved_contexts | LLM + reference |
   | context_recall | `ContextRecall` | user_input, retrieved_contexts, reference | LLM + reference |
   | answer_correctness | `FactualCorrectness(mode="recall")` | response, reference | LLM + reference |
   | abstention, clarification | `ragas.metrics.DiscreteMetric` (custom criterion, Ragas engine) | llm, user_input, response | LLM |

   `answer_correctness` was added because none of the four requested metrics compares the answer with the ground truth. `abstention` and `clarification` were added because out-of-corpus and ambiguous questions need a behavioural judgement. Ragas has no built-in metric for either.
5. **Telemetry is on by default.** `ragas/_analytics.py` posts usage events to `https://t.explodinggradients.com` unless `RAGAS_DO_NOT_TRACK=true`. Our runner sets that by default.
6. **Judge defaults.** `InstructorModelArgs` defaults to temperature 0.01, top_p 0.1 and max_tokens 1024. These are recorded through the package version pin.

### 2.3 Langfuse: SDK capabilities [INSTALLED]

- `Langfuse.create_dataset`, `create_dataset_item(id=...)` (an upsert with a stable id), `get_dataset(name)`, `DatasetClient.run_experiment`, `Langfuse.run_experiment(data=[local items])` and `create_score` all exist in 4.16.0.
- **`run_experiment` works fully offline** with `tracing_enabled=False`. A probe ran a task, per-item evaluators and run-level evaluators locally. So one code path serves both "no server yet" and "self-hosted server".
- **Pitfall found in the source** (`langfuse/_client/client.py`, `langfuse/experiment.py`): an item whose task raises is *logged and dropped* from the results (`asyncio.gather(..., return_exceptions=True)` followed by a filter). An evaluator that raises is *logged and returns no scores*. A naïve integration would silently shrink the dataset. Our wrappers catch and record both, and the run aborts if any golden item is missing.
- **Not verified:** server-side behaviour (dataset UI, experiment comparison, score storage) on a self-hosted Langfuse server. Docker Desktop was not running on this machine, so no server was started. The integration (`eval/runners/sync_langfuse_dataset.py`, `langfuse.enabled: true`) is implemented and unit-tested only against the offline client.

### 2.4 DeepEval [INSTALLED]

- It exposes `FaithfulnessMetric`, `AnswerRelevancyMetric`, `ContextualPrecisionMetric`, `ContextualRecallMetric`, `ContextualRelevancyMetric`, `HallucinationMetric` and G-Eval/DAG custom metrics, plus about 50 agent, multimodal and safety metrics.
- It pulls in pytest plugins (`pytest-xdist`, `pytest-rerunfailures`, `pytest-repeat`), gRPC, OpenTelemetry and PostHog.
- **Telemetry is on by default.** `deepeval/config/settings.py` defines `DEEPEVAL_TELEMETRY_OPT_OUT` (truthy turns it off), and `deepeval/telemetry/client.py` uses PostHog.

### 2.5 Model providers [checked endpoints]

All of the user's providers expose OpenAI-compatible endpoints, so one `AsyncOpenAI` client type covers the system under test and the Ragas judge:

| Provider | Base URL | Check |
|---|---|---|
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | [DOC] ai.google.dev/gemini-api/docs/openai: chat, embeddings, models and structured outputs supported. `/models` without a key returned 404. |
| OpenRouter | `https://openrouter.ai/api/v1` | `/models` returned 200 (462 models) |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | `/models` returned 200 (81 models, including embedding models) |
| xAI (Grok) | `https://api.x.ai/v1` | Returned 401 without a key (endpoint exists) |
| Groq | `https://api.groq.com/openai/v1` | Returned 401 without a key (endpoint exists) |

No provider API keys were present in the environment, so no model call was made in Phase 2.

## 3. Decisions in detail

### Ragas: REUSE, with a pin and a fallback

- **For:** it has all required metrics plus FactualCorrectness and DiscreteMetric, it is Apache-2.0, and it is the de-facto vocabulary in RAG papers and posts, which helps a portfolio project.
- **Against:** the repo is frozen and the release breaks against current langchain-community.
- **Mitigation:**
  - Pin `ragas==0.4.3` and `langchain-community<0.4`.
  - Only use the `collections` API.
  - Keep all Ragas calls inside `metrics.py`, so a swap to DeepEval touches one module.
  - The fallback trigger is defined in ADR 008.

### Langfuse: REUSE as runner and dataset store

`run_experiment` covers what we would otherwise have built: the iteration loop, concurrency control, evaluator plumbing, and dataset/run linking in the UI. Our glue adds three things it lacks: error recording, the run manifest, and JSON results on disk.

### DeepEval: REFERENCE (deferred)

- **Ragas measures:** answer grounding (faithfulness), answer relevance, retrieval precision/recall against a reference, and answer correctness against a reference.
- **DeepEval measures:** the same four RAG properties (`Faithfulness`, `AnswerRelevancy`, `ContextualPrecision`, `ContextualRecall`). On top of those it adds G-Eval/DAG custom rubrics, hallucination, safety and agent metrics, and a pytest runner.
- **Overlap:** 100% for the Phase 2 metric set.
- **Why not both now:** running both would double judge cost and give two numbers for the same property with no way to say which is right. That is metric duplication, which the phase brief forbids.
- **When DeepEval comes in:**
  1. Phase 9 CI regression gates (`assert_test` with thresholds), or
  2. If the Ragas fallback trigger fires, or
  3. Phase 6/7 agent metrics (`ToolCorrectnessMetric`, `TaskCompletionMetric`), which Ragas only partially covers.

### FlashRAG / BEIR: REFERENCE (Phase 8)

Our corpus is domain-specific (PEPs) and the golden set is hand-built and traceable. Public multi-hop benchmarks (HotpotQA, 2Wiki) are useful later for comparing against published numbers. They are not needed for the baseline.

## 4. What we did not build

- No metric implementation. Every score comes from a Ragas class.
- No experiment loop or concurrency code. `Langfuse.run_experiment` provides it.
- No results database. Results are plain JSON files plus Langfuse when enabled.
- No token counting. LangChain's `UsageMetadataCallbackHandler` provides it.

**Custom code we did write** (glue: 1,169 lines in `src/archagenticrag/evaluation/` including docstrings and comments, plus 124 lines of CLI runners):

- Dataset schema and evidence verification.
- Config schema.
- Target adapter.
- A 20-line callback that times retrievers and counts LLM calls.
- Failure triage rules.
- Summary aggregation.
- File persistence.
