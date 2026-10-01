"""End-to-end runner tests: real Langfuse run_experiment (offline), fake target and judge."""

from __future__ import annotations

import pytest
from langchain_core.runnables import RunnableLambda

from archagenticrag.evaluation.metrics import MetricOutcome
from archagenticrag.evaluation.persistence import read_run
from archagenticrag.evaluation.runner import RunError, run_evaluation
from archagenticrag.evaluation.target import TargetError


def fake_target(fail_on: str | None = None):
    def run(inputs: dict) -> dict:
        question = inputs["question"]
        if fail_on and fail_on in question:
            raise RuntimeError("generator unavailable")
        if "life" in question:
            return {"answer": "42.", "documents": ["The answer to life is 42."]}
        return {"answer": "I cannot answer from the documents.", "documents": []}

    return RunnableLambda(run)


class FakeScorer:
    def __init__(self, raise_for: str | None = None):
        self.raise_for = raise_for
        self.seen: list[str] = []

    async def score(self, item, answer, contexts):
        self.seen.append(item.id)
        if item.id == self.raise_for:
            raise ValueError("judge returned invalid JSON")
        if item.expected_behavior.value == "abstain":
            return [MetricOutcome("abstention", 1.0 if "cannot" in answer else 0.0)]
        if item.expected_behavior.value == "clarify":
            return [MetricOutcome("clarification", 0.0, "picked one meaning")]
        return [
            MetricOutcome(name, 1.0)
            for name in ("faithfulness", "answer_relevancy", "context_precision", "context_recall", "answer_correctness")
        ]


def _run(root, config_path, **kwargs):
    from archagenticrag.evaluation.langfuse_sync import make_client

    kwargs.setdefault("target", fake_target())
    kwargs.setdefault("scorer", FakeScorer())
    kwargs.setdefault("langfuse_client", make_client(enabled=False))
    return run_evaluation(config_path, repo_root=root, **kwargs)


def test_full_run_persists_every_item_with_manifest(mini_repo):
    root, config_path = mini_repo()
    run_dir = _run(root, config_path)
    run = read_run(run_dir)

    assert [r["id"] for r in run["items"]] == ["Q1", "Q2", "Q3"]
    labels = {r["id"]: r["triage"]["label"] for r in run["items"]}
    assert labels == {"Q1": "PASS", "Q2": "PASS", "Q3": "AMBIGUITY"}
    q1 = run["items"][0]
    assert q1["retrieval"]["evidence_in_context"] == 1.0
    assert q1["metrics"]["faithfulness"]["value"] == 1.0

    manifest = run["manifest"]
    for key in ("run_id", "started_at", "finished_at", "git", "packages", "config", "config_fingerprint", "dataset", "corpus"):
        assert key in manifest
    assert manifest["dataset"]["version"] == "0.0.1"
    assert manifest["packages"]["ragas"] == "0.4.3"
    assert manifest["config"]["system"]["retrieval"]["top_k"] == 4
    assert (run_dir / "config.yaml").exists()
    assert run["summary"]["items"] == 3
    assert run["summary"]["failure_matrix"]["AMBIGUITY"]["count"] == 1


def test_target_failure_is_recorded_not_dropped(mini_repo):
    root, config_path = mini_repo()
    scorer = FakeScorer()
    run = read_run(_run(root, config_path, target=fake_target(fail_on="World Cup"), scorer=scorer))
    q2 = next(r for r in run["items"] if r["id"] == "Q2")
    assert q2["error"] == "RuntimeError: generator unavailable"
    assert q2["triage"]["label"] == "OTHER"
    assert "Q2" not in scorer.seen  # nothing to judge
    assert run["summary"]["system_errors"] == 1


def test_scorer_failure_is_recorded_not_dropped(mini_repo):
    root, config_path = mini_repo()
    run = read_run(_run(root, config_path, scorer=FakeScorer(raise_for="Q1")))
    q1 = run["items"][0]
    assert "judge returned invalid JSON" in q1["metrics"]["_scorer"]["error"]
    assert q1["triage"]["label"] == "OTHER"


def test_untraceable_dataset_blocks_the_run(mini_repo):
    root, config_path = mini_repo()
    (root / "data" / "corpus" / "mini" / "doc-a.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(RunError, match="not traceable"):
        _run(root, config_path)


def test_missing_phase1_target_fails_fast(mini_repo):
    root, config_path = mini_repo()
    with pytest.raises(TargetError):
        _run(root, config_path, target=None)


def test_back_to_back_runs_get_separate_directories(mini_repo):
    root, config_path = mini_repo()
    first = _run(root, config_path)
    second = _run(root, config_path)
    assert first != second
    assert first.exists() and second.exists()


def test_ragas_tracking_is_disabled_by_default(mini_repo, monkeypatch):
    monkeypatch.delenv("RAGAS_DO_NOT_TRACK", raising=False)
    root, config_path = mini_repo()
    _run(root, config_path)
    import os

    assert os.environ["RAGAS_DO_NOT_TRACK"] == "true"
