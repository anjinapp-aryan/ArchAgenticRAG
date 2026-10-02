from __future__ import annotations

import math

import pytest
from ragas.metrics.result import MetricResult

from archagenticrag.evaluation.config import JudgeConfig
from archagenticrag.evaluation.dataset import load_dataset
from archagenticrag.evaluation.metrics import RagasScorer

from .conftest import GOLDEN_PATH

ALL = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "answer_correctness",
    "abstention",
    "clarification",
]


class FakeMetric:
    """Stands in for a Ragas metric object: records calls, returns a fixed MetricResult."""

    def __init__(self, value=0.9, exc: Exception | None = None):
        self.value = value
        self.exc = exc
        self.calls: list[dict] = []

    async def ascore(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return MetricResult(value=self.value, reason="because")


def _item(item_id: str):
    return next(i for i in load_dataset(GOLDEN_PATH).items if i.id == item_id)


def _scorer(**overrides) -> tuple[RagasScorer, dict]:
    metrics = {name: FakeMetric() for name in ALL}
    metrics["abstention"] = FakeMetric("abstained")
    metrics["clarification"] = FakeMetric("handled")
    metrics.update(overrides)
    return RagasScorer(ALL, metrics, llm=object()), metrics


@pytest.mark.parametrize(
    ("item_id", "expected"),
    [
        ("A01", ["faithfulness", "answer_relevancy", "context_precision", "context_recall", "answer_correctness"]),
        ("E01", ["abstention"]),
        ("D01", ["faithfulness", "context_recall", "clarification"]),
        ("D02", ["faithfulness", "clarification"]),  # no evidence: no context metrics
    ],
)
def test_applicable_metrics_depend_on_expected_behavior(item_id, expected):
    scorer, _ = _scorer()
    assert scorer.applicable(_item(item_id)) == expected


async def test_answer_item_passes_ragas_the_right_fields():
    scorer, metrics = _scorer()
    item = _item("A01")
    outcomes = await scorer.score(item, "79 characters", ["Limit all lines to a maximum of 79 characters."])
    assert {o.name: o.value for o in outcomes} == {
        "faithfulness": 0.9,
        "answer_relevancy": 0.9,
        "context_precision": 0.9,
        "context_recall": 0.9,
        "answer_correctness": 0.9,
    }
    assert metrics["faithfulness"].calls[0]["retrieved_contexts"] == ["Limit all lines to a maximum of 79 characters."]
    assert metrics["context_recall"].calls[0]["reference"] == item.ground_truth
    assert metrics["answer_correctness"].calls[0] == {
        "user_input": item.question,
        "response": "79 characters",
        "reference": item.ground_truth,
    }


async def test_metric_exception_is_recorded_not_raised():
    scorer, _ = _scorer(faithfulness=FakeMetric(exc=TimeoutError("judge timed out")))
    outcomes = {o.name: o for o in await scorer.score(_item("A01"), "a", ["c"])}
    assert outcomes["faithfulness"].value is None
    assert "TimeoutError" in outcomes["faithfulness"].error
    assert outcomes["context_recall"].value == 0.9  # other metrics still scored


async def test_nan_metric_value_is_recorded_as_missing():
    scorer, _ = _scorer(faithfulness=FakeMetric(math.nan))
    outcomes = {o.name: o for o in await scorer.score(_item("A01"), "a", ["c"])}
    assert outcomes["faithfulness"].value is None
    assert outcomes["faithfulness"].error == "metric returned no value"


@pytest.mark.parametrize(("label", "value"), [("abstained", 1.0), ("answered", 0.0)])
async def test_abstention_labels_map_to_scores(label, value):
    scorer, metrics = _scorer(abstention=FakeMetric(label))
    (outcome,) = await scorer.score(_item("E01"), "I cannot answer that.", [])
    assert outcome.value == value
    assert "llm" in metrics["abstention"].calls[0]  # DiscreteMetric needs the judge per call


async def test_unexpected_discrete_label_is_an_error():
    scorer, _ = _scorer(clarification=FakeMetric("maybe"))
    outcomes = {o.name: o for o in await scorer.score(_item("D02"), "Which one?", [])}
    assert outcomes["clarification"].value is None
    assert "unexpected label" in outcomes["clarification"].error


def test_real_ragas_metrics_build_from_judge_config(monkeypatch):
    """Builds the real Ragas metric objects (no API call is made at construction)."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    judge = JudgeConfig.model_validate(
        {"llm": {"provider": "gemini", "model": "m"}, "embedding": {"provider": "gemini", "model": "e"}}
    )
    scorer = RagasScorer.from_judge_config(ALL, judge)
    assert set(scorer._metrics) == set(ALL)


def test_missing_provider_key_fails_loudly(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    judge = JudgeConfig.model_validate(
        {"llm": {"provider": "gemini", "model": "m"}, "embedding": {"provider": "gemini", "model": "e"}}
    )
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        RagasScorer.from_judge_config(["faithfulness"], judge)
