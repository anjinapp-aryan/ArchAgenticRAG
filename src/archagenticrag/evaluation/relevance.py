"""Chunk- and document-level relevance labels (qrels) derived from the golden evidence quotes.

Every answerable golden item cites verbatim evidence quotes from the raw reStructuredText
corpus. Chunks hold the *rendered* text (docutils -> HTML -> Docling), so a raw quote is not a
substring of its chunk: inline markup (````code````, ``*emphasis*``, ``:pep:`484```) is
rendered, and Docling adds spaces around inline code and footnote links.

The mapping below is deterministic and uses no LLM:
  1. render the quote with docutils (the same reference renderer the ingestion uses) and
     drop docutils' own warning nodes;
  2. reduce quote and chunk to their lower-case alphanumeric token sequence, after removing
     Docling footnote links (``[[1]](#footnote-1)``);
  3. a chunk is relevant to an item if it belongs to the evidence's cited document and its
     token sequence contains the quote's token sequence.

Labels are binary (1 = the chunk contains a gold evidence quote). Quotes found in other
documents too are listed under ``also_found_in`` for review, but not labelled relevant: the
golden set cites one document per quote. Quotes that match no chunk (e.g. split across a
chunk boundary) are reported in ``unmatched_evidence``, never silently dropped.

Qrels depend on the chunking, so one file is written per Qdrant collection.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from archagenticrag.evaluation.dataset import GoldenDataset

QRELS_VERSION = 1
_DOCUTILS_SETTINGS = {"report_level": 5, "halt_level": 5}
_FOOTNOTE_LINK = re.compile(r"\[\[\d+\]\]\(#footnote-\d+\)")
_TOKEN = re.compile(r"[a-z0-9]+")


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_rst(text: str) -> str:
    """Plain text of a reStructuredText fragment, as docutils renders it."""
    from docutils import nodes
    from docutils.core import publish_doctree

    tree = publish_doctree(text, settings_overrides=_DOCUTILS_SETTINGS)
    for message in list(tree.findall(nodes.system_message)):
        message.parent.remove(message)
    return tree.astext()


def match_key(text: str) -> str:
    """Space-delimited token sequence used for containment checks."""
    return " " + " ".join(_TOKEN.findall(_FOOTNOTE_LINK.sub(" ", text).lower())) + " "


def build_qrels(dataset: GoldenDataset, chunks: list[Document], chunk_set: dict[str, Any]) -> dict[str, Any]:
    """Qrels for every golden item with evidence. ``chunk_set`` describes the index (collection, chunking)."""
    keyed = [(doc.metadata["chunk_id"], doc.metadata["doc_id"], match_key(doc.page_content)) for doc in chunks]
    catalog = {doc.metadata["chunk_id"]: {"doc_id": doc.metadata["doc_id"], "sha256": text_sha256(doc.page_content)} for doc in chunks}
    if len(catalog) != len(chunks):
        raise ValueError("chunk ids are not unique")

    queries: dict[str, Any] = {}
    unmatched: list[dict[str, Any]] = []
    for item in dataset.items:
        if not item.evidence:
            continue
        chunk_relevance: dict[str, int] = {}
        evidence = []
        for index, ev in enumerate(item.evidence):
            key = match_key(render_rst(ev.quote))
            hits = [cid for cid, doc_id, text in keyed if doc_id == ev.doc_id and key in text]
            elsewhere = [cid for cid, doc_id, text in keyed if doc_id != ev.doc_id and key in text]
            evidence.append({"index": index, "doc_id": ev.doc_id, "chunks": hits, "also_found_in": elsewhere})
            if not hits:
                unmatched.append({"id": item.id, "index": index, "doc_id": ev.doc_id, "quote": ev.quote})
            for cid in hits:
                chunk_relevance[cid] = 1
        queries[item.id] = {
            "category": item.category.value,
            "expected_behavior": item.expected_behavior.value,
            "chunk_relevance": chunk_relevance,
            "doc_relevance": {doc_id: 1 for doc_id in item.source_documents},
            "evidence": evidence,
        }
    return {
        "qrels_version": QRELS_VERSION,
        "method": "docutils-rendered evidence quote, alphanumeric token containment within the cited document",
        "dataset": {"dataset_id": dataset.dataset_id, "version": dataset.version},
        "chunk_set": {**chunk_set, "chunks": len(catalog), "catalog_sha256": text_sha256(json.dumps(catalog, sort_keys=True))},
        "chunk_catalog": catalog,
        "queries": queries,
        "unmatched_evidence": unmatched,
    }


def qrels_path(qrels_dir: Path, collection: str) -> Path:
    return qrels_dir / f"{collection}.json"


def load_qrels(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("qrels_version") != QRELS_VERSION:
        raise ValueError(f"{path}: unsupported qrels_version {data.get('qrels_version')!r}")
    return data
