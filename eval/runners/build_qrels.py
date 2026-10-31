"""Derive chunk/document relevance labels (qrels) from the golden evidence quotes.

Usage: python eval/runners/build_qrels.py eval/configs/baseline-basic-rag.yaml

Re-chunks the corpus offline with the config's chunking settings (no Qdrant, no LLM) and
writes eval/datasets/<dataset>/qrels/<collection>.json. Exits 1 if any evidence quote
matches no chunk. See archagenticrag.evaluation.relevance for the matching rule.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from archagenticrag.evaluation.config import load_config
from archagenticrag.evaluation.dataset import file_sha256, load_dataset
from archagenticrag.evaluation.relevance import build_qrels, qrels_path
from archagenticrag.rag.ingestion import chunk_corpus
from archagenticrag.rag.settings import parse_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()

    config = load_config(args.config)
    settings = parse_settings(config.system.model_dump(mode="json"))
    dataset_path = REPO_ROOT / config.dataset.path
    corpus_dir = REPO_ROOT / config.dataset.corpus_dir
    chunks, manifest, _ = chunk_corpus(corpus_dir, settings.chunking)
    chunk_set = {
        "collection": settings.retrieval.qdrant.collection,
        "chunking": settings.chunking.model_dump(),
        "corpus_id": manifest["corpus_id"],
        "corpus_manifest_sha256": file_sha256(corpus_dir / "MANIFEST.json"),
    }
    qrels = build_qrels(load_dataset(dataset_path), chunks, chunk_set)
    qrels["dataset"]["sha256"] = file_sha256(dataset_path)

    out = qrels_path(dataset_path.parent / "qrels", settings.retrieval.qdrant.collection)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(qrels, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    queries = qrels["queries"]
    print(f"wrote {out}")
    print(f"items with qrels: {len(queries)}; relevant chunks: {sum(len(q['chunk_relevance']) for q in queries.values())}")
    for miss in qrels["unmatched_evidence"]:
        print(f"UNMATCHED {miss['id']} evidence[{miss['index']}] ({miss['doc_id']}): {miss['quote'][:80]!r}")
    return 1 if qrels["unmatched_evidence"] else 0


if __name__ == "__main__":
    sys.exit(main())
