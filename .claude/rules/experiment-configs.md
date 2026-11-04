---
paths:
  - "eval/configs/**"
  - "eval/experiments.yaml"
---

# Experiment configs and registry

Loaded when you read or edit a config. Procedure: `experiment-design` skill.

- Every existing file in `eval/configs/` is frozen: its fingerprint is in `docs/ai-development/frozen-artifacts.json`. Editing one needs the user's authorisation, and the `guard.py` write hook will ask.
- A new experiment is a new file: copy its control, change only the independent variable, comment the difference, add a test that pins that exact diff (pattern: `tests/rag/test_rerank.py`), and add its entry to `eval/experiments.yaml` (`run_names`, `config`, `report`).
- Add the new fingerprint to `frozen-artifacts.json` only after its run is final.
- Reading an index built for another config is fine; running ingestion with a config recreates that config's collection. Check the collection name before any ingestion.
- Keep the generator, prompt, judge and provider strategy identical to the control unless that is the variable.
