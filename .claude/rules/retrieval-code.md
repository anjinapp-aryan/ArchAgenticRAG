---
paths:
  - "src/archagenticrag/graphs/**"
  - "src/archagenticrag/rag/**"
---

# Graphs and retrieval code

Loaded when you read or edit graph or retrieval code. Procedure: `architecture-review` skill. Rules: `docs/ai-development/ARCHITECTURE_RULES.md`.

- The graph is the unit of an experiment: `build_graph(system) -> graph`, input `question`, output `answer` and `documents` with `doc_id` and `chunk_id`.
- Query-side logic is a graph node. Re-ranking or fusion of a ranked list is retriever composition in `make_retriever`. A different index needs a new collection and new qrels.
- The baseline path must stay byte-for-byte equivalent in behaviour: same retriever call, same prompt, same defaults. New settings default to the baseline behaviour and stay out of the fingerprint while unset.
- Graphs know nothing about provider fallback, the judge, ranking metrics or Langfuse.
- Hybrid (RRF) ordering is not deterministic between calls; dense ordering is. Do not assert exact hybrid order in tests.
- Do not move or rename modules, functions or collections that manifests, configs or the registry reference.
