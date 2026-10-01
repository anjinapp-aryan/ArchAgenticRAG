# Third-party notices

## Evaluation corpus

`data/corpus/peps/*.rst` are unmodified copies of Python Enhancement Proposals from
https://github.com/python/peps (commit `50803e5f0aa404f34093c16d13a9bd7d21d904d1`).
Each document states that it is placed in the public domain, or in the public domain or
under the CC0-1.0-Universal license, whichever is more permissive. Per-file details are in
`data/corpus/peps/MANIFEST.json`.

## Libraries (used as dependencies, not copied)

| Package | License | Use |
|---|---|---|
| ragas 0.4.3 | Apache-2.0 | Evaluation metrics |
| langfuse 4.16.0 (Python SDK) | MIT | Experiment runner, datasets |
| langchain-core / langchain-community | MIT | Callbacks, documents, Ragas dependency |
| openai | Apache-2.0 | OpenAI-compatible provider client |
| pydantic, PyYAML | MIT | Config and schema validation |

No source code has been copied from third-party repositories into this project.
