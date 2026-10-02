# ArchAgenticRAG

A learning and portfolio project for Agentic RAG. The rule is to never reinvent the wheel: every capability is reused, adapted or composed from existing open-source projects, and only glue code is written here.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Ecosystem research and architecture | Done: [docs/phase-0-research.md](docs/phase-0-research.md) |
| 1 | Foundation and Basic RAG | Done, pending review: Docling → FastEmbed → Qdrant → LangGraph `retrieve → generate`. [docs/PHASE-1-IMPLEMENTATION.md](docs/PHASE-1-IMPLEMENTATION.md), [docs/PHASE-1-REPORT.md](docs/PHASE-1-REPORT.md) |
| 2 | Evaluation harness and baseline | Harness, dataset and tests are done. Basic RAG baseline measured: [docs/PHASE-2-BASELINE-RESULTS.md](docs/PHASE-2-BASELINE-RESULTS.md) |

## Layout

```
data/corpus/peps/      13 public-domain / CC0 Python PEPs (evaluation corpus) + MANIFEST.json
eval/datasets/         golden QA sets (versioned)
eval/configs/          versioned evaluation run configs
eval/runners/          CLI entry points (validate, sync to Langfuse, run)
eval/results/          one folder per run (manifest, per-item records, summary)
src/archagenticrag/    package code: rag/ (ingestion, Qdrant), graphs/ (LangGraph), evaluation/ (glue)
tests/                 offline unit tests; integration/ needs Qdrant, live needs API keys
docker-compose.yml     Qdrant server
docs/                  research, ADRs, learning log
```

## Quick start

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[eval]" pytest pytest-asyncio
cp .env.example .env                                 # add the key for your provider; never commit .env
.venv/Scripts/python -m pytest                       # offline tests
docker compose up -d qdrant
.venv/Scripts/python -m archagenticrag.rag.ingest eval/configs/baseline-basic-rag.yaml
.venv/Scripts/python eval/runners/validate_dataset.py eval/datasets/peps-v1/golden.json
.venv/Scripts/python eval/runners/run_eval.py eval/configs/baseline-basic-rag.yaml
```

For a fully local LLM, set `generator.provider: ollama` in the config. See [docs/PHASE-1-IMPLEMENTATION.md](docs/PHASE-1-IMPLEMENTATION.md) and [eval/README.md](eval/README.md).
