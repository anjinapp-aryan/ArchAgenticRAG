---
name: evaluation
description: "Use when running, resuming, judging, comparing or interpreting evaluations in ArchAgenticRAG: run_eval, resume_eval, benchmark, qrels, Ragas, Groq judge quota. Uses the existing two-layer evaluation (ranking metrics and Ragas) and never builds a second framework or spends judge quota unasked."
---

# evaluation

## Purpose
Run and read evaluations with the project's own tools. Details: `eval/README.md`, `docs/PHASE-3.0-EXPERIMENT-LAB.md`, `docs/PHASE-2-BASELINE-RESULTS.md`.

## When to use
Any run, resume, comparison or metric question. Pair with `experiment-design` for new experiments and `data-retention` for artifacts.

## Inputs
The config or run directory; the comparison set; whether the user approved judging.

## Workflow
1. **Check prerequisites:** Qdrant up for the collection the config names; the collection exists; qrels exist for it (`eval/datasets/peps-v1/qrels/<collection>.json`, else `build_qrels.py`).
2. **Tier 1 run:** `run_eval.py <config> --defer-judge`. Items that fail on rate limits are retried with `resume_eval.py <run> --no-judge`. Do not run other quota-consuming work meanwhile.
3. **Compare:** `benchmark.py --all`, or `--experiments 01 02 --baseline 01` with `--json`. Do not hand-compute comparisons: the benchmark pairs items, adds chunk and document level, candidate-stage metrics and wins/ties/losses.
4. **Tier 2 (Ragas):** only when the user asks. `resume_eval.py <run>` judges what is pending, stops at the daily quota (or `PROVIDER_EXHAUSTED`) and is run again the next day. The judge is Groq `qwen/qwen3.8-27b` at about 200k tokens a day, so a full run takes days. Do not change the judge or Ragas settings.
5. **Interpret:** keep retrieval and answer results apart; `NOT RUN` is a state, never zero; Ragas means are comparable only at similar `n`; report which items were excluded and why.

## Required checks
- Sanity: the baseline row of `benchmark.py --all` still reads 27/42 pass, faithfulness 0.847 (n=34), correctness 0.724 (n=30).
- Dataset and corpus hashes match the manifests (`resume_eval` enforces this), and `python .claude/hooks/guard.py verify` reports no MISMATCH before and after.
- Fallback runs are labelled as multi-provider (`provider-development`).
- A run directory is never edited by hand; a changed config means a new run.

## Output
Tables from `benchmark.py` with the paired item set and exclusions stated, status per run (`COMPLETE`, `IN PROGRESS`, `RETRIEVAL ONLY`, `FAILED`, `NOT RUN`), and judge usage (none, or items judged and where it stopped).

## STOP
- The dataset, corpus or qrels hash changed, or the baseline row no longer reproduces.
- Judging would start without the user's request.
- A second evaluation framework or a different judge is proposed.
- Compared runs differ in anything except the declared variable.
