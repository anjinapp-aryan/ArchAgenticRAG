"""Validate a golden dataset: schema, and that every evidence quote exists in the corpus.

Usage: python eval/runners/validate_dataset.py eval/datasets/peps-v1/golden.json [--corpus data/corpus/peps]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from archagenticrag.evaluation.dataset import DatasetError, load_dataset, verify_traceability


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--corpus", type=Path, default=Path("data/corpus/peps"))
    args = parser.parse_args()

    try:
        dataset = load_dataset(args.dataset)
    except DatasetError as exc:
        print(exc, file=sys.stderr)
        return 1
    problems = verify_traceability(dataset, args.corpus)
    print(f"{dataset.dataset_id} v{dataset.version}: {len(dataset.items)} items")
    for field in ("category", "expected_behavior", "difficulty"):
        counts = Counter(str(getattr(i, field)) for i in dataset.items)
        print(f"  {field}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if problems:
        print(f"{len(problems)} traceability problem(s):", *problems, sep="\n  ", file=sys.stderr)
        return 1
    quotes = sum(len(i.evidence) for i in dataset.items)
    print(f"  traceability: OK ({quotes} evidence quotes verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
