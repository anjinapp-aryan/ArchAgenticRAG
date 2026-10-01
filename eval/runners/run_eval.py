"""Run an evaluation config end to end.

Usage: python eval/runners/run_eval.py eval/configs/baseline-basic-rag.yaml [--skip-preflight]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from archagenticrag.evaluation.config import load_config
from archagenticrag.evaluation.providers import assert_models_available
from archagenticrag.evaluation.runner import run_evaluation

REPO_ROOT = Path(__file__).resolve().parents[2]


async def preflight(config_path: Path) -> None:
    config = load_config(config_path)
    wanted: dict[str, set[str]] = {}
    for ref in (config.system.generator, config.system.embedding, config.judge.llm, config.judge.embedding):
        if ref.provider != "local":
            wanted.setdefault(ref.provider, set()).add(ref.model)
    for provider, models in wanted.items():
        await assert_models_available(provider, sorted(models))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--skip-preflight", action="store_true", help="do not check provider model lists first")
    args = parser.parse_args()
    load_dotenv(REPO_ROOT / ".env")  # gitignored; never overrides variables already set

    if not args.skip_preflight:
        asyncio.run(preflight(args.config))
    run_dir = run_evaluation(args.config, repo_root=REPO_ROOT)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    print(f"results: {run_dir}")
    print(json.dumps({k: summary[k] for k in ("items", "system_errors", "metrics_overall", "failure_matrix")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
