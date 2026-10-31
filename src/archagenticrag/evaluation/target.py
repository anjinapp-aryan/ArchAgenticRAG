"""Adapter for the system under test (any LangGraph graph / LangChain runnable).

Token usage comes from LangChain's own ``UsageMetadataCallbackHandler``. The custom
callbacks time retriever calls and count LLM calls, which LangChain does not aggregate
for us, and record every retriever call's ranked results (``retrieval_trace``).
"""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler

from archagenticrag.evaluation.config import EvalConfig, TargetRef
from archagenticrag.evaluation.retrieval_trace import RetrievalRecorder, doc_id_of
from archagenticrag.provider_fallback import collect_provider_calls


class TargetError(RuntimeError):
    pass


def load_factory(target: TargetRef):
    module_name, func_name = target.factory.split(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise TargetError(
            f"cannot import target module {module_name!r} ({exc}). Check target.factory in the config."
        ) from exc
    factory = getattr(module, func_name, None)
    if factory is None:
        raise TargetError(f"{module_name!r} has no attribute {func_name!r}")
    return factory


def build_target(config: EvalConfig) -> Any:
    factory = load_factory(config.target)
    return factory(system=config.system.model_dump(mode="json"), **config.target.kwargs)


class _CallStats(BaseCallbackHandler):
    def __init__(self) -> None:
        self.llm_calls = 0
        self.retriever_seconds = 0.0
        self.llm_seconds = 0.0
        self._starts: dict[Any, float] = {}
        self._llm_starts: dict[Any, float] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):  # noqa: ANN001
        self.llm_calls += 1
        self._llm_starts[run_id] = time.perf_counter()

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):  # noqa: ANN001
        self.llm_calls += 1
        self._llm_starts[run_id] = time.perf_counter()

    def _end_llm(self, run_id) -> None:  # noqa: ANN001
        start = self._llm_starts.pop(run_id, None)
        if start is not None:
            self.llm_seconds += time.perf_counter() - start

    def on_llm_end(self, response, *, run_id, **kwargs):  # noqa: ANN001
        self._end_llm(run_id)

    # LangChain passes the error positionally and may also pass `response=` as a keyword,
    # so this cannot simply alias on_llm_end.
    def on_llm_error(self, error, *, run_id, **kwargs):  # noqa: ANN001
        self._end_llm(run_id)

    def on_retriever_start(self, serialized, query, *, run_id, **kwargs):  # noqa: ANN001
        self._starts[run_id] = time.perf_counter()

    def _end_retriever(self, run_id) -> None:  # noqa: ANN001
        start = self._starts.pop(run_id, None)
        if start is not None:
            self.retriever_seconds += time.perf_counter() - start

    def on_retriever_end(self, documents, *, run_id, **kwargs):  # noqa: ANN001
        self._end_retriever(run_id)

    def on_retriever_error(self, error, *, run_id, **kwargs):  # noqa: ANN001
        self._end_retriever(run_id)


@dataclass
class TargetResult:
    answer: str
    contexts: list[str]
    context_doc_ids: list[str | None]
    latency_s: float
    retrieval_latency_s: float
    llm_calls: int
    generation_latency_s: float = 0.0  # time inside LLM calls
    usage: dict[str, dict[str, int]] = field(default_factory=dict)  # model -> token counts
    error: str | None = None
    recorded: dict[str, Any] = field(default_factory=dict)  # TargetRef.record_keys -> output values
    retrieval_results: list[dict[str, Any]] = field(default_factory=list)  # final ranked contexts
    retrieval_calls: list[dict[str, Any]] = field(default_factory=list)  # every retriever call
    provider_calls: list[dict[str, Any]] = field(default_factory=list)  # fallback-transport records (fallback mode only)


def _normalize_contexts(raw: Any) -> tuple[list[str], list[str | None]]:
    texts: list[str] = []
    ids: list[str | None] = []
    for ctx in raw or []:
        if isinstance(ctx, str):
            texts.append(ctx)
            ids.append(None)
        elif hasattr(ctx, "page_content"):  # langchain Document
            texts.append(ctx.page_content)
            ids.append(doc_id_of(getattr(ctx, "metadata", {}) or {}))
        else:
            raise TargetError(f"unsupported context type {type(ctx).__name__}")
    return texts, ids


async def run_target(target: Any, ref: TargetRef, question: str, extra_callbacks: list | None = None) -> TargetResult:
    """Invoke the system once. Never raises: failures are returned in ``error``."""
    usage = UsageMetadataCallbackHandler()
    stats = _CallStats()
    recorder = RetrievalRecorder()
    callbacks = [usage, stats, recorder, *(extra_callbacks or [])]
    start = time.perf_counter()
    with collect_provider_calls() as provider_calls:  # filled by the fallback transport, if any
        try:
            if hasattr(target, "ainvoke"):
                output = await target.ainvoke({ref.input_key: question}, config={"callbacks": callbacks})
            else:
                output = target.invoke({ref.input_key: question}, config={"callbacks": callbacks})
            latency = time.perf_counter() - start
            answer = output[ref.answer_key]
            if not isinstance(answer, str):
                answer = getattr(answer, "content", None) or str(answer)
            raw_contexts = output.get(ref.contexts_key)
            contexts, ids = _normalize_contexts(raw_contexts)
            recorded = {key: output.get(key) for key in ref.record_keys}
            retrieval_results = recorder.final_results(list(raw_contexts or []))
            error = None
        except Exception as exc:
            latency = time.perf_counter() - start
            answer, contexts, ids, recorded, retrieval_results = "", [], [], {}, []
            error = f"{type(exc).__name__}: {exc}"
    return TargetResult(
        answer=answer,
        contexts=contexts,
        context_doc_ids=ids,
        latency_s=latency,
        retrieval_latency_s=stats.retriever_seconds,
        llm_calls=stats.llm_calls,
        generation_latency_s=stats.llm_seconds,
        usage={model: dict(meta) for model, meta in usage.usage_metadata.items()},
        error=error,
        recorded=recorded,
        retrieval_results=retrieval_results,
        retrieval_calls=recorder.calls,
        provider_calls=provider_calls,
    )
