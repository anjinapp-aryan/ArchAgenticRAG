"""Resume a run whose generation or judging stopped part-way (e.g. a free-tier daily quota).

A resume never touches what already succeeded: recorded answers, contexts and metric values
are kept. It only re-does
  * items whose system call failed (target re-run, then all applicable metrics), and
  * metrics that have no value because their judge call errored.
Items are saved after each one, so an interrupted resume loses nothing. When a provider
reports a *daily* quota error the resume stops early and leaves the rest for the next session.
With ``judge=False`` only failed system calls are re-run (no judge call, nothing scored), which
completes a ``--defer-judge`` run's answers and retrieval without spending judge quota.
Every session is appended to ``manifest["resumes"]`` (time, git state, what was redone) when it
starts and updated after each item, so even a killed session leaves a record.
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
from archagenticrag.provider_fallback import DAILY_QUOTA_MARKERS, EXHAUSTED, collect_provider_calls

# Waiting minutes will not help with these: a provider's daily quota, or every fallback provider failing.
STOP_MARKERS = (*DAILY_QUOTA_MARKERS, EXHAUSTED)


class ResumeError(RuntimeError):
    pass


def is_daily_quota_error(message: str | None) -> bool:
    """A daily quota, or PROVIDER_EXHAUSTED from the fallback transport: stop this session."""
    return bool(message) and any(marker in message for marker in STOP_MARKERS)


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
    judge: bool = True,
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
    todo = [r for r in records if (pending(r) if judge else r.get("error"))]
    session: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "judge": judge,
        "git": git_state(repo_root),
        "pending_items": len(todo),
        "rerun_items": [],
        "rescored_metrics": {},
        "stopped_on_daily_quota": None,
        "finished_at": None,
    }
    manifest.setdefault("resumes", []).append(session)
    _write_json(run_dir / "manifest.json", manifest)
    if todo and scorer is None and judge:
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
                retrieval_results=res.retrieval_results,
                retrieval_calls=res.retrieval_calls,
            )
            if config.target.record_keys:
                record["recorded"] = res.recorded
            if res.provider_calls:
                record["provider_calls"] = res.provider_calls
            session["rerun_items"].append(g.id)

        if not judge:
            _write_items(run_dir, records)
            _write_json(run_dir / "manifest.json", manifest)
            continue
        only = failed_metrics(record)
        try:
            # stop at the first daily-quota error inside the item: the SDK's own retries on the
            # remaining metrics would only wait out a quota that will not reset for hours
            with collect_provider_calls() as judge_calls:
                outcomes = await scorer.score(
                    g, record["answer"], record["contexts"], only=only, stop=lambda o: is_daily_quota_error(o.error)
                )
            if judge_calls:
                record.setdefault("judge_provider_calls", []).extend(judge_calls)
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
        _write_json(run_dir / "manifest.json", manifest)

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
    _write_json(run_dir / "manifest.json", manifest)
    return session


def resume(run_dir: str | Path, **kwargs: Any) -> dict[str, Any]:
    return asyncio.run(resume_evaluation(run_dir, **kwargs))
