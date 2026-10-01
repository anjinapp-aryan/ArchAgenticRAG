"""Write and read evaluation run artifacts (plain JSON files under eval/results/<run_id>/)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def write_run(
    results_root: Path,
    run_id: str,
    *,
    manifest: dict[str, Any],
    config_path: Path,
    records: list[dict[str, Any]],
    summary: dict[str, Any],
) -> Path:
    run_dir = results_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)  # never overwrite an earlier run
    shutil.copyfile(config_path, run_dir / "config.yaml")
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    with (run_dir / "items.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return run_dir


def read_run(run_dir: Path) -> dict[str, Any]:
    items = [
        json.loads(line)
        for line in (run_dir / "items.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {
        "manifest": json.loads((run_dir / "manifest.json").read_text(encoding="utf-8")),
        "summary": json.loads((run_dir / "summary.json").read_text(encoding="utf-8")),
        "items": items,
    }
