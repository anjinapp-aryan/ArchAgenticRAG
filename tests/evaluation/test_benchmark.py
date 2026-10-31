"""Benchmark comparison: statuses (incl. NOT RUN), duplicate runs, missing metrics, metadata contract, cost."""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from archagenticrag.evaluation.benchmark import (
    Registry,
    Status,
    compare,
    discover_runs,
    load_registry,
    render_markdown,
)
from archagenticrag.evaluation.config import load_config
from archagenticrag.evaluation.pricing import PriceBook, load_price_book, run_cost
from archagenticrag.evaluation.relevance import text_sha256

from .conftest import BASELINE_CONFIG, REPO_ROOT

DATASET_SHA = "d" * 64
COLLECTION = "peps_v1_bge_small_docling_480"


def _item(qid: str, *, error=None, metric=1.0, label="PASS", contexts=("A0",)) -> dict:
    return {
        "id": qid,
        "category": "A_direct_factual",
        "error": error,
        "contexts": [] if error else list(contexts),
        "context_doc_ids": [] if error else [c[0].lower() for c in contexts],
        "latency_s": 2.0,
        "llm_calls": 1,
        "usage": {"gen-model": {"input_tokens": 1000, "output_tokens": 100}},
        "metrics": {} if error else {"faithfulness": {"value": metric, "error": None if metric is not None else "judge 429"}},
        "triage": {"label": label},
    }


