from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = REPO_ROOT / "eval" / "datasets" / "peps-v1" / "golden.json"
CORPUS_DIR = REPO_ROOT / "data" / "corpus" / "peps"
BASELINE_CONFIG = REPO_ROOT / "eval" / "configs" / "baseline-basic-rag.yaml"

os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")


@pytest.fixture
def golden_raw() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def write_json(tmp_path: Path):
    def _write(data: dict, name: str = "golden.json") -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def mini_repo(tmp_path: Path, golden_raw: dict):
    """A throwaway repo layout: tiny corpus, small dataset, config. Returns a builder."""

    def _build(items: list[dict] | None = None, config_overrides: dict | None = None) -> tuple[Path, Path]:
        root = tmp_path / "repo"
        corpus = root / "data" / "corpus" / "mini"
        corpus.mkdir(parents=True)
        docs = {
            "doc-a": "Alpha facts. The answer to life is 42. Other alpha text.",
            "doc-b": "Beta facts. Beta uses tabs never. More beta text.",
        }
        manifest_docs = []
        for doc_id, text in docs.items():
            (corpus / f"{doc_id}.txt").write_text(text, encoding="utf-8")
            manifest_docs.append(
                {"doc_id": doc_id, "file": f"{doc_id}.txt", "sha256": hashlib.sha256(text.encode()).hexdigest()}
            )
        (corpus / "MANIFEST.json").write_text(
            json.dumps({"corpus_id": "mini-v1", "source_commit": "abc123", "documents": manifest_docs}),
            encoding="utf-8",
        )
        dataset = {
            "dataset_id": "mini",
            "version": "0.0.1",
            "corpus_id": "mini-v1",
            "created": "2026-10-01",
            "description": "test",
            "items": items
            if items is not None
            else [
                {
                    "id": "Q1",
                    "category": "A_direct_factual",
                    "difficulty": "easy",
                    "expected_behavior": "answer",
                    "question": "What is the answer to life?",
                    "ground_truth": "42.",
                    "source_documents": ["doc-a"],
                    "evidence": [{"doc_id": "doc-a", "quote": "The answer to life is 42."}],
                },
                {
                    "id": "Q2",
                    "category": "E_out_of_corpus",
                    "difficulty": "easy",
                    "expected_behavior": "abstain",
                    "question": "Who won the 2022 World Cup?",
                    "ground_truth": "Not in corpus.",
                    "source_documents": [],
                    "evidence": [],
                },
                {
                    "id": "Q3",
                    "category": "D_ambiguous",
                    "difficulty": "medium",
                    "expected_behavior": "clarify",
                    "question": "What about the facts?",
                    "ground_truth": "Ambiguous: alpha or beta facts.",
                    "source_documents": ["doc-a", "doc-b"],
                    "evidence": [{"doc_id": "doc-b", "quote": "Beta uses tabs never."}],
                },
            ],
        }
        ds_dir = root / "eval" / "datasets" / "mini"
        ds_dir.mkdir(parents=True)
        (ds_dir / "golden.json").write_text(json.dumps(dataset), encoding="utf-8")

        config = yaml.safe_load(BASELINE_CONFIG.read_text(encoding="utf-8"))
        config["run_name"] = "test-run"
        config["dataset"] = {"path": "eval/datasets/mini/golden.json", "corpus_dir": "data/corpus/mini"}
        config["target"]["factory"] = "nonexistent.module:build_graph"
        for key, value in (config_overrides or {}).items():
            config[key] = value
        config_path = root / "eval" / "configs" / "test.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        return root, config_path

    return _build


@pytest.fixture
def baseline_config_dict() -> dict:
    return copy.deepcopy(yaml.safe_load(BASELINE_CONFIG.read_text(encoding="utf-8")))
