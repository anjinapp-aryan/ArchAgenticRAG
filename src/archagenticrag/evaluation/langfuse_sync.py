"""Langfuse dataset sync and client construction.

Langfuse stores the golden dataset, runs the experiment (``run_experiment``) and keeps
per-item scores linked to traces. We do not maintain a separate results database.
"""

from __future__ import annotations

from typing import Any

from archagenticrag.evaluation.dataset import GoldenDataset, GoldenItem


def make_client(enabled: bool) -> Any:
    from langfuse import Langfuse

    if enabled:
        # Reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST from the environment.
        client = Langfuse()
        if not client.auth_check():
            raise RuntimeError("Langfuse auth_check failed: check LANGFUSE_* environment variables and server")
        return client
    # Offline mode: run_experiment still orchestrates the run locally, nothing is sent.
    return Langfuse(public_key="offline", secret_key="offline", host="http://127.0.0.1:9", tracing_enabled=False)


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