@pytest.fixture
def lab(tmp_path: Path):
    """Results root, registry, qrels and a run writer."""
    config = load_config(BASELINE_CONFIG)
    qrels_dir = tmp_path / "eval" / "datasets" / "peps-v1" / "qrels"
    qrels_dir.mkdir(parents=True)
    (qrels_dir / f"{COLLECTION}.json").write_text(
        json.dumps(
            {
                "qrels_version": 1,
                "dataset": {"sha256": DATASET_SHA},
                "chunk_set": {"collection": COLLECTION},
                "chunk_catalog": {"a#0": {"doc_id": "a", "sha256": text_sha256("A0")}, "b#0": {"doc_id": "b", "sha256": text_sha256("B0")}},
                "queries": {
                    "Q1": {"category": "A", "expected_behavior": "answer", "chunk_relevance": {"a#0": 1}, "doc_relevance": {"a": 1}},
                    "Q2": {"category": "A", "expected_behavior": "answer", "chunk_relevance": {"b#0": 1}, "doc_relevance": {"b": 1}},
                },
            }
        ),
        encoding="utf-8",
    )
    results = tmp_path / "eval" / "results"
    results.mkdir(parents=True)

    def write_run(run_name: str, started: str, items: list[dict], *, resumes=None, suffix="aaaaaa") -> Path:
        run_id = f"{started}-{run_name}-{config.fingerprint()[:8]}-{suffix}"
        run_dir = results / run_id
        run_dir.mkdir()
        shutil.copyfile(BASELINE_CONFIG, run_dir / "config.yaml")
        manifest = {
            "run_id": run_id,
            "run_name": run_name,
            "started_at": f"2026-10-{started[6:8]}T00:00:00+00:00",
            "finished_at": f"2026-10-{started[6:8]}T01:00:00+00:00",
            "git": {"commit": "abc", "dirty": False},
            "config_fingerprint": config.fingerprint(),
            "config": config.model_dump(mode="json"),
            "dataset": {"sha256": DATASET_SHA},
            "corpus": {"manifest_sha256": "c" * 64},
            "resumes": resumes or [],
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (run_dir / "summary.json").write_text("{}", encoding="utf-8")
        (run_dir / "items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")
        return run_dir

    def registry(entries: list[dict]) -> Registry:
        return Registry.model_validate({"registry_version": 1, "experiments": entries})

    def run_compare(entries: list[dict], **kwargs):
        return compare(registry(entries), discover_runs(results), repo_root=tmp_path, price_book=PriceBook(pricing_version=1), cutoffs=(1, 4), **kwargs)

    return {"write_run": write_run, "run_compare": run_compare, "results": results, "registry": registry}


def _row(result: dict, exp_id: str) -> dict:
    return next(r for r in result["rows"] if r["experiment_id"] == exp_id)


def test_complete_experiment_with_ranking_answer_metrics_and_contract(lab):
    lab["write_run"]("exp-a", "20261001T000000Z", [_item("Q1"), _item("Q2", contexts=("A0", "B0"))])
    row = _row(lab["run_compare"]([{"id": "01", "name": "A", "run_names": ["exp-a"]}]), "01")
    assert row["status"] == Status.COMPLETE.value
    for key in (
        "experiment_id", "experiment_name", "run_id", "git_commit", "config_fingerprint", "dataset_hash", "corpus_hash",
        "embedding_config", "retrieval_config", "generator_config", "judge_config", "metrics", "status", "started_at", "completed_at",
    ):  # fmt: skip
        assert key in row, key
    assert row["fingerprint_verified"] is True
    assert row["dataset_hash"] == DATASET_SHA and row["corpus_hash"] == "c" * 64
    assert row["retrieval_config"]["top_k"] == 4 and row["judge_config"]["llm"]["model"] == "qwen/qwen3.8-27b"
    assert row["completed_at"] == "2026-10-01T01:00:00+00:00"
    chunk = row["ranking"]["paired"]["chunk"]["mean"]
    assert chunk["recall@1"] == 0.5 and chunk["mrr"] == pytest.approx(0.75)  # Q1 rank 1, Q2 rank 2
    assert row["answer"]["metrics"]["faithfulness"] == {"mean": 1.0, "n": 2}
    assert row["answer"]["pass"] == 2 and row["answer"]["latency_p50_s"] == 2.0


def test_tampered_config_fails_fingerprint_verification(lab):
    run_dir = lab["write_run"]("exp-a", "20261001T000000Z", [_item("Q1")])
    cfg = yaml.safe_load((run_dir / "config.yaml").read_text(encoding="utf-8"))
    cfg["system"]["retrieval"]["top_k"] = 5
    (run_dir / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    assert _row(lab["run_compare"]([{"id": "01", "name": "A", "run_names": ["exp-a"]}]), "01")["fingerprint_verified"] is False


def test_not_run_is_a_state_not_zero(lab):
    result = lab["run_compare"]([{"id": "02", "name": "Hybrid"}])
    row = _row(result, "02")
    assert row == {"experiment_id": "02", "experiment_name": "Hybrid", "role": "experiment", "status": "NOT RUN"}
    table = render_markdown(result, (4,))
    assert "| 02 Hybrid | NOT RUN | — |" in table and " 0.000 " not in table
    assert lab["run_compare"]([{"id": "02", "name": "Hybrid"}], include_not_run=False)["rows"] == []


def test_partial_experiment_is_in_progress_and_missing_metric_is_none(lab):
    lab["write_run"]("exp-a", "20261001T000000Z", [_item("Q1"), _item("Q2", metric=None, label="OTHER")])
    row = _row(lab["run_compare"]([{"id": "05", "name": "M", "run_names": ["exp-a"]}]), "05")
    assert row["status"] == Status.IN_PROGRESS.value and row["completed_at"] is None
    assert row["answer"]["pending_items"] == 1
    assert row["answer"]["metrics"]["faithfulness"] == {"mean": 1.0, "n": 1}  # the missing value is not a 0
    assert row["answer"]["metrics"]["answer_correctness"] == {"mean": None, "n": 0}


def test_finalized_run_with_gaps_is_complete(lab):
    run_dir = lab["write_run"]("exp-a", "20261001T000000Z", [_item("Q1"), _item("Q2", metric=None, label="OTHER")])
    row = _row(lab["run_compare"]([{"id": "01", "name": "A", "run_names": ["exp-a"], "final_runs": [run_dir.name]}]), "01")
    assert row["status"] == Status.COMPLETE.value and "missing a value" in row["status_detail"]


def test_failed_experiment_unreadable_or_all_errors(lab):
    broken = lab["results"] / "20261002T000000Z-exp-b-12345678-bbbbbb"
    broken.mkdir()
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")
    lab["write_run"]("exp-c", "20261003T000000Z", [_item("Q1", error="RuntimeError: down")])
    result = lab["run_compare"]([{"id": "b", "name": "B", "run_names": ["exp-b"]}, {"id": "c", "name": "C", "run_names": ["exp-c"]}])
    assert _row(result, "b")["status"] == "FAILED" and "unreadable" in _row(result, "b")["status_detail"]
    assert _row(result, "c")["status"] == "FAILED" and "ranking" not in _row(result, "c")
    assert "| b B | FAILED | — |" in render_markdown(result)


def test_duplicate_runs_latest_wins_unless_pinned_and_others_are_listed(lab):
    old = lab["write_run"]("exp-a", "20261001T000000Z", [_item("Q1", label="OTHER")], suffix="oldold")
    new = lab["write_run"]("exp-a", "20261005T000000Z", [_item("Q1")], suffix="newnew")
    row = _row(lab["run_compare"]([{"id": "01", "name": "A", "run_names": ["exp-a"]}]), "01")
    assert row["run_id"] == new.name and row["other_runs"] == [old.name]
    pinned = _row(lab["run_compare"]([{"id": "01", "name": "A", "run_names": ["exp-a"], "pinned_run": old.name}]), "01")
    assert pinned["run_id"] == old.name


def test_paired_ranking_excludes_items_any_compared_run_failed(lab):
    lab["write_run"]("exp-a", "20261001T000000Z", [_item("Q1"), _item("Q2", contexts=("B0",))])
    lab["write_run"]("exp-b", "20261002T000000Z", [_item("Q1"), _item("Q2", error="RateLimitError")])
    result = lab["run_compare"]([{"id": "a", "name": "A", "run_names": ["exp-a"]}, {"id": "b", "name": "B", "run_names": ["exp-b"]}])
    assert result["paired_excluded_items"] == ["Q2"]
    b = _row(result, "b")["ranking"]
    assert b["paired"]["chunk"]["n"] == 1 and b["paired"]["chunk"]["mean"]["mrr"] == 1.0
    assert b["all_items"]["chunk"]["mean"]["mrr"] == 0.5  # the failed item counts as nothing retrieved


def test_retrieval_only_experiment_and_unregistered_runs(lab):
    lab["write_run"]("exp-a", "20261001T000000Z", [_item("Q1", metric=None)])
    lab["write_run"]("stray", "20261001T000000Z", [_item("Q1")])
    result = lab["run_compare"]([{"id": "B2", "name": "MMR", "run_names": ["exp-a"], "answer_eval": "skipped"}])
    row = _row(result, "B2")
    assert row["status"] == Status.RETRIEVAL_ONLY.value and row["answer"] is None and row["ranking"]
    assert result["unregistered_runs"][0].endswith("-stray-" + row["config_fingerprint"][:8] + "-aaaaaa")


def test_missing_qrels_leaves_ranking_unavailable(lab, tmp_path):
    lab["write_run"]("exp-a", "20261001T000000Z", [_item("Q1")])
    shutil.rmtree(tmp_path / "eval" / "datasets")
    row = _row(lab["run_compare"]([{"id": "01", "name": "A", "run_names": ["exp-a"]}]), "01")
    assert row["ranking"] is None and "no qrels" in row["ranking_unavailable"]


def test_registry_rejects_duplicates_and_the_repo_registry_is_valid(lab):
    with pytest.raises(ValidationError):
        lab["registry"]([{"id": "01", "name": "A"}, {"id": "01", "name": "B"}])
    with pytest.raises(ValidationError):
        lab["registry"]([{"id": "01", "name": "A", "run_names": ["x"]}, {"id": "02", "name": "B", "run_names": ["x"]}])
    registry = load_registry(REPO_ROOT / "eval" / "experiments.yaml")
    assert [e.id for e in registry.experiments if e.role == "experiment"] == [f"{i:02d}" for i in range(1, 12)]


def test_cost_is_null_without_a_documented_price():
    tokens = {"gen-model": {"input_tokens": 2_000_000, "output_tokens": 1_000_000}}
    assert run_cost(tokens, PriceBook(pricing_version=1), date(2026, 10, 1)) == {"total": None, "currency": None, "by_model": {"gen-model": None}}
    book = PriceBook.model_validate(
        {
            "pricing_version": 1,
            "prices": [
                {"provider": "p", "model": "gen-model", "input_price_per_million": 1.0, "output_price_per_million": 2.0, "currency": "USD", "effective_date": "2026-09-01", "source_url": "https://example.com/old"},
                {"provider": "p", "model": "gen-model", "input_price_per_million": 3.0, "output_price_per_million": 4.0, "currency": "USD", "effective_date": "2026-11-01", "source_url": "https://example.com/new"},
            ],
        }
    )
    cost = run_cost(tokens, book, date(2026, 10, 1))  # the price in effect on the run date
    assert cost["total"] == pytest.approx(4.0) and cost["by_model"]["gen-model"]["source_url"].endswith("/old")
    assert run_cost(tokens, book, date(2026, 8, 1))["total"] is None
    assert load_price_book(REPO_ROOT / "eval" / "pricing.yaml").prices == []


def test_experiment_filter_and_paired_wins_ties_losses_against_the_baseline(lab):
    lab["write_run"]("base", "20261001T000000Z", [_item("Q1", contexts=("B0", "A0")), _item("Q2", contexts=("B0",))])
    lab["write_run"]("treat", "20261002T000000Z", [_item("Q1"), _item("Q2", contexts=("A0",))])
    lab["write_run"]("other", "20261003T000000Z", [_item("Q1"), _item("Q2", error="RateLimitError")])
    entries = [
        {"id": "01", "name": "Base", "run_names": ["base"]},
        {"id": "02", "name": "Treat", "run_names": ["treat"]},
        {"id": "03", "name": "Other", "run_names": ["other"]},
    ]
    result = lab["run_compare"](entries, experiments={"01", "02"})
    assert [r["experiment_id"] for r in result["rows"]] == ["01", "02"]
    assert result["paired_excluded_items"] == []  # the unrelated run's failure does not shrink the 01/02 comparison
    vs = _row(result, "02")["ranking"]["vs_baseline"]
    assert vs["baseline"] == "01" and vs["chunk"]["n"] == 2
    mrr = vs["chunk"]["metrics"]["mrr"]
    assert (mrr["wins"], mrr["ties"], mrr["losses"]) == (1, 0, 1)  # Q1: 0.5 -> 1, Q2: 1 -> 0
    assert mrr["delta"] == pytest.approx(-0.25)
    assert "vs_baseline" not in _row(result, "01")["ranking"]
    assert _row(result, "02")["ranking"]["paired_items"] == ["Q1", "Q2"]
