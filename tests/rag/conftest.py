from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "data" / "corpus" / "peps"
BASELINE_CONFIG = REPO_ROOT / "eval" / "configs" / "baseline-basic-rag.yaml"


@pytest.fixture
def system() -> dict:
    """The baseline `system` section, as the evaluator passes it to build_graph."""
    return copy.deepcopy(yaml.safe_load(BASELINE_CONFIG.read_text(encoding="utf-8"))["system"])


@pytest.fixture
def fake_embeddings() -> DeterministicFakeEmbedding:
    return DeterministicFakeEmbedding(size=384)


@pytest.fixture
def memory_client():
    """qdrant-client's local in-memory mode: same API as the server, no network."""
    from qdrant_client import QdrantClient

    return QdrantClient(":memory:")


@pytest.fixture
def sample_chunks() -> list[Document]:
    texts = {
        "pep-0008": "PEP 8 - Style Guide for Python Code\nMaximum Line Length\nLimit all lines to a maximum of 79 characters.",
        "pep-0020": "PEP 20 - The Zen of Python\nBeautiful is better than ugly.",
        "pep-0572": "PEP 572 - Assignment Expressions\nThe walrus operator NAME := expr.",
    }
    return [
        Document(
            page_content=text,
            metadata={"doc_id": doc_id, "source": f"data/corpus/peps/{doc_id}.rst", "section": "S", "chunk_id": f"{doc_id}#000"},
        )
        for doc_id, text in texts.items()
    ]
