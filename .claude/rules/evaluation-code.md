---
paths:
  - "eval/runners/**"
  - "src/archagenticrag/evaluation/**"
  - "eval/README.md"
---

# Evaluation code

Loaded when you read or edit evaluation code. Procedure: `evaluation` skill. Rules: `docs/ai-development/EXPERIMENT_RULES.md`.

- Evaluation behaviour is part of the experiment. Changing a metric, the judge, the pairing rule or a record field changes what old and new runs mean. Make such a change additive and optional, and keep `benchmark.py` able to read old runs.
- A run directory is evidence. Code may append to it through `resume_eval`; nothing edits it by hand, and `write_run` must keep refusing to overwrite.
- Ranking metrics and Ragas answer metrics stay separate in code and in output.
- Fallback and judge-deferral are run-level facts: record them in the manifest or item records, never infer them.
- After changing anything here, run `python .claude/hooks/guard.py verify` and the offline tests; the baseline row of `benchmark.py --all` must still read as documented in the `evaluation` skill.
