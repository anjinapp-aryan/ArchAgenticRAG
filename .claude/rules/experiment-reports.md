---
paths:
  - "docs/EXPERIMENT-*.md"
  - "docs/PHASE-*.md"
---

# Experiment reports

Loaded when you read or edit a report. Procedure: `experiment-design` skill. Template: `docs/EXPERIMENT-02-HYBRID-RETRIEVAL.md`. Rules: `docs/ai-development/EXPERIMENT_RULES.md`.

- Numbers come from `benchmark.py` output or the run files, not from memory. State the item set and which items were excluded and why.
- Say which level a decision is about (retrieval or answer). A retrieval WIN or REGRESSION is not an answer-quality result; if answers are unjudged, write NOT RUN.
- Use the decision words WIN, MIXED, NO IMPROVEMENT, REGRESSION, and state whether the difference is statistically supported.
- Label diagnostics as diagnostics. Record every pre-registered choice and any deviation.
- Do not edit the report of a finished experiment to change its conclusion; add a dated note instead.
