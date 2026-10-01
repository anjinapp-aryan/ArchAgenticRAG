"""One real golden question through the Phase 2 evaluator with the real Basic RAG graph.

Run with: pytest -m live   (needs the baseline Qdrant index, .env keys; costs a few API calls)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from archagenticrag.evaluation.persistence import read_run
from archagenticrag.evaluation.runner import run_evaluation

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.live


def test_one_golden_question_through_the_evaluator(tmp_path):
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    golden = json.loads((REPO_ROOT / "eval/datasets/peps-v1/golden.json").read_text(encoding="utf-8"))
    golden["items"] = [i for i in golden["items"] if i["id"] == "A01"]
    (tmp_path / "golden.json").write_text(json.dumps(golden), encoding="utf-8")

    config = yaml.safe_load((REPO_ROOT / "eval/configs/baseline-basic-rag.yaml").read_text(encoding="utf-8"))
    config["run_name"] = "live-smoke"
    config["dataset"] = {"path": str(tmp_path / "golden.json"), "corpus_dir": str(REPO_ROOT / "data/corpus/peps")}
    config_path = tmp_path / "live.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    run = read_run(run_evaluation(config_path, repo_root=REPO_ROOT, results_root=tmp_path / "results"))
    (item,) = run["items"]
    assert item["error"] is None
    assert item["answer"].strip()
    assert "pep-0008" in item["retrieval"]["retrieved_doc_ids"]
    assert item["metrics"], "Ragas produced no metrics"
    assert run["manifest"]["target_metadata"]["index"]["embedding_dimension"] == 384
