"""Unified benchmark comparison across experiment runs (``eval/runners/benchmark.py``).

Reads run directories under eval/results (never writes to them), maps each run to the
experiment registry (eval/experiments.yaml) by its ``run_name`` and reports, per experiment:
status, the run metadata contract, retrieval ranking metrics (no judge needed), Ragas answer
metrics, latency, tokens and cost.

Two evaluation layers are kept apart on purpose: ranking metrics answer "did retrieval
improve?", Ragas metrics answer "did the final answer improve?". An experiment without a run
is NOT RUN, and a missing value is ``None``, never 0.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from archagenticrag.evaluation.config import load_config
from archagenticrag.evaluation.persistence import read_run
from archagenticrag.evaluation.pricing import PriceBook, run_cost
from archagenticrag.evaluation.ranking import DEFAULT_CUTOFFS, run_ranking
from archagenticrag.evaluation.relevance import load_qrels, qrels_path
from archagenticrag.evaluation.resume import pending


class Status(StrEnum):
    COMPLETE = "COMPLETE"  # every item answered and judged (or finalized with recorded gaps)
    IN_PROGRESS = "IN PROGRESS"  # items still pending: system errors or unjudged metrics
    RETRIEVAL_ONLY = "RETRIEVAL ONLY"  # answers recorded; answer judging deliberately skipped
    FAILED = "FAILED"  # unreadable run, or every item failed
    NOT_RUN = "NOT RUN"


class RegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    role: Literal["experiment", "control"] = "experiment"
    run_names: list[str] = Field(default_factory=list)
    final_runs: list[str] = Field(default_factory=list)  # accepted as complete with their recorded gaps
    pinned_run: str | None = None  # compare this run instead of the latest one
    answer_eval: Literal["judged", "skipped"] = "judged"
    config: str | None = None  # eval/configs/... that produces the runs
    report: str | None = None  # docs/... with the experiment's design and results


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_version: Literal[1]
    experiments: list[RegistryEntry]

    @model_validator(mode="after")
    def _unique(self) -> Registry:
        ids = [e.id for e in self.experiments]
        names = [n for e in self.experiments for n in e.run_names]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate experiment ids in the registry")
        if len(names) != len(set(names)):
            raise ValueError("a run_name is mapped to more than one experiment")
        return self


def load_registry(path: Path) -> Registry:
    return Registry.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass
class LoadedRun:
    run_dir: Path
    run_name: str | None
    manifest: dict[str, Any] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None  # why the run could not be read

    @property
    def run_id(self) -> str:
        return self.manifest.get("run_id") or self.run_dir.name

    @property
    def started_at(self) -> str:
        return self.manifest.get("started_at") or ""


def _run_name_from_dir(name: str) -> str | None:
    # <timestamp>-<run_name>-<fingerprint[:8]>-<random[:6]>, see runner.run_evaluation
    parts = name.split("-")
    if len(parts) < 4:
        return None
    return "-".join(parts[1:-2])


def discover_runs(results_root: Path) -> list[LoadedRun]:
    runs = []
    for run_dir in sorted(p for p in results_root.iterdir() if p.is_dir()) if results_root.exists() else []:
        try:
            data = read_run(run_dir)
        except (OSError, ValueError) as exc:  # missing file or bad JSON
            runs.append(LoadedRun(run_dir, _run_name_from_dir(run_dir.name), error=f"{type(exc).__name__}: {exc}"))
            continue
        runs.append(LoadedRun(run_dir, data["manifest"].get("run_name"), data["manifest"], data["items"]))
    return runs


def run_status(run: LoadedRun, entry: RegistryEntry) -> tuple[Status, str]:
    if run.error:
        return Status.FAILED, f"unreadable run: {run.error}"
    if not run.items:
        return Status.FAILED, "run has no items"
    errors = sum(1 for r in run.items if r.get("error"))
    if errors == len(run.items):
        return Status.FAILED, f"all {errors} items failed"
    if entry.answer_eval == "skipped":
        return Status.RETRIEVAL_ONLY, "answer judging skipped by decision"
    waiting = sum(1 for r in run.items if pending(r))
    if not waiting:
        return Status.COMPLETE, ""
    if run.run_id in entry.final_runs:
        return Status.COMPLETE, f"finalized with {waiting} item(s) missing a value"
    return Status.IN_PROGRESS, f"{waiting} item(s) pending ({errors} system error(s))"


def _completed_at(run: LoadedRun, status: Status) -> str | None:
    if status not in (Status.COMPLETE, Status.RETRIEVAL_ONLY):
        return None
    sessions = [s.get("finished_at") for s in run.manifest.get("resumes", []) if s.get("finished_at")]
    return max([run.manifest.get("finished_at") or "", *sessions]) or None


def run_metadata(run: LoadedRun, entry: RegistryEntry, status: Status) -> dict[str, Any]:
    """The experiment metadata contract (docs/PHASE-3.0-EXPERIMENT-LAB.md, section 7)."""
    m = run.manifest
    config = m.get("config") or {}
    system = config.get("system") or {}
    fingerprint_ok = None
    if (run.run_dir / "config.yaml").exists() and m.get("config_fingerprint"):
        try:
            fingerprint_ok = load_config(run.run_dir / "config.yaml").fingerprint() == m["config_fingerprint"]
        except ValueError:
            fingerprint_ok = False
    return {
        "experiment_id": entry.id,
        "experiment_name": entry.name,
        "role": entry.role,
        "config": entry.config,
        "report": entry.report,
        "run_id": run.run_id,
        "run_name": run.run_name,
        "git_commit": (m.get("git") or {}).get("commit"),
        "git_dirty": (m.get("git") or {}).get("dirty"),
        "config_fingerprint": m.get("config_fingerprint"),
        "fingerprint_verified": fingerprint_ok,
        "dataset_hash": (m.get("dataset") or {}).get("sha256"),
        "corpus_hash": (m.get("corpus") or {}).get("manifest_sha256"),
        "target_factory": (config.get("target") or {}).get("factory"),
        "embedding_config": system.get("embedding"),
        "retrieval_config": system.get("retrieval"),
        "generator_config": system.get("generator"),
        "judge_config": config.get("judge"),
        "judge_deferred": m.get("judge_deferred", False),
        # runs before multi-provider fallback had one provider per role, as configured
        "provider_strategy": m.get("provider_strategy"),
        "provider_mode": _provider_mode(m.get("provider_strategy")),
        "providers_used": _providers_used(run.items),
        "metrics": config.get("metrics"),
        "status": status.value,
        "started_at": m.get("started_at"),
        "completed_at": _completed_at(run, status),
    }


def _provider_mode(strategy: dict[str, Any] | None) -> str:
    if strategy and any((role or {}).get("mode") == "fallback" for role in strategy.values()):
        return "multi-provider fallback"
    return "single provider"


def _providers_used(items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Requests served per role and provider:model, from the per-item fallback records."""
    used: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in items:
        for key in ("provider_calls", "judge_provider_calls"):
            for call in item.get(key) or []:
                served = f"{call.get('actual_provider')}:{call.get('actual_model')}" if call.get("outcome") == "success" else call.get("outcome")
                used[call.get("role", key)][served] += 1
    return {role: dict(v) for role, v in used.items()}


