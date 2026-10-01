"""Index the corpus into Qdrant using the `system` section of an evaluation config.

Usage: python -m archagenticrag.rag.ingest eval/configs/baseline-basic-rag.yaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from importlib import metadata
from pathlib import Path

from dotenv import load_dotenv

from archagenticrag.evaluation.config import load_config
from archagenticrag.rag.ingestion import chunk_corpus
from archagenticrag.rag.settings import parse_settings
from archagenticrag.rag.vector_store import index_documents, make_client, make_embeddings


def ingest(config_path: Path, repo_root: Path) -> dict:
    config = load_config(config_path)
    settings = parse_settings(config.system.model_dump(mode="json"))
    corpus_dir = repo_root / config.dataset.corpus_dir

    started = time.perf_counter()
    documents, manifest, report = chunk_corpus(corpus_dir, settings.chunking)
    chunk_seconds = time.perf_counter() - started

    index_metadata = {
        "corpus_id": manifest["corpus_id"],
        "corpus_source_commit": manifest.get("source_commit"),
        "corpus_manifest_sha256": hashlib.sha256((corpus_dir / "MANIFEST.json").read_bytes()).hexdigest(),
        "chunks_per_document": report.chunks_per_document,
        "versions": {p: metadata.version(p) for p in ("docling-slim", "docling-core", "docutils", "fastembed")},
    }
    started = time.perf_counter()
    stored = index_documents(
        make_client(settings.retrieval.qdrant), settings, make_embeddings(settings.embedding), documents, index_metadata
    )
    stored["timing_s"] = {"parse_and_chunk": round(chunk_seconds, 2), "embed_and_upsert": round(time.perf_counter() - started, 2)}
    return stored


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    load_dotenv(args.repo_root / ".env")
    result = ingest(args.config, args.repo_root.resolve())
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
