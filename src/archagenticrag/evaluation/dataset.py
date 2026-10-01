"""Golden dataset schema, loading and traceability checks."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class Category(StrEnum):
    A_DIRECT_FACTUAL = "A_direct_factual"
    B_MULTI_SENTENCE = "B_multi_sentence"
    C_MULTI_DOCUMENT = "C_multi_document"
    D_AMBIGUOUS = "D_ambiguous"
    E_OUT_OF_CORPUS = "E_out_of_corpus"
    F_RETRIEVAL_CHALLENGE = "F_retrieval_challenge"
    G_MULTI_HOP = "G_multi_hop"


class ExpectedBehavior(StrEnum):
    ANSWER = "answer"  # corpus contains the answer
    ABSTAIN = "abstain"  # corpus does not contain the answer; system must not invent one
    CLARIFY = "clarify"  # question is ambiguous; system should ask or cover interpretations


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class GoldenItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    category: Category
    difficulty: str = Field(pattern=r"^(easy|medium|hard)$")
    expected_behavior: ExpectedBehavior
    question: str = Field(min_length=1)
    ground_truth: str = Field(min_length=1)
    source_documents: list[str]
    evidence: list[Evidence]
    notes: str | None = None

    @model_validator(mode="after")
    def _check_behavior_consistency(self) -> GoldenItem:
        if not self.ground_truth.strip():
            raise ValueError("ground_truth must not be blank")
        if self.expected_behavior is ExpectedBehavior.ANSWER:
            if not self.source_documents:
                raise ValueError("answerable items need at least one source document")
            if not self.evidence:
                raise ValueError("answerable items need at least one evidence quote")
        if self.expected_behavior is ExpectedBehavior.ABSTAIN and (
            self.source_documents or self.evidence
        ):
            raise ValueError("abstain items must not cite source documents or evidence")
        stray = {e.doc_id for e in self.evidence} - set(self.source_documents)
        if stray:
            raise ValueError(f"evidence cites documents not in source_documents: {sorted(stray)}")
        return self


class GoldenDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    version: str
    corpus_id: str
    created: str
    description: str
    items: list[GoldenItem]

    @model_validator(mode="after")
    def _check_unique_ids(self) -> GoldenDataset:
        seen: set[str] = set()
        dupes = {i.id for i in self.items if i.id in seen or seen.add(i.id)}
        if dupes:
            raise ValueError(f"duplicate item ids: {sorted(dupes)}")
        return self


class DatasetError(ValueError):
    """Raised when a dataset file cannot be loaded or fails validation."""


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset(path: str | Path) -> GoldenDataset:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetError(f"cannot read dataset {path}: {exc}") from exc

    # Validate rows individually first so one bad row reports its id, not just an index.
    problems: list[str] = []
    for index, row in enumerate(raw.get("items", [])):
        try:
            GoldenItem.model_validate(row)
        except ValidationError as exc:
            row_id = row.get("id", f"#{index}") if isinstance(row, dict) else f"#{index}"
            problems.append(f"item {row_id}: {exc.errors(include_url=False)}")
    if problems:
        raise DatasetError(f"{len(problems)} invalid row(s) in {path}:\n" + "\n".join(problems))

    try:
        return GoldenDataset.model_validate(raw)
    except ValidationError as exc:
        raise DatasetError(f"invalid dataset {path}: {exc}") from exc


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def verify_traceability(dataset: GoldenDataset, corpus_dir: str | Path) -> list[str]:
    """Check every evidence quote appears verbatim (modulo whitespace) in its source document.

    Also checks the corpus files still match the hashes recorded in MANIFEST.json.
    Returns a list of problems; an empty list means the dataset is fully traceable.
    """
    corpus_dir = Path(corpus_dir)
    manifest = json.loads((corpus_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    if manifest["corpus_id"] != dataset.corpus_id:
        return [f"dataset targets corpus {dataset.corpus_id!r}, manifest is {manifest['corpus_id']!r}"]

    problems: list[str] = []
    docs: dict[str, str] = {}
    for doc in manifest["documents"]:
        file = corpus_dir / doc["file"]
        if not file.exists():
            problems.append(f"{doc['doc_id']}: missing file {file.name}")
            continue
        if file_sha256(file) != doc["sha256"]:
            problems.append(f"{doc['doc_id']}: file hash differs from MANIFEST.json")
        docs[doc["doc_id"]] = _normalize(file.read_text(encoding="utf-8"))

    for item in dataset.items:
        for doc_id in item.source_documents:
            if doc_id not in docs:
                problems.append(f"{item.id}: unknown source document {doc_id}")
        for ev in item.evidence:
            text = docs.get(ev.doc_id)
            if text is not None and _normalize(ev.quote) not in text:
                problems.append(f"{item.id}: quote not found in {ev.doc_id}: {ev.quote[:60]!r}")
    return problems
