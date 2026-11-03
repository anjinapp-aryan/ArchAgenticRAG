---
name: experiment-design
description: "Use when designing or reviewing an ArchAgenticRAG experiment (for example hybrid retrieval, reranking, query rewrite, CRAG, GraphRAG). Enforces hypothesis, control, one independent variable, controlled variables, metrics per layer, two-tier evaluation and a decision rule, and keeps retrieval results apart from answer-quality results."
---

# experiment-design

## Purpose
Make an experiment interpretable before it runs. Rules and the frozen-artifact register: `docs/ai-development/EXPERIMENT_RULES.md`.

## When to use
Before implementing an experiment, and when reviewing one. Pair with `reuse-audit` and `architecture-review`.

## Inputs
The idea; the control (default: experiment 01, then the best earlier experiment if relevant); the results that motivated it.

## Workflow
1. **Hypothesis** with evidence from earlier reports, stated so it can fail.
2. **Control.** Name the experiment and run it is compared with.
3. **One independent variable.** If two things must change (for example candidate depth and a reranker), document the coupling and plan a diagnostic that separates them.
4. **Controlled variables.** Walk the checklist in `EXPERIMENT_RULES.md` and confirm each is identical. Create the config as a copy of the control with a commented diff, plus a test that pins the diff.
5. **Layers.** State which of candidate retrieval, ranking, generation and answer evaluation the experiment touches, and the metric for each. Candidate recall and final recall are separate numbers.
6. **Tiers.** Tier 1: all 42 questions, `--defer-judge`, ranking metrics. Tier 2 (Ragas): only after Tier 1 is accepted and the user approves.
7. **Comparison.** Paired items, chunk and document level, wins/ties/losses, categories A–G, sign test, repeat variance if retrieval is non-deterministic.
8. **Pre-register** anything tunable (model, thresholds, depth, cut-offs) before looking at quality metrics.
9. **Decision rule.** Define WIN, MIXED, NO IMPROVEMENT and REGRESSION for the primary metrics in advance, at the retrieval or the answer level.
10. **Deliverables.** Audit doc if needed, config, registry entry in `eval/experiments.yaml`, report using the section template.

## Required checks
- The frozen artifacts in the register are untouched (verify, do not assume).
- The same generator, prompt, provider strategy and judge as the control.
- Diagnostics are labelled and never replace the official run.

## Output
A one-page design: hypothesis, control, variable, controlled-variables table, metrics per layer, tiers, decision rule, files to create, risks.

## STOP
- More than one uncontrolled variable.
- Anything would change a frozen artifact.
- Judge quota would be spent without the user asking.
- The next experiment would start before the current one has a decision.
