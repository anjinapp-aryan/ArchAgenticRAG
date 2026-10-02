"""Resume a run whose generation or judging stopped part-way (e.g. a free-tier daily quota).

A resume never touches what already succeeded: recorded answers, contexts and metric values
are kept. It only re-does
  * items whose system call failed (target re-run, then all applicable metrics), and
  * metrics that have no value because their judge call errored.
Items are saved after each one, so an interrupted resume loses nothing. When a provider
reports a *daily* quota error the resume stops early and leaves the rest for the next session.
Every session is appended to ``manifest["resumes"]`` (time, git state, what was redone).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from archagenticrag.evaluation import analysis
from archagenticrag.evaluation.config import load_config
from archagenticrag.evaluation.dataset import file_sha256, load_dataset
from archagenticrag.evaluation.persistence import read_run
from archagenticrag.evaluation.target import build_target, run_target
from archagenticrag.evaluation.tracking import git_state

# Provider messages for daily (not per-minute) quotas. Waiting minutes will not help with these.
DAILY_QUOTA_MARKERS = ("tokens per day", "requests per day", "(TPD)", "(RPD)", "PerDay")


class ResumeError(RuntimeError):
    pass


def is_daily_quota_error(message: str | None) -> bool:
    return bool(message) and any(marker in message for marker in DAILY_QUOTA_MARKERS)


def failed_metrics(record: dict[str, Any]) -> list[str] | None:
    """Metric names to re-score; None means score everything (no or broken scoring)."""
    metrics = record.get("metrics") or {}
    if not metrics or "_scorer" in metrics:
        return None
    return [name for name, m in metrics.items() if m.get("value") is None and m.get("error")]


def pending(record: dict[str, Any]) -> bool:
    if record.get("error"):
        return True
    names = failed_metrics(record)
    return names is None or bool(names)


def _write_items(run_dir: Path, records: list[dict[str, Any]]) -> None:
    tmp = run_dir / "items.jsonl.tmp"
    with tmp.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    os.replace(tmp, run_dir / "items.jsonl")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


async def resume_evaluation(
    run_dir: str | Path,
    *,
    repo_root: str | Path = ".",
    target: Any = None,
    scorer: Any = None,
) -> dict[str, Any]:
    """Re-do the failed parts of ``run_dir`` in place and return this session's log entry."""
    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")
    run_dir = Path(run_dir)
    repo_root = Path(repo_root).resolve()
    run = read_run(run_dir)
    manifest = run["manifest"]
    config = load_config(run_dir / "config.yaml")  # the run's own copy, not the current file

    if config.fingerprint() != manifest["config_fingerprint"]:
        raise ResumeError("config.yaml in the run directory no longer matches the manifest fingerprint")
    dataset_path = repo_root / config.dataset.path
    if file_sha256(dataset_path) != manifest["dataset"]["sha256"]:
        raise ResumeError("golden dataset changed since the run started; start a new run instead")
    golden = {item.id: item for item in load_dataset(dataset_path).items}

    records: list[dict[str, Any]] = run["items"]
    todo = [r for r in records if pending(r)]
    session: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "git": git_state(repo_root),
        "pending_items": len(todo),
        "rerun_items": [],
        "rescored_metrics": {},
        "stopped_on_daily_quota": None,
    }
    if todo and scorer is None:
        from archagenticrag.evaluation.metrics import RagasScorer

        scorer = RagasScorer.from_judge_config(config.metrics, config.judge)

    for record in todo:
        g = golden[record["id"]]
        if record.get("error"):
            if target is None:
                target = build_target(config)
            res = await run_target(target, config.target, g.question)
            if res.error:
                if is_daily_quota_error(res.error):
                    session["stopped_on_daily_quota"] = f"{g.id}: {res.error[:300]}"
                    break
                record["error"] = res.error
                continue
            record.update(
                answer=res.answer,
                contexts=res.contexts,
                context_doc_ids=res.context_doc_ids,
                latency_s=res.latency_s,
                retrieval_latency_s=res.retrieval_latency_s,
                generation_latency_s=res.generation_latency_s,
                llm_calls=res.llm_calls,
                usage=res.usage,
                error=None,
                metrics={},
                retrieval=analysis.retrieval_checks(g, res.contexts, res.context_doc_ids),
            )
            session["rerun_items"].append(g.id)

        only = failed_metrics(record)
        try:
            outcomes = await scorer.score(g, record["answer"], record["contexts"], only=only)
        except Exception as exc:  # scorer-level failure: record, keep going
            record["metrics"] = {"_scorer": {"value": None, "reason": None, "error": f"{type(exc).__name__}: {exc}"}}
            outcomes = []
        else:
            if only is None:
                record["metrics"] = {}
            for o in outcomes:
                record["metrics"][o.name] = o.to_dict()
            session["rescored_metrics"][g.id] = [o.name for o in outcomes if o.value is not None]
        _write_items(run_dir, records)

        quota_error = next((o.error for o in outcomes if is_daily_quota_error(o.error)), None)
        if quota_error:
            session["stopped_on_daily_quota"] = f"{g.id}: {quota_error[:300]}"
            break

    for record in records:
        record["triage"] = analysis.triage(golden[record["id"]], record, config.triage)
    _write_items(run_dir, records)
    _write_json(run_dir / "summary.json", analysis.summarize(records, config.pricing))

    session["finished_at"] = datetime.now(UTC).isoformat()
    session["still_pending_items"] = sum(1 for r in records if pending(r))
    manifest.setdefault("resumes", []).append(session)
    _write_json(run_dir / "manifest.json", manifest)
    return session


def resume(run_dir: str | Path, **kwargs: Any) -> dict[str, Any]:
    return asyncio.run(resume_evaluation(run_dir, **kwargs))
