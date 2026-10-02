"""Resuming a run that stopped part-way: keep what succeeded, redo only what failed."""

from __future__ import annotations

import json

import pytest

from archagenticrag.evaluation.metrics import MetricOutcome
from archagenticrag.evaluation.persistence import read_run
from archagenticrag.evaluation.resume import ResumeError, is_daily_quota_error, resume_evaluation

from .test_runner import FakeScorer, _run, fake_target

DAILY = "Error code: 429 - Rate limit reached on tokens per day (TPD): Limit 200000"
MINUTE = "Error code: 429 - Rate limit reached on tokens per minute (TPM): Limit 8000"


class QuotaScorer(FakeScorer):
    """FakeScorer whose given metrics fail with a given error; records what it was asked."""

    def __init__(self, failing: dict[str, set[str]] | None = None, error: str = DAILY):
        super().__init__()
        self.failing = failing or {}
        self.error = error
        self.calls: list[tuple[str, list[str] | None]] = []

    async def score(self, item, answer, contexts, only=None):
        self.calls.append((item.id, only))
        outcomes = await super().score(item, answer, contexts)
        if only is not None:
            outcomes = [o for o in outcomes if o.name in only]
        bad = self.failing.get(item.id, set())
        return [MetricOutcome(o.name, None, error=self.error) if o.name in bad else o for o in outcomes]


def _items(run_dir):
    return {r["id"]: r for r in read_run(run_dir)["items"]}


async def test_resume_rescores_only_failed_metrics_and_keeps_the_rest(mini_repo):
    root, config_path = mini_repo()
    run_dir = _run(root, config_path, scorer=QuotaScorer({"Q1": {"faithfulness", "context_recall"}}, error=MINUTE))
    before = _items(run_dir)
    assert before["Q1"]["metrics"]["faithfulness"]["value"] is None

    scorer = QuotaScorer()
    session = await resume_evaluation(run_dir, repo_root=root, target=fake_target(), scorer=scorer)

    assert scorer.calls == [("Q1", ["faithfulness", "context_recall"])]
    after = _items(run_dir)
    assert after["Q1"]["metrics"]["faithfulness"]["value"] == 1.0
    assert after["Q1"]["metrics"]["answer_relevancy"] == before["Q1"]["metrics"]["answer_relevancy"]
    assert after["Q1"]["answer"] == before["Q1"]["answer"]
    assert session["still_pending_items"] == 0
    manifest = read_run(run_dir)["manifest"]
    assert manifest["resumes"][0]["rescored_metrics"] == {"Q1": ["faithfulness", "context_recall"]}
    assert read_run(run_dir)["summary"]["metric_value_missing"] == {}


async def test_resume_reruns_failed_system_calls(mini_repo):
    root, config_path = mini_repo()
    run_dir = _run(root, config_path, target=fake_target(fail_on="life"))
    assert _items(run_dir)["Q1"]["error"]

    session = await resume_evaluation(run_dir, repo_root=root, target=fake_target(), scorer=QuotaScorer())

    q1 = _items(run_dir)["Q1"]
    assert q1["error"] is None and q1["answer"] == "42."
    assert q1["metrics"]["answer_correctness"]["value"] == 1.0
    assert q1["triage"]["label"] == "PASS"
    assert session["rerun_items"] == ["Q1"]


async def test_resume_stops_at_a_daily_quota_and_can_continue_later(mini_repo):
    root, config_path = mini_repo()
    everything_fails = QuotaScorer({i: {"faithfulness", "abstention", "clarification"} for i in ("Q1", "Q2", "Q3")})
    run_dir = _run(root, config_path, scorer=everything_fails)
    pending_before = [i for i, r in _items(run_dir).items() if any(m["error"] for m in r["metrics"].values())]
    assert len(pending_before) >= 2

    still_out = QuotaScorer({i: {"faithfulness", "abstention", "clarification"} for i in ("Q1", "Q2", "Q3")})
    session = await resume_evaluation(run_dir, repo_root=root, target=fake_target(), scorer=still_out)
    assert len(still_out.calls) == 1  # stopped after the first daily-quota error
    assert session["stopped_on_daily_quota"].startswith(pending_before[0])
    assert session["still_pending_items"] == len(pending_before)

    session = await resume_evaluation(run_dir, repo_root=root, target=fake_target(), scorer=QuotaScorer())
    assert session["still_pending_items"] == 0
    assert len(read_run(run_dir)["manifest"]["resumes"]) == 2


async def test_resume_refuses_a_changed_dataset(mini_repo):
    root, config_path = mini_repo()
    run_dir = _run(root, config_path)
    dataset_path = next(root.rglob("golden.json"))
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    data["description"] = "edited"
    dataset_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ResumeError, match="dataset changed"):
        await resume_evaluation(run_dir, repo_root=root, target=fake_target(), scorer=QuotaScorer())


def test_daily_quota_detection():
    assert is_daily_quota_error(DAILY)
    assert not is_daily_quota_error(MINUTE)
    assert not is_daily_quota_error(None)
