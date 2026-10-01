"""Run one evaluation: Langfuse ``run_experiment`` drives the loop, Ragas scores each item.

Langfuse logs and drops items whose task raises, and swallows evaluator exceptions.
For a trustworthy baseline both wrappers below catch their own errors and record them,
and the run fails if any golden item is missing from the results.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from archagenticrag.evaluation import analysis, persistence
from archagenticrag.evaluation.config import load_config
from archagenticrag.evaluation.dataset import load_dataset, verify_traceability
from archagenticrag.evaluation.langfuse_sync import item_metadata, make_client
from archagenticrag.evaluation.target import build_target, run_target
from archagenticrag.evaluation.tracking import build_manifest


class RunError(RuntimeError):
    pass


def run_evaluation(
    config_path: str | Path,
    *,
    repo_root: str | Path = ".",
    results_root: str | Path | None = None,
    target: Any = None,
    scorer: Any = None,
    langfuse_client: Any = None,
) -> Path:
    """Execute a run and return its results directory.

    ``target``, ``scorer`` and ``langfuse_client`` are injectable for tests; by default they
    are built from the config (Phase 1 graph, Ragas judge, Langfuse client).
    """
    # Ragas sends usage analytics unless told not to.
    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")

    repo_root = Path(repo_root).resolve()
    config_path = Path(config_path)
    config = load_config(config_path)
    dataset = load_dataset(repo_root / config.dataset.path)
    problems = verify_traceability(dataset, repo_root / config.dataset.corpus_dir)
    if problems:
        raise RunError("dataset is not traceable to the corpus:\n" + "\n".join(problems))

    started = datetime.now(UTC)
    # timestamp + config fingerprint identify the run; the random suffix keeps same-second runs apart
    run_id = f"{started:%Y%m%dT%H%M%SZ}-{config.run_name}-{config.fingerprint()[:8]}-{uuid.uuid4().hex[:6]}"
    manifest = build_manifest(
        run_id=run_id, config=config, config_path=config_path, dataset=dataset, repo_root=repo_root, started_at=started
    )

    if target is None:
        target = build_target(config)
    # Graphs may describe what they run on (e.g. the Qdrant index metadata); record it verbatim.
    manifest["target_metadata"] = getattr(target, "eval_metadata", None)
    if scorer is None:
        from archagenticrag.evaluation.metrics import RagasScorer

        scorer = RagasScorer.from_judge_config(config.metrics, config.judge)
    if langfuse_client is None:
        langfuse_client = make_client(config.langfuse.enabled)

    golden = {item.id: item for item in dataset.items}
    records: dict[str, dict[str, Any]] = {}

    def golden_id(metadata: Any) -> str:
        return (metadata or {})["id"]

    async def task(*, item: Any, **_: Any) -> dict[str, Any]:
        meta = item["metadata"] if isinstance(item, dict) else item.metadata
        g = golden[golden_id(meta)]
        res = await run_target(target, config.target, g.question)
        records[g.id] = {
            "id": g.id,
            "category": g.category.value,
            "difficulty": g.difficulty,
            "expected_behavior": g.expected_behavior.value,
            "question": g.question,
            "ground_truth": g.ground_truth,
            "answer": res.answer,
            "contexts": res.contexts,
            "context_doc_ids": res.context_doc_ids,
            "latency_s": res.latency_s,
            "retrieval_latency_s": res.retrieval_latency_s,
            "generation_latency_s": res.generation_latency_s,
            "llm_calls": res.llm_calls,
            "usage": res.usage,
            "error": res.error,
            "metrics": {},
            "retrieval": analysis.retrieval_checks(g, res.contexts, res.context_doc_ids),
        }
        return {"answer": res.answer, "contexts": res.contexts, "error": res.error}

    async def ragas_evaluator(*, metadata: Any = None, **_: Any) -> list[Any]:
        from langfuse import Evaluation

        g = golden[golden_id(metadata)]
        record = records[g.id]
        if record["error"]:
            return []
        try:
            outcomes = await scorer.score(g, record["answer"], record["contexts"])
        except Exception as exc:  # scorer-level failure: record, keep going
            record["metrics"] = {"_scorer": {"value": None, "reason": None, "error": f"{type(exc).__name__}: {exc}"}}
            return []
        record["metrics"] = {o.name: o.to_dict() for o in outcomes}
        return [Evaluation(name=o.name, value=o.value, comment=o.reason) for o in outcomes if o.value is not None]

    experiment_meta = {
        "run_id": run_id,
        "config_fingerprint": config.fingerprint(),
        "git_commit": str(manifest["git"].get("commit")),
        "dataset_version": dataset.version,
    }
    if config.langfuse.enabled:
        lf_dataset = langfuse_client.get_dataset(config.langfuse.dataset_name)
        remote_ids = {golden_id(i.metadata) for i in lf_dataset.items}
        if remote_ids != set(golden):
            raise RunError("Langfuse dataset differs from local golden set; run eval/runners/sync_langfuse_dataset.py")
        result = lf_dataset.run_experiment(
            name=config.run_name,
            run_name=run_id,
            task=task,
            evaluators=[ragas_evaluator],
            max_concurrency=config.max_concurrency,
            metadata=experiment_meta,
        )
    else:
        result = langfuse_client.run_experiment(
            name=config.run_name,
            run_name=run_id,
            data=[
                {"input": {"question": g.question}, "expected_output": g.ground_truth, "metadata": item_metadata(g, dataset)}
                for g in dataset.items
            ],
            task=task,
            evaluators=[ragas_evaluator],
            max_concurrency=config.max_concurrency,
            metadata=experiment_meta,
        )

    missing = sorted(set(golden) - set(records))
    if missing:
        raise RunError(f"{len(missing)} item(s) produced no result: {missing}")

    for item_result in getattr(result, "item_results", []) or []:
        item = item_result.item
        meta = item["metadata"] if isinstance(item, dict) else item.metadata
        records[golden_id(meta)]["langfuse_trace_id"] = item_result.trace_id

    ordered = [records[item.id] for item in dataset.items]
    for record in ordered:
        record["triage"] = analysis.triage(golden[record["id"]], record, config.triage)
    summary = analysis.summarize(ordered, config.pricing)
    manifest["finished_at"] = datetime.now(UTC).isoformat()
    if config.langfuse.enabled:
        langfuse_client.flush()

    return persistence.write_run(
        Path(results_root) if results_root else repo_root / "eval" / "results",
        run_id,
        manifest=manifest,
        config_path=config_path,
        records=ordered,
        summary=summary,
    )
