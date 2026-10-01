"""Run manifest: everything needed to reproduce an evaluation run."""

from __future__ import annotations

import json
import platform
import subprocess
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from archagenticrag.evaluation.config import EvalConfig
from archagenticrag.evaluation.dataset import GoldenDataset, file_sha256

TRACKED_PACKAGES = (
    "ragas",
    "langfuse",
    "openai",
    "langchain-core",
    "langchain-community",
    "langgraph",
    "langchain-qdrant",
    "qdrant-client",
    "docling",
)


def git_state(repo: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()

    try:
        return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain"))}
    except (OSError, subprocess.CalledProcessError) as exc:
        # Recorded rather than faked: a run outside git is not fully reproducible.
        return {"commit": None, "dirty": None, "error": f"git unavailable: {exc}".strip()[:200]}


def package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in TRACKED_PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def build_manifest(
    *,
    run_id: str,
    config: EvalConfig,
    config_path: Path,
    dataset: GoldenDataset,
    repo_root: Path,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    dataset_path = repo_root / config.dataset.path
    corpus_manifest = repo_root / config.dataset.corpus_dir / "MANIFEST.json"
    corpus = json.loads(corpus_manifest.read_text(encoding="utf-8"))
    return {
        "run_id": run_id,
        "run_name": config.run_name,
        "started_at": (started_at or datetime.now(UTC)).isoformat(),
        "git": git_state(repo_root),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": package_versions(),
        "config_path": str(config_path),
        "config_fingerprint": config.fingerprint(),
        "config": config.model_dump(mode="json"),
        "dataset": {
            "dataset_id": dataset.dataset_id,
            "version": dataset.version,
            "items": len(dataset.items),
            "sha256": file_sha256(dataset_path),
        },
        "corpus": {
            "corpus_id": corpus["corpus_id"],
            "source_commit": corpus.get("source_commit"),
            "manifest_sha256": file_sha256(corpus_manifest),
        },
    }
