"""Ragas metric wiring.

All scoring is done by Ragas (``ragas.metrics.collections``, the non-deprecated API in
ragas 0.4.x). This module only decides which metric applies to which item and turns
exceptions into recorded errors instead of silently dropping them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from archagenticrag.evaluation.config import JudgeConfig, MetricName
from archagenticrag.evaluation.dataset import ExpectedBehavior, GoldenItem

# Which metrics are meaningful for which kind of item.
#  - answer:  the four Ragas RAG metrics plus answer_correctness (Ragas AnswerCorrectness,
#             recall-weighted, see the builder). None of the four RAG metrics compares the answer with the
#             ground truth, so without it a faithful but wrong answer would pass.
#  - clarify: Ragas AnswerRelevancy scores noncommittal answers as 0, which would punish
#             a correct clarifying question, so it is not applied. The reference lists
#             the interpretations, so context recall still tells us whether retrieval
#             surfaced them. The clarification judgement checks ambiguity handling.
#  - abstain: the reference is "not in corpus", so context metrics are meaningless.
#             Only the abstention judgement applies.
APPLICABLE: dict[ExpectedBehavior, set[str]] = {
    ExpectedBehavior.ANSWER: {
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_recall",
        "answer_correctness",
    },
    ExpectedBehavior.CLARIFY: {"faithfulness", "context_recall", "clarification"},
    ExpectedBehavior.ABSTAIN: {"abstention"},
}

# Discrete judgements built with Ragas' DiscreteMetric: name -> (passing value, failing value).
DISCRETE_VALUES: dict[str, tuple[str, str]] = {
    "abstention": ("abstained", "answered"),
    "clarification": ("handled", "ignored"),
}

ABSTENTION_PROMPT = (
    "You are checking whether an assistant declined to answer.\n"
    "Question: {user_input}\n"
    "Assistant response: {response}\n\n"
    "Return 'abstained' if the response says it cannot answer, that the information is not "
    "available in the provided documents, or otherwise declines to give a substantive answer. "
    "Return 'answered' if it gives a substantive answer, even a hedged one."
)

CLARIFICATION_PROMPT = (
    "The following question is ambiguous: it has no clear referent or several plausible "
    "interpretations.\n"
    "Question: {user_input}\n"
    "Assistant response: {response}\n\n"
    "Return 'handled' if the response asks a clarifying question, or explicitly names more than "
    "one interpretation and addresses them separately. Return 'ignored' if it silently picks a "
    "single interpretation and answers only that."
)


@dataclass
class MetricOutcome:
    name: str
    value: float | None
    reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RagasScorer:
    """Scores one (item, answer, contexts) triple with the configured Ragas metrics."""

    def __init__(self, metric_names: list[MetricName], metrics: dict[str, Any], llm: Any):
        self.metric_names = metric_names
        self._metrics = metrics
        self._llm = llm  # DiscreteMetric takes the llm per call

    @classmethod
    def from_judge_config(cls, metric_names: list[MetricName], judge: JudgeConfig) -> RagasScorer:
        from ragas.embeddings import OpenAIEmbeddings
        from ragas.llms import llm_factory
        from ragas.metrics import DiscreteMetric
        from ragas.metrics.collections import (
            AnswerCorrectness,
            AnswerRelevancy,
            ContextPrecisionWithReference,
            ContextRecall,
            Faithfulness,
        )

        from archagenticrag.evaluation.providers import async_client

        llm_kwargs = {} if judge.llm.temperature is None else {"temperature": judge.llm.temperature}
        llm = llm_factory(judge.llm.model, provider="openai", client=async_client(judge.llm.provider), **llm_kwargs)
        builders = {
            "faithfulness": lambda: Faithfulness(llm=llm),
            "answer_relevancy": lambda: AnswerRelevancy(
                llm=llm,
                embeddings=OpenAIEmbeddings(client=async_client(judge.embedding.provider), model=judge.embedding.model),
            ),
            "context_precision": lambda: ContextPrecisionWithReference(llm=llm),
            "context_recall": lambda: ContextRecall(llm=llm),
            # AnswerCorrectness extracts claims with the question in view. FactualCorrectness does
            # not, and turned short references like "79 characters." into unverifiable claims
            # ("The text contains 79 characters."), scoring correct answers 0. weights=[1, 0]
            # drops the embedding-similarity term; beta=5 weights recall over precision, so
            # correct detail beyond the short ground truth is barely penalised (ADR 008).
            "answer_correctness": lambda: AnswerCorrectness(llm=llm, weights=[1.0, 0.0], beta=5.0),
            "abstention": lambda: DiscreteMetric(
                name="abstention", allowed_values=list(DISCRETE_VALUES["abstention"]), prompt=ABSTENTION_PROMPT
            ),
            "clarification": lambda: DiscreteMetric(
                name="clarification",
                allowed_values=list(DISCRETE_VALUES["clarification"]),
                prompt=CLARIFICATION_PROMPT,
            ),
        }
        return cls(metric_names, {name: builders[name]() for name in metric_names}, llm)

    def applicable(self, item: GoldenItem) -> list[str]:
        allowed = set(APPLICABLE[item.expected_behavior])
        if not item.evidence:  # e.g. a no-referent ambiguous question: nothing to recall
            allowed -= {"context_precision", "context_recall"}
        return [m for m in self.metric_names if m in allowed]

    async def score(
        self, item: GoldenItem, answer: str, contexts: list[str], only: list[str] | None = None
    ) -> list[MetricOutcome]:
        """Score the applicable metrics, or just those in ``only`` (used when resuming a run)."""
        names = [n for n in self.applicable(item) if only is None or n in only]
        return [await self._score_one(name, item, answer, contexts) for name in names]

    async def _score_one(self, name: str, item: GoldenItem, answer: str, contexts: list[str]) -> MetricOutcome:
        metric = self._metrics[name]
        try:
            if name == "faithfulness":
                result = await metric.ascore(user_input=item.question, response=answer, retrieved_contexts=contexts)
            elif name == "answer_relevancy":
                result = await metric.ascore(user_input=item.question, response=answer)
            elif name == "context_precision":
                result = await metric.ascore(
                    user_input=item.question, reference=item.ground_truth, retrieved_contexts=contexts
                )
            elif name == "context_recall":
                result = await metric.ascore(
                    user_input=item.question, retrieved_contexts=contexts, reference=item.ground_truth
                )
            elif name == "answer_correctness":
                result = await metric.ascore(user_input=item.question, response=answer, reference=item.ground_truth)
            elif name in DISCRETE_VALUES:
                result = await metric.ascore(llm=self._llm, user_input=item.question, response=answer)
                passing, failing = DISCRETE_VALUES[name]
                if result.value not in (passing, failing):
                    return MetricOutcome(name, None, result.reason, error=f"unexpected label {result.value!r}")
                return MetricOutcome(name, 1.0 if result.value == passing else 0.0, result.reason)
            else:  # pragma: no cover - guarded by config validation
                raise ValueError(f"unknown metric {name}")
        except Exception as exc:  # recorded, never swallowed
            return MetricOutcome(name, None, error=f"{type(exc).__name__}: {exc}")
        value = result.value
        if value is None or value != value:  # None or NaN
            return MetricOutcome(name, None, getattr(result, "reason", None), error="metric returned no value")
        return MetricOutcome(name, float(value), getattr(result, "reason", None))