def select_run(entry: RegistryEntry, runs: list[LoadedRun]) -> tuple[LoadedRun | None, list[LoadedRun]]:
    """The pinned run, else the latest by start time; the others are reported, not compared."""
    mine = [r for r in runs if r.run_name in entry.run_names]
    if not mine:
        return None, []
    if entry.pinned_run:
        chosen = next((r for r in mine if r.run_id == entry.pinned_run), None)
        if chosen is None:
            raise ValueError(f"experiment {entry.id}: pinned run {entry.pinned_run} not found")
    else:
        chosen = max(mine, key=lambda r: (r.started_at, r.run_dir.name))
    return chosen, [r for r in mine if r is not chosen]


def _mean_metric(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    values = [m["value"] for r in items if (m := (r.get("metrics") or {}).get(name)) and m.get("value") is not None]
    return {"mean": statistics.fmean(values) if values else None, "n": len(values)}


def answer_summary(items: list[dict[str, Any]], metric_names: list[str]) -> dict[str, Any]:
    finished = [r for r in items if not pending(r)]
    latencies = [r["latency_s"] for r in items if not r.get("error") and r.get("latency_s") is not None]
    tokens: dict[str, dict[str, int]] = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0})
    for r in items:
        for model, usage in (r.get("usage") or {}).items():
            tokens[model]["input_tokens"] += usage.get("input_tokens", 0)
            tokens[model]["output_tokens"] += usage.get("output_tokens", 0)
    return {
        "items": len(items),
        "system_errors": sum(1 for r in items if r.get("error")),
        "pending_items": len(items) - len(finished),
        "pass": sum(1 for r in items if (r.get("triage") or {}).get("label") == "PASS"),
        "judged_items": len(finished),
        "metrics": {name: _mean_metric(items, name) for name in metric_names},
        "latency_p50_s": statistics.median(latencies) if latencies else None,
        "llm_calls_mean": statistics.fmean(r.get("llm_calls", 0) for r in items) if items else None,
        "tokens_by_model": dict(tokens),
    }


