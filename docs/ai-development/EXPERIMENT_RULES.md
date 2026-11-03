# Experiment rules

Experiments and baselines are scientific artifacts. The procedure for designing one is the `experiment-design` skill; this file holds the rules and the register of what is frozen.

## Every experiment states

Hypothesis · baseline (control) · independent variable · controlled variables · dataset · metrics · reproducibility · results · decision · limitations. Controlled variables to check every time: corpus, chunking, collection, embedding model, delivered `top_k`, dataset, qrels, generator model and temperature, prompt, judge, provider strategy.

## Files an experiment produces

| Step | File |
|---|---|
| Audit and design, when reuse or architecture is uncertain | `docs/EXPERIMENT-NN-<name>-AUDIT.md` ending in GO / GO WITH CONDITIONS / NO-GO |
| Config, copied from its control with a commented diff, plus a test pinning the diff | `eval/configs/expNN-<name>.yaml` |
| Registry entry | `eval/experiments.yaml` (`run_names`, `config`, `report`) |
| Report | `docs/EXPERIMENT-NN-<name>.md` |

Report sections (template: `docs/EXPERIMENT-02-HYBRID-RETRIEVAL.md`): research question · hypothesis · reuse audit · control configuration · treatment configuration · variables held constant · variables changed · index design · instrumentation · methodology · full results (chunk and document level) · category results · baseline comparison · interpretation · limitations · decision.

## Layers are never conflated

| Layer | Question | Evidence |
|---|---|---|
| Candidate retrieval | Is the evidence anywhere in the pool? | Recall@K on the candidate stage |
| Ranking | Is it in the final `top_k` and how high? | Recall@K, MRR, nDCG on `retrieval_results`, chunk and document level |
| Generation | Did the generator use it? | Ragas faithfulness, answer relevancy |
| Answer evaluation | Is the answer right? | Ragas correctness, abstention, clarification |

A retrieval WIN is not an answer WIN, and a retrieval REGRESSION is not an answer REGRESSION. Say which level a decision is about.

## Tiers

- **Tier 1, always:** all 42 questions with `--defer-judge`. Ranking metrics, latency, tokens. No judge quota.
- **Tier 2, only after Tier 1 is accepted and the user approves:** Ragas through `resume_eval.py`, one quota-day at a time, with the unchanged judge.

## Comparing runs

- **Paired items.** Compare only items no compared run failed on with a system error, and list the excluded ones. Do not count a provider error as a retrieval miss. `benchmark.py` pairs automatically.
- **Both levels, per item.** Report chunk and document level, wins/ties/losses per item, categories A–G, and a sign test. D (ambiguous) and E (out of corpus) are examined separately because they lack answerable labels.
- **Variance.** If retrieval can vary between calls (hybrid RRF ties), measure repeats and compare against the range, not only the recorded run.
- **Small n.** The golden set has 31 answerable items; most differences are not significant. Say so.
- **Latency** measured on different days or provider load is context, not a result.

## Pre-registration and diagnostics

- Fix anything that could be tuned to the outcome (model choice, thresholds, candidate depth, cut-offs) and record it **before** looking at quality metrics. Precedent: the Experiment 03 latency gate chose the reranker.
- Extra probes are labelled **diagnostic**, never replace the official result, and are never tuned to the golden set.

## Decision vocabulary

| Decision | Meaning |
|---|---|
| WIN | Material improvement on the primary metrics without unacceptable regression elsewhere |
| MIXED | Some metrics or categories improve, others do not; say which |
| NO IMPROVEMENT | Effectively unchanged |
| REGRESSION | Materially worse |

State level (retrieval or answer), the control, and whether the difference is statistically supported. Do not force a positive conclusion.

## Run hygiene

- Official run IDs include the config fingerprint; a run directory is never overwritten. A changed config is a new fingerprint and a new run.
- The manifest records the git commit and a dirty flag. Prefer a committed tree for official runs; if it was dirty, say so in the report.
- Do not run other quota-consuming work (live tests, judge resumes) while an official run is generating; it causes rate-limit errors.
- Retry failed system calls with `resume_eval.py --no-judge`: same provider and model, no judge.

## Frozen artifact register

Changing any of these needs an explicit instruction. If one is changed on purpose, update this table in the same change. Verified 2026-11-03.

| Artifact | How to verify | Expected |
|---|---|---|
| Baseline config fingerprint | `.venv/Scripts/python -c "from archagenticrag.evaluation.config import load_config as l; print(l('eval/configs/baseline-basic-rag.yaml').fingerprint())"` (also pinned by a test) | `63bf3b5f990cc9e5` |
| Other fingerprints (same call, other config) | exp02 `690aff0c9e3997bd` · exp03 `532e86f37f018e05` · phase3-1 `d53636ae426cd64f` · control B1 `edde17323d8722cd` · control B2 `dc235c8ab5693621` | as listed |
| Baseline run `eval/results/20261001T173531Z-baseline-basic-rag-63bf3b5f-6227d9/` | `sha256sum config.yaml items.jsonl manifest.json summary.json` (gitignored, local only) | the four hashes listed below the table |
| `eval/datasets/peps-v1/golden.json` | `sha256sum` (also recorded in every manifest; `resume_eval` refuses a mismatch) | `18a359e928ae792fec9fcb74e11b2efce7338f520974a2c0f2c0ada0f270a520` |
| `data/corpus/peps/MANIFEST.json` | `sha256sum` | `b3f7f85b9c47e3784b682188e9f86f30a7c1828666ccc52879ee4a2885a9da03` |
| Qrels (`eval/datasets/peps-v1/qrels/*.json`) | git diff; integration tests compare their chunk catalogs with the live collections | unchanged |
| Baseline collection `peps_v1_bge_small_docling_480` | integration tests; `curl -s localhost:6333/collections/<name>` | 455 points, `indexed_at` `2026-10-01T14:31:48` |

Baseline run hashes: `fd510ab9e3919f3d675eaae4224954b3b18a3f7b67a6f2f0a9c99a55094ce609` (config.yaml), `a4db3e3ebc77a31e101e7d0c7b2e88034dfb1fdea7837415b536619fc4e8e066` (items.jsonl), `a13d28572060e603641d0288273db266215e22563e884b3a1b887af5978483e4` (manifest.json), `434880a4dad0aef86b498cb87dd302f3d6153e23a96b38068d979429e2480cf2` (summary.json).
