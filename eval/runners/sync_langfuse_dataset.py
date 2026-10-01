"""Upload the golden dataset to Langfuse (idempotent: stable item ids).

Needs LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_HOST.
Usage: python eval/runners/sync_langfuse_dataset.py eval/configs/baseline-basic-rag.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from archagenticrag.evaluation.config import load_config
from archagenticrag.evaluation.dataset import load_dataset
from archagenticrag.evaluation.langfuse_sync import make_client, sync_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()

    config = load_config(args.config)
    if not config.langfuse.dataset_name:
        print("config has no langfuse.dataset_name", file=sys.stderr)
        return 1
    dataset = load_dataset(REPO_ROOT / config.dataset.path)
    count = sync_dataset(make_client(enabled=True), dataset, config.langfuse.dataset_name)
    print(f"synced {count} items to Langfuse dataset {config.langfuse.dataset_name!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
