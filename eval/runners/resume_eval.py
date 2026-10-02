"""Finish a run that stopped part-way (for example on a free-tier daily quota).

Usage: python eval/runners/resume_eval.py eval/results/<run_id>

Keeps every recorded answer and metric value. Re-runs only failed system calls and re-scores
only metrics without a value. Stops early on a daily-quota error; run it again the next day.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from archagenticrag.evaluation.resume import resume

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    load_dotenv(REPO_ROOT / ".env")  # gitignored; never overrides variables already set

    session = resume(args.run_dir, repo_root=REPO_ROOT)
    summary = json.loads((args.run_dir / "summary.json").read_text(encoding="utf-8"))
    print(json.dumps({k: session[k] for k in ("pending_items", "rerun_items", "stopped_on_daily_quota", "still_pending_items")}, indent=2))
    print(json.dumps({k: summary[k] for k in ("system_errors", "metric_value_missing", "failure_matrix")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
