# AGENTS.md

Operating rules for AI coding agents working in ArchAgenticRAG. Claude Code loads this through `CLAUDE.md`; other agents read it directly. This file stays short on purpose: procedures live in skills (`.claude/skills/`), explanations in `docs/ai-development/`.

## What this project is

An experiment lab for RAG and agentic RAG: Docling chunking → FastEmbed embeddings → Qdrant → LangGraph graphs, scored by Ragas (answers) and ir-measures (retrieval ranking), traced with Langfuse. Numbered experiments are compared against a frozen baseline. Python 3.12, package `src/archagenticrag`, runs driven by YAML configs under `eval/`.

## Hard rules

1. **Reuse first.** REUSE → ADAPT → COMPOSE → REFERENCE → BUILD. Audit the repo, installed packages and mature open source before writing a capability.
2. **Frozen artifacts are read-only** unless the task says otherwise: the baseline (experiment 01, fingerprint `63bf3b5f990cc9e5`), earlier experiments' configs and `eval/results/*` runs, `golden.json`, `data/corpus/**`, qrels, and the baseline Qdrant collection. Tests pin fingerprints and config diffs; a failing pin is a STOP, not something to patch around.
3. **One variable per experiment.** Everything else is identical to the control and recorded in the config. A new optional config field must stay out of the fingerprint while unset.
4. **Retrieval win ≠ answer win.** Report ranking metrics (Recall@K, MRR, nDCG) and Ragas answer metrics separately; never infer one from the other.
5. **Report test status per category** as PASS / FAIL / SKIPPED / NOT RUN / BLOCKED. Deselected tests are NOT RUN. Never write "all tests pass" if anything was skipped, not run or blocked.
6. **No silent provider or model swaps.** Fallback is opt-in, recorded per request, and makes a different run configuration.
7. **Secrets.** Never commit, print or ask for keys. `.env` is gitignored.
8. **Licences.** Unclear means reject. Record accepted components in `THIRD_PARTY_NOTICES.md`.
9. **Judge quota is scarce.** Defer judging (`--defer-judge`, `resume_eval.py`). Never start judging unasked, and never run quota-consuming work while an official run is generating.
10. **Additive, minimal changes.** No moves, renames or rewrites for tidiness. Keep `build_graph(system) -> graph`; factory strings are recorded in run manifests.
11. **Git.** Commit or push only when asked. If on `main`, branch first. Scan for secrets before committing.
12. **Scope.** Do what was asked and stop where told. Never start the next experiment or phase unasked.

## STOP and report, do not work around, if

- a frozen artifact, fingerprint or result file changed unexpectedly, or configuration drift appears between compared runs
- a licence is unclear for something you are about to add
- the task needs a major rewrite, or a custom build of something that can be reused
- tests regressed, or required tests cannot be run
- a credential appears in a diff, log, result file or chat
- a comparison stops being controlled (more than one variable changed, or a different provider or model answered)
- the scope grows beyond what was approved

## Ask first, before starting

- changing a frozen artifact, the dataset or qrels; recreating an existing collection; deleting a run
- a major architecture change, a breaking interface change, or anything that touches production
- a new paid or external service, or a component with an unclear licence
- spending judge quota; pushing to `main`; force-pushing
- growing the scope, or starting the next experiment

Everything else inside the approved scope proceeds without asking. Which of these a hook enforces: `docs/ai-development/AGENT_WORKFLOW.md`.

## Commands (Windows; run from the repo root)

| Task | Command |
|---|---|
| Offline tests (default) | `.venv/Scripts/python -m pytest -q` |
| Integration (needs Qdrant) | `.venv/Scripts/python -m pytest -m integration -q` |
| Live (real providers, uses free-tier quota) | `.venv/Scripts/python -m pytest -m live -q` |
| Start Qdrant | `docker compose up -d qdrant` (`localhost:6333`) |
| Run an experiment, no judge | `.venv/Scripts/python eval/runners/run_eval.py eval/configs/<cfg>.yaml --defer-judge` |
| Finish or judge a run | `.venv/Scripts/python eval/runners/resume_eval.py eval/results/<run_id> [--no-judge]` |
| Compare experiments | `.venv/Scripts/python eval/runners/benchmark.py --all` |
| Check frozen artifacts | `python .claude/hooks/guard.py verify` |
| Relevance labels for a collection | `.venv/Scripts/python eval/runners/build_qrels.py eval/configs/<cfg>.yaml` |

If Docker or Qdrant is unavailable, integration and live are BLOCKED. `python -m archagenticrag.rag.ingest <cfg>` **deletes and recreates** its config's collection: run it only for a new collection. No linter, formatter or CI is configured; do not add one unasked. Files are LF (`.gitattributes`).

## Where to look

| Task | Skills, in order | Read |
|---|---|---|
| New capability, dependency or model | `reuse-audit`, `license-audit`, `architecture-review` | `docs/ai-development/REUSE_FIRST_POLICY.md` |
| New experiment, or "improve retrieval" | `experiment-design`, `reuse-audit`, `architecture-review`, `implementation`, `evaluation`, `testing` | `docs/ai-development/EXPERIMENT_RULES.md` |
| Implement an approved design or a fix | `implementation`, `testing` | `docs/ai-development/ARCHITECTURE_RULES.md` |
| Investigate a failure | `failure-investigation` | the skill's triage table |
| New or changed LLM provider | `provider-development`, `reuse-audit`, `license-audit`, `security`, `testing` | `docs/MULTI-PROVIDER-FALLBACK.md` |
| Run or judge an evaluation | `evaluation`, `data-retention` | `eval/README.md` |
| Structural change | `architecture-review` | `docs/ai-development/ARCHITECTURE_RULES.md` |
| Before committing | `change-review`, `testing`, `security`, `git-checkpoint` | `docs/ai-development/AGENT_WORKFLOW.md` |

The full map is `docs/ai-development/AI_DEVELOPMENT_GUIDE.md`.
