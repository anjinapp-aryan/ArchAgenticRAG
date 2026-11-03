---
name: data-retention
description: "Use when deciding what ArchAgenticRAG artifacts to keep, back up or delete: eval/results run directories, Qdrant collections, qrels, model caches, scratch files, and before any destructive step such as ingestion into an existing collection. Adds no new retention mechanism."
---

# data-retention

## Purpose
Keep what reproducibility needs, delete only what is disposable, and never lose an experiment's evidence by accident.

## When to use
Before deleting, moving, regenerating or re-indexing anything; when cleaning up; when a run's evidence must survive.

## Inputs
The artifact in question and which docs or registry entries reference it.

## Workflow
1. **Classify** the artifact:

| Class | Artifacts | Rule |
|---|---|---|
| Versioned evidence | code, configs, docs, `eval/experiments.yaml`, golden set, corpus, qrels, `THIRD_PARTY_NOTICES.md` | in git; frozen ones are read-only |
| Local-only evidence | `eval/results/<run_id>/` (gitignored) | the only copy of the run data; reports quote its numbers. Never delete, edit or overwrite a run referenced by the registry (`final_runs`) or a report. Back up before risky work |
| Rebuildable, but frozen | Qdrant collections (rebuilt by ingestion) | do not recreate the baseline or earlier experiments' collections: it changes `indexed_at`, and integration tests compare chunk texts with the qrels |
| Cache | FastEmbed models in `FASTEMBED_CACHE_PATH` (kept outside `%TEMP%`), HF cache | may be deleted if unused; they re-download |
| Disposable | scratch scripts and probe output, `__pycache__`, `.pytest_cache` | delete freely |

2. **Before any destructive step** (ingestion, collection delete, run delete, history rewrite) confirm the target is new or authorised, list what references it, and ask if unsure.
3. **Reproducibility needs:** a run's `manifest.json` (config, fingerprint, git commit and dirty flag, package versions, dataset and corpus hashes), `config.yaml`, `items.jsonl`, `summary.json`. Prefer a committed tree for official runs; if dirty, say so in the report.
4. **Never store credentials** in any artifact (`security`).
5. Do not add backup scripts or retention tooling; report the gap instead.

## Required checks
- `python -m archagenticrag.rag.ingest <cfg>` targets the collection named in `<cfg>`: read that name first.
- References (registry, reports, qrels) are checked before anything is removed.

## Output
What is kept, what is removed, what is backed up, and the evidence that nothing referenced was lost.

## STOP
- The target is a frozen artifact or a run referenced by docs or the registry.
- The action would recreate a collection that earlier results depend on.
- Credentials are found in an artifact.
