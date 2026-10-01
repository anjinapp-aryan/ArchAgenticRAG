# ArchAgenticRAG

A learning and portfolio project for Agentic RAG. The rule is to never reinvent the wheel: every capability is reused, adapted or composed from existing open-source projects, and only glue code is written here.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Ecosystem research and architecture | Done: [docs/phase-0-research.md](docs/phase-0-research.md) |
| 1 | Foundation and Basic RAG | **Not present in this repository** |
| 2 | Evaluation harness and baseline | Harness, dataset and tests are done. The baseline run is blocked on Phase 1: [docs/learning-log/phase-2-baseline.md](docs/learning-log/phase-2-baseline.md) |

## Layout

```
data/corpus/peps/      13 public-domain / CC0 Python PEPs (evaluation corpus) + MANIFEST.json
eval/datasets/         golden QA sets (versioned)
eval/configs/          versioned evaluation run configs
eval/runners/          CLI entry points (validate, sync to Langfuse, run)
eval/results/          one folder per run (manifest, per-item records, summary)
src/archagenticrag/    package code (evaluation glue in evaluation/)
tests/                 offline unit tests (no external API calls)
docs/                  research, ADRs, learning log
```

## Evaluation quick start

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[eval]" pytest pytest-asyncio
.venv/Scripts/python -m pytest                       # offline tests
.venv/Scripts/python eval/runners/validate_dataset.py eval/datasets/peps-v1/golden.json
.venv/Scripts/python eval/runners/run_eval.py eval/configs/baseline-basic-rag.yaml
```

`run_eval.py` needs the Phase 1 Basic RAG graph and model provider keys. See [eval/README.md](eval/README.md).
