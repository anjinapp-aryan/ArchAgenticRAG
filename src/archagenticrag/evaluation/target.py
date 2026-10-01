"""Adapter for the system under test (any LangGraph graph / LangChain runnable).

Token usage comes from LangChain's own ``UsageMetadataCallbackHandler``. The only
custom callback here times retriever calls and counts LLM calls, which LangChain
does not aggregate for us.
"""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler, UsageMetadataCallbackHandler

from archagenticrag.evaluation.config import EvalConfig, TargetRef


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

    def on_llm_end(self, response, *, run_id, **kwargs):  # noqa: ANN001
        start = self._llm_starts.pop(run_id, None)
        if start is not None:
            self.llm_seconds += time.perf_counter() - start

    on_llm_error = on_llm_end

    def on_retriever_start(self, serialized, query, *, run_id, **kwargs):  # noqa: ANN001
        self._starts[run_id] = time.perf_counter()

    def on_retriever_end(self, documents, *, run_id, **kwargs):  # noqa: ANN001
        start = self._starts.pop(run_id, None)
        if start is not None:
            self.retriever_seconds += time.perf_counter() - start

    on_retriever_error = on_retriever_end


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


def _doc_id(metadata: dict) -> str | None:
    for key in ("doc_id", "source", "file_path"):
        if metadata.get(key):
            return PurePath(str(metadata[key])).stem  # "data/corpus/peps/pep-0484.rst" -> "pep-0484"
    return None


def _normalize_contexts(raw: Any) -> tuple[list[str], list[str | None]]:
    texts: list[str] = []
    ids: list[str | None] = []
    for ctx in raw or []:
        if isinstance(ctx, str):
            texts.append(ctx)
            ids.append(None)
        elif hasattr(ctx, "page_content"):  # langchain Document
            texts.append(ctx.page_content)
            ids.append(_doc_id(getattr(ctx, "metadata", {}) or {}))
        else:
            raise TargetError(f"unsupported context type {type(ctx).__name__}")
    return texts, ids


async def run_target(target: Any, ref: TargetRef, question: str, extra_callbacks: list | None = None) -> TargetResult:
    """Invoke the system once. Never raises: failures are returned in ``error``."""
    usage = UsageMetadataCallbackHandler()
    stats = _CallStats()
    callbacks = [usage, stats, *(extra_callbacks or [])]
    start = time.perf_counter()
    try:
        if hasattr(target, "ainvoke"):
            output = await target.ainvoke({ref.input_key: question}, config={"callbacks": callbacks})
        else:
            output = target.invoke({ref.input_key: question}, config={"callbacks": callbacks})
        latency = time.perf_counter() - start
        answer = output[ref.answer_key]
        if not isinstance(answer, str):
            answer = getattr(answer, "content", None) or str(answer)
        contexts, ids = _normalize_contexts(output.get(ref.contexts_key))
        error = None
    except Exception as exc:
        latency = time.perf_counter() - start
        answer, contexts, ids = "", [], []
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
    )