def _qrels_for(run: LoadedRun, repo_root: Path) -> tuple[dict[str, Any] | None, str | None]:
    config = run.manifest.get("config") or {}
    try:
        collection = config["system"]["retrieval"]["qdrant"]["collection"]
        dataset_path = repo_root / config["dataset"]["path"]
    except (KeyError, TypeError):
        return None, "run config names no Qdrant collection"
    path = qrels_path(dataset_path.parent / "qrels", collection)
    if not path.exists():
        return None, f"no qrels for collection {collection} (run eval/runners/build_qrels.py)"
    qrels = load_qrels(path)
    if qrels["dataset"].get("sha256") != (run.manifest.get("dataset") or {}).get("sha256"):
        return None, "qrels were built from a different golden dataset version"
    return qrels, None


def compare(
    registry: Registry,
    runs: list[LoadedRun],
    *,
    repo_root: Path,
    price_book: PriceBook,
    cutoffs: tuple[int, ...] = DEFAULT_CUTOFFS,
    include_not_run: bool = True,
    experiments: set[str] | None = None,
    baseline_id: str | None = "01",
) -> dict[str, Any]:
    """Compare the registered experiments (or only the ids in ``experiments``).

    The paired item set is computed over the experiments actually compared, so restricting the
    comparison (e.g. to 01 and 02) does not drop items only some unrelated run failed on.
    Each row also gets per-item wins / ties / losses against ``baseline_id`` on the paired set.
    """
    rows: list[dict[str, Any]] = []
    known = {n for e in registry.experiments for n in e.run_names}
    for entry in registry.experiments:
        if experiments is not None and entry.id not in experiments:
            continue
        chosen, others = select_run(entry, runs)
        if chosen is None:
            if include_not_run:
                rows.append({"experiment_id": entry.id, "experiment_name": entry.name, "role": entry.role, "status": Status.NOT_RUN.value})
            continue
        status, detail = run_status(chosen, entry)
        row: dict[str, Any] = {
            **run_metadata(chosen, entry, status),
            "status_detail": detail,
            "other_runs": [r.run_id for r in others],
            "run_dir": str(chosen.run_dir),
        }
        row["_run"] = chosen
        rows.append(row)

    # Paired ranking: only items no compared run failed on, so a provider error is not scored as a retrieval miss.
    compared = [r["_run"] for r in rows if "_run" in r and r["status"] != Status.FAILED.value]
    failed_ids = {i["id"] for run in compared for i in run.items if i.get("error")}

    per_query: dict[str, dict[str, Any]] = {}  # experiment id -> paired per-item values
    for row in rows:
        run = row.pop("_run", None)
        if run is None or row["status"] == Status.FAILED.value:
            continue
        metric_names = row.get("metrics") or []
        row["answer"] = answer_summary(run.items, metric_names) if row["status"] != Status.RETRIEVAL_ONLY.value else None
        if row["answer"] is None:
            row["generation"] = answer_summary(run.items, [])
        usage = (row["answer"] or row["generation"])["tokens_by_model"]
        started = datetime.fromisoformat(row["started_at"]).date() if row.get("started_at") else datetime.now().date()
        row["cost"] = run_cost(usage, price_book, started)
        qrels, reason = _qrels_for(run, repo_root)
        if qrels is None:
            row["ranking"], row["ranking_unavailable"] = None, reason
            continue
        all_items = run_ranking(run.items, qrels, cutoffs)
        paired_ids = {qid for qid, q in qrels["queries"].items() if q["expected_behavior"] == "answer"} - failed_ids
        paired = run_ranking(run.items, qrels, cutoffs, only=paired_ids)
        per_query[row["experiment_id"]] = {
            "catalog": qrels["chunk_set"].get("catalog_sha256"),
            "chunk": paired["chunk"]["per_query"],
            "doc": paired["doc"]["per_query"],
        }
        row["ranking"] = {
            "all_items": _drop_per_query(all_items),
            "paired": _drop_per_query(paired),
            "paired_items": sorted(paired_ids),
            "qrels_collection": qrels["chunk_set"]["collection"],
        }

    base = per_query.get(baseline_id) if baseline_id else None
    for row in rows:
        mine = per_query.get(row["experiment_id"])
        if base is None or mine is None or row["experiment_id"] == baseline_id:
            continue
        if mine["catalog"] != base["catalog"]:
            row["ranking"]["vs_baseline"] = {"unavailable": "different chunk catalog; chunk ids are not comparable"}
            continue
        row["ranking"]["vs_baseline"] = {
            "baseline": baseline_id,
            "chunk": _paired_deltas(base["chunk"], mine["chunk"]),
            "doc": _paired_deltas(base["doc"], mine["doc"]),
        }

    unregistered = sorted({r.run_dir.name for r in runs if r.run_name not in known})
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cutoffs": list(cutoffs),
        "paired_excluded_items": sorted(failed_ids),
        "rows": rows,
        "unregistered_runs": unregistered,
    }


