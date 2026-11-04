---
paths:
  - "tests/**"
---

# Tests

Loaded when you read or edit tests. Procedure: `testing` skill.

- Offline first: fake chat model, `DeterministicFakeEmbedding`, in-memory Qdrant, `httpx.MockTransport`. No network, no provider, no Langfuse, no Docker.
- Mark tests that need Qdrant `integration` and tests that call real providers `live`; the default run deselects both, so say NOT RUN for them.
- Never weaken, delete or loosen a test, or change expected behaviour, to get green. A failing pin (baseline fingerprint, config diff, frozen register) is a STOP.
- Integration tests treat baseline collections as read-only. Live tests are tiny and never assert on judge scores.
- Tests must not depend on the order or timing of non-deterministic retrieval.
- Report statuses per category: PASS, FAIL, SKIPPED, NOT RUN, BLOCKED.
