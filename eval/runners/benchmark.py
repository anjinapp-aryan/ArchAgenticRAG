"""Compare experiment runs: retrieval ranking metrics, answer metrics, latency, cost.

Usage: python eval/runners/benchmark.py --all [--k 4 8] [--experiments 01 02] [--json out.json] [--markdown out.md]

--all lists every registered experiment, NOT RUN included. Reads eval/results, the registry
(eval/experiments.yaml), qrels (eval/datasets/<dataset>/qrels) and the price book
(eval/pricing.yaml). Needs no model, judge, Qdrant or Langfuse; never modifies a run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from archagenticrag.evaluation.benchmark import compare, discover_runs, load_registry, render_markdown, to_json
from archagenticrag.evaluation.pricing import load_price_book
from archagenticrag.evaluation.ranking import DEFAULT_CUTOFFS

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="include registered experiments that have no run (NOT RUN)")
    parser.add_argument("--k", type=int, nargs="+", default=[4, 8], help="Recall@K columns in the table (default: 4 8)")
    parser.add_argument("--results", type=Path, default=REPO_ROOT / "eval" / "results")
    parser.add_argument("--registry", type=Path, default=REPO_ROOT / "eval" / "experiments.yaml")
    parser.add_argument("--pricing", type=Path, default=REPO_ROOT / "eval" / "pricing.yaml")
    parser.add_argument("--experiments", nargs="+", help="compare only these experiment ids (e.g. 01 02)")
    parser.add_argument("--baseline", default="01", help="experiment id for paired wins/ties/losses (default: 01)")
    parser.add_argument("--json", type=Path, help="also write the full comparison (metadata contract, all cutoffs) here")
    parser.add_argument("--markdown", type=Path, help="also write the table here")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # the table uses "—" for missing values

    cutoffs = tuple(sorted(set(DEFAULT_CUTOFFS) | set(args.k)))
    result = compare(
        load_registry(args.registry),
        discover_runs(args.results),
        repo_root=REPO_ROOT,
        price_book=load_price_book(args.pricing),
        cutoffs=cutoffs,
        include_not_run=args.all,
        experiments=set(args.experiments) if args.experiments else None,
        baseline_id=args.baseline,
    )
    table = render_markdown(result, tuple(args.k))
    print(table)
    if args.markdown:
        args.markdown.write_text(table, encoding="utf-8", newline="\n")
    if args.json:
        args.json.write_text(to_json(result), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