def _paired_deltas(base: dict[str, dict[str, float]], other: dict[str, dict[str, float]]) -> dict[str, Any]:
    """Mean difference and per-item wins / ties / losses of ``other`` against ``base``."""
    items = sorted(set(base) & set(other))
    out: dict[str, Any] = {}
    for name in next(iter(base.values()), {}):
        diffs = [other[q][name] - base[q][name] for q in items]
        out[name] = {
            "delta": statistics.fmean(diffs) if diffs else None,
            "wins": sum(d > 1e-9 for d in diffs),
            "ties": sum(abs(d) <= 1e-9 for d in diffs),
            "losses": sum(d < -1e-9 for d in diffs),
        }
    return {"n": len(items), "metrics": out}


def _drop_per_query(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    out["chunk"] = {k: v for k, v in result["chunk"].items() if k != "per_query"}
    out["doc"] = {k: v for k, v in result["doc"].items() if k != "per_query"}
    return out


def _fmt(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def render_markdown(result: dict[str, Any], table_ks: tuple[int, ...] = (4, 8)) -> str:
    head = ["Experiment", "Status", "Pass", *(f"Recall@{k}" for k in table_ks), "MRR", *(f"nDCG@{k}" for k in table_ks), "Faithfulness", "Correctness", "Latency p50"]
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join(["---", "---", "---:"] + ["---:"] * (len(head) - 3)) + "|"]
    for row in result["rows"]:
        label = f"{row['experiment_id']} {row['experiment_name']}"
        status = row["status"]
        if status == Status.NOT_RUN.value or row.get("ranking") is None and row.get("answer") is None and row.get("generation") is None:
            lines.append("| " + " | ".join([label, status] + ["—"] * (len(head) - 2)) + " |")
            continue
        answer = row.get("answer")
        ranking = (row.get("ranking") or {}).get("paired", {}).get("chunk", {}).get("mean") if row.get("ranking") else None
        if answer:
            if status == Status.COMPLETE.value:  # finalized runs keep their gaps in the denominator
                passed = f"{answer['pass']}/{answer['items']}"
            else:
                passed = f"{answer['pass']}/{answer['judged_items']} judged" + (f" ({answer['pending_items']} pending)" if answer["pending_items"] else "")
            faith = answer["metrics"].get("faithfulness", {})
            corr = answer["metrics"].get("answer_correctness", {})
            faith_s = f"{_fmt(faith.get('mean'))} (n={faith.get('n', 0)})" if faith.get("n") else "—"
            corr_s = f"{_fmt(corr.get('mean'))} (n={corr.get('n', 0)})" if corr.get("n") else "—"
            latency = answer["latency_p50_s"]
        else:
            passed, faith_s, corr_s = "—", "—", "—"
            latency = (row.get("generation") or {}).get("latency_p50_s")
        rank_cells = [_fmt(ranking.get(f"recall@{k}")) if ranking else "—" for k in table_ks]
        rank_cells += [_fmt(ranking.get("mrr")) if ranking else "—"]
        rank_cells += [_fmt(ranking.get(f"ndcg@{k}")) if ranking else "—" for k in table_ks]
        lines.append("| " + " | ".join([label, status, passed, *rank_cells, faith_s, corr_s, f"{_fmt(latency, 2)} s" if latency is not None else "—"]) + " |")

    notes = [
        "",
        "Ranking metrics: chunk-level, answerable items with qrels, paired (items any compared run failed on are excluded: "
        + (", ".join(result["paired_excluded_items"]) or "none")
        + "). Pass = PASS / items (COMPLETE) or PASS / fully judged items (IN PROGRESS). "
        "Ragas means are over the items each run has a value for (n); compare them only at similar n.",
    ]
    for row in result["rows"]:
        if row.get("status_detail"):
            notes.append(f"- {row['experiment_id']}: {row['status_detail']}")
        if row.get("ranking_unavailable"):
            notes.append(f"- {row['experiment_id']}: ranking unavailable: {row['ranking_unavailable']}")
        if row.get("provider_mode") == "multi-provider fallback":
            used = "; ".join(f"{role}: " + ", ".join(f"{k} x{v}" for k, v in served.items()) for role, served in (row.get("providers_used") or {}).items())
            notes.append(f"- {row['experiment_id']}: MULTI-PROVIDER FALLBACK RUN, not a single-provider result ({used or 'no calls recorded'})")
        if row.get("other_runs"):
            notes.append(f"- {row['experiment_id']}: {len(row['other_runs'])} other run(s) not compared: {', '.join(row['other_runs'])}")
    if result["unregistered_runs"]:
        notes.append(f"- runs not in the registry: {', '.join(result['unregistered_runs'])}")
    return "\n".join(lines + notes) + "\n"


def to_json(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, default=str) + "\n"
