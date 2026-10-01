# peps-golden v1.0.0

This is a set of 42 evaluation questions over the `peps-v1` corpus in `data/corpus/peps/`.

## Provenance and license

**Corpus.** 13 PEP source files copied unmodified from https://github.com/python/peps at commit `50803e5f0aa404f34093c16d13a9bd7d21d904d1` (retrieved 2026-10-01).

**Corpus license.** Each file's Copyright section says it is placed in the public domain. Newer PEPs say: *"in the public domain or under the CC0-1.0-Universal license, whichever is more permissive"*. This was checked per file and is recorded in `MANIFEST.json`.

**Questions and answers.** They were written for this project from the corpus text.

## Item schema

```json
{
  "id": "C01",
  "category": "C_multi_document",
  "difficulty": "easy | medium | hard",
  "expected_behavior": "answer | abstain | clarify",
  "question": "...",
  "ground_truth": "...",
  "source_documents": ["pep-0484", "pep-0604"],
  "evidence": [{"doc_id": "pep-0484", "quote": "<verbatim text from the corpus>"}],
  "notes": "optional"
}
```

## Rules (enforced by `load_dataset` and the tests)

- `answer` items must cite at least one source document and one evidence quote.
- `abstain` items cite nothing.
- Evidence may only cite documents listed in `source_documents`.
- Every quote must appear verbatim in its document (whitespace-normalized), and every corpus file must match its manifest hash.

## Changing the dataset

- Bump `version` (semver) whenever an item changes.
- Run `python eval/runners/validate_dataset.py eval/datasets/peps-v1/golden.json`.
- A different version means a different baseline. Never compare runs across versions.
