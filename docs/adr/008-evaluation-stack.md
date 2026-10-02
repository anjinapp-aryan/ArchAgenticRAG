# ADR 008: Evaluation stack

- **Status:** Accepted (pending architectural review after Phase 2)
- **Date:** 2026-10-01
- **Note on numbering:** ADRs 001–007 were expected from Phase 1, but they are not in this repository. The number 008 follows the Phase 2 brief.

## Context

We need a trustworthy, reproducible measure of the Basic RAG baseline before building agentic patterns. Later patterns (CRAG, adaptive routing, reflection, multi-agent) will be judged by their delta against this baseline. That makes the evaluation stack a long-lived dependency.

The project rule is REUSE → ADAPT → COMPOSE → REFERENCE → BUILD: no home-grown evaluator where a maintained one exists.

## Options considered

| Option | Verdict |
|---|---|
| Ragas (metrics) | Chosen for metrics |
| DeepEval (metrics + pytest runner) | Deferred (fallback, and CI gates in Phase 9) |
| Langfuse (datasets + experiments + traces) | Chosen for runner and dataset store |
| Opik (datasets + experiments + metrics) | Rejected. It is a second observability platform next to Langfuse. |
| TruLens, MLflow GenAI evaluate | Rejected. Overlap with plenty already chosen. |
| Phoenix evals | Rejected. Elastic License 2.0. |
| RAGChecker, continuous-eval | Rejected. Inactive, and continuous-eval does not support Python ≥3.13. |
| Write our own LLM-judge prompts | Rejected. This is the anti-pattern found in the Backblaze starter kit in Phase 0. |

Full evidence is in [docs/research/PHASE-2-EVALUATION-REUSE-AUDIT.md](../research/PHASE-2-EVALUATION-REUSE-AUDIT.md).

## Reuse audit (summary)

- **Ragas 0.4.3:** installed and inspected. All required metrics exist in the non-deprecated `ragas.metrics.collections` API. It imports only with `langchain-community<0.4`. The repo has been inactive since 2026-02-24.
- **Langfuse SDK 4.16.0:** installed and executed. `run_experiment` works offline and against a server. It silently drops failing items unless wrapped.
- **DeepEval 4.2.7:** installed and inspected. Its four RAG metrics overlap Ragas completely. Telemetry is on by default.

## Decision

1. **Metrics:** Ragas `ragas.metrics.collections`:
   - `Faithfulness`
   - `AnswerRelevancy`
   - `ContextPrecisionWithReference`
   - `ContextRecall`
   - `AnswerCorrectness(weights=[1, 0], beta=5)`, which we call answer_correctness (was `FactualCorrectness(mode="recall")`, see Amendment 1)
   - Two `DiscreteMetric` judgements: abstention (for out-of-corpus questions) and clarification (for ambiguous questions)
2. **Execution:** Langfuse `run_experiment()`.
   - Offline client (`tracing_enabled=False`) until the self-hosted stack runs.
   - Then `DatasetClient.run_experiment()` against the synced dataset, so runs, traces and scores are linked in Langfuse.
3. **Storage:**
   - Langfuse holds datasets and scores.
   - Each run also writes `eval/results/<run_id>/` (`manifest.json`, `config.yaml`, `items.jsonl`, `summary.json`) for git-friendly, offline-readable history.
4. **Pins:** `ragas==0.4.3`, `langchain-community>=0.3.31,<0.4`, `langfuse==4.16.0`.
5. **Telemetry:** the runner sets `RAGAS_DO_NOT_TRACK=true` by default.

## Why Ragas?

It is the only maintained-API library that ships all four requested RAG metrics plus answer correctness and custom discrete judgements. It is also the standard vocabulary in RAG literature, so our numbers stay comparable and explainable.

## Why DeepEval only later?

Its RAG metrics measure the same four properties. Running both doubles judge cost and gives two competing numbers for the same property. DeepEval's distinct value is pytest-style regression gates and agent/tool metrics, which become relevant in Phases 6, 7 and 9.

## Why Langfuse?

It was already chosen for tracing in Phase 0. Its dataset and experiment features remove the need for our own run loop, results database or comparison UI, and the same code path works offline.

## Why not build our own evaluator?

- **Judge prompts and claim decomposition are research problems.** Ragas' versions are published and studied. Ours would not be, and our scores would not be comparable with anyone else's.
- **Maintenance.** Owning metric code is the same "reinventing the wheel" cost that the project rule forbids.
- **What we did build is glue.** It is dataset validation, config, target adapter, failure triage rules and persistence. None of it computes a quality score.

