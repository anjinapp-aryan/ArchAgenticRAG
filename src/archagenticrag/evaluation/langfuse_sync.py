"""Langfuse dataset sync and client construction.

Langfuse stores the golden dataset, runs the experiment (``run_experiment``) and keeps
per-item scores linked to traces. We do not maintain a separate results database.
"""

from __future__ import annotations

from typing import Any

from archagenticrag.evaluation.dataset import GoldenDataset, GoldenItem


class LangfuseUnavailable(RuntimeError):
    pass


def make_client(enabled: bool) -> Any:
    from langfuse import Langfuse

    if enabled:
        # Reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST (or LANGFUSE_BASE_URL)
        # from the environment. An enabled run fails here, before any model call, rather than
        # running untraced.
        client = Langfuse()
        try:
            ok = client.auth_check()
        except Exception as exc:  # unreachable server, bad keys: the SDK raises its own types
            raise LangfuseUnavailable(f"Langfuse server not usable: {type(exc).__name__}: {exc}") from exc
        if not ok:
            raise LangfuseUnavailable("Langfuse auth_check failed: check LANGFUSE_* environment variables and server")
        return client
    # Offline mode: run_experiment still orchestrates the run locally, nothing is sent.
    return Langfuse(public_key="offline", secret_key="offline", host="http://127.0.0.1:9", tracing_enabled=False)


def langchain_callbacks(enabled: bool) -> list[Any]:
    """Langfuse's LangChain callback when tracing is enabled, else nothing (no import, no network).

    The handler uses the client ``make_client`` initialised and attaches graph, retriever and
    LLM spans to the current trace, i.e. the per-item trace ``run_experiment`` opens.
    """
    if not enabled:
        return []
    from langfuse.langchain import CallbackHandler

    return [CallbackHandler()]


def item_metadata(item: GoldenItem, dataset: GoldenDataset) -> dict[str, Any]:
    return {
        "id": item.id,
        "category": item.category.value,
        "difficulty": item.difficulty,
        "expected_behavior": item.expected_behavior.value,
        "source_documents": item.source_documents,
        "dataset_version": dataset.version,
    }


def sync_dataset(client: Any, dataset: GoldenDataset, dataset_name: str) -> int:
    """Create or update the Langfuse dataset. Item ids are stable, so re-running is idempotent."""
    client.create_dataset(
        name=dataset_name,
        description=dataset.description,
        metadata={"dataset_id": dataset.dataset_id, "version": dataset.version, "corpus_id": dataset.corpus_id},
    )
    for item in dataset.items:
        client.create_dataset_item(
            dataset_name=dataset_name,
            id=f"{dataset.dataset_id}-{item.id}",
            input={"question": item.question},
            expected_output=item.ground_truth,
            metadata=item_metadata(item, dataset) | {"evidence": [e.model_dump() for e in item.evidence]},
        )
    client.flush()
    return len(dataset.items)