## Consequences

- **Positive:**
  - Baseline numbers come from standard metrics.
  - Runs are reproducible: the manifest records git SHA, package versions, config fingerprint, dataset hash and corpus commit.
  - Switching metric libraries touches one module (`metrics.py`).
- **Negative:**
  - We carry a pin on an old langchain-community line.
  - Ragas judge calls cost money with API providers.
  - Judge-token usage is not captured: only system-under-test tokens are. Judge cost must be read from the provider dashboard.

## Known risks

| Risk | Mitigation / trigger |
|---|---|
| Ragas abandoned (no commit since 2026-02-24) | **Fallback trigger:** if Ragas has no new release by 2027-01-01, or our pins become uninstallable alongside the Phase 1 stack, swap `metrics.py` to DeepEval's equivalent metrics. Re-run the baseline with both libraries once to calibrate. |
| langchain-community <0.4 conflicts with Phase 1 dependencies | Detected at install time (`uv pip check`). If it happens, run evaluation in a separate venv/extra. |
| Judge = same model family as the generator → self-preference bias | Resolved in Amendment 1: generator `openai/gpt-oss-120b`, judge `qwen/qwen3.8-27b` (both served by Groq, different model families). |
| LLM-judge variance | Temperature is near 0 (Ragas default 0.01). Repeat runs are compared to measure variance before claiming deltas. |
| Failure triage thresholds are arbitrary | They are provisional, configurable and recorded per run. Labels are reviewed by hand for the baseline. |
| Langfuse server features not verified live | Run `sync_langfuse_dataset.py` and one experiment with `langfuse.enabled: true` when Docker is available, then update this ADR. |

## Amendment 1 (2026-10-01, Phase 1 baseline run)

### Judge model

The planned Gemini judge (`gemini-3.6-flash`) could not complete a run. The free tier allows 5 requests per minute, and the provider also returned intermittent 503 errors. NVIDIA NIM models timed out (60 s) or returned 404 for this account.

The judge is now Groq `qwen/qwen3.8-27b` at temperature 0. Judge embeddings for AnswerRelevancy stay on Gemini `gemini-embedding-001`.

- Qwen is a different model family from the generator (`openai/gpt-oss-120b`).
- Groq's free tier allows 8,000 tokens per minute per model, so a full run is slow, but it completes. The OpenAI SDK retries honour `retry-after`.

### answer_correctness metric

A smoke test with the new judge scored the correct answer to A01 ("79 characters") at **0.0**. The cause: `FactualCorrectness` decomposes the reference without seeing the question, so the reference "79 characters." became the claim "The text contains 79 characters.", which the judge rightly found unsupported. Many golden references are short noun phrases, so this would have produced false failures across the baseline.

Ragas' `AnswerCorrectness` passes the question to claim extraction and classification. It is configured to keep the original recall intent:

- `weights=[1.0, 0.0]`: the factuality term only. The embedding-similarity term is dropped.
- `beta=5.0`: F-beta favouring recall, so correct detail beyond a short ground truth is barely penalised.

Measured with the qwen judge on A01:

| Answer | FactualCorrectness (recall) | AnswerCorrectness default | AnswerCorrectness weights=[1,0], beta=5 |
|---|---|---|---|
| "The maximum line length is 79 characters." | 0.0 | 0.956 | 1.0 |
| "… 120 characters." (wrong) | 0.0 | 0.177 | 0.0 |
| Correct, plus extra true detail (72 for docstrings, 99 by agreement) | — | 0.466 | 0.897 |
| "The provided documents do not say." | — | 0.154 | 0.0 |

A05 with the ground truth as the answer scored 1.0. The metric is still Ragas code; only its documented parameters changed.

### Free-tier quota and resumable runs

The first full run on 2026-10-01 produced answers for 40 of 42 questions. It then exhausted the judge's daily quota (Groq, 200,000 tokens per day): 126 metric calls failed with `tokens per day (TPD)`. About 22,000 judge tokens are needed per answerable question, roughly 800k–1M for the full set.

The user chose to stay on the free tier, so runs are now resumable (`eval/runners/resume_eval.py`). A resume:

- keeps successful values;
- redoes only the failures;
- stops at a daily-quota error;
- logs each session in the manifest.

The judge model stays the same across sessions, so the scores remain comparable. The cost is wall-clock days.
