---
name: reuse-audit
description: "Use before building any new capability, dependency, model or algorithm in ArchAgenticRAG, and at the start of every new experiment. Checks whether the repo, installed packages or a mature licensed open-source project already solves it, and returns REUSE, ADAPT, COMPOSE, REFERENCE or BUILD with evidence."
---

# reuse-audit

## Purpose
Answer "does an existing solution already solve this?" before any code is written. Policy and past decisions: `docs/ai-development/REUSE_FIRST_POLICY.md`.

## When to use
Before implementing a capability, adding a dependency or model, or proposing an algorithm. Not needed for edits that add no capability.

## Inputs
The capability in one sentence; constraints (local only? no paid API? CPU or GPU?); the baseline it must stay comparable with.

## Workflow
1. **Repository.** Search `src/`, `eval/`, `tests/` for the capability. Read the "already here" and "previously decided" tables in `REUSE_FIRST_POLICY.md` and the precedent audits it lists. The question may already be decided.
2. **Installed packages.** `.venv/Scripts/python -c "import importlib.metadata as m; print(m.version('<pkg>'))"`, then read the real API under `.venv/Lib/site-packages/`. Do not trust memory: versions move (LangChain 1.x moved retrievers into `langchain-classic`).
3. **Existing abstractions** already in use (LangChain compressors, `RetrievalMode.HYBRID`, fastembed `TextCrossEncoder`, LangGraph `Send`). Prefer composing them below the graph.
4. **Open source.** Find 2–4 candidates (GitHub, PyPI, Hugging Face). For each record: version, licence (run `license-audit`), last release, dependency footprint (`uv pip install --python .venv/Scripts/python.exe --dry-run <pkg>` lists what would be added), CPU/GPU need, download size.
5. **Decide the smallest outcome that works:** REUSE, ADAPT (thin adapter), COMPOSE (combine existing parts), REFERENCE (learn, write own, credit in `THIRD_PARTY_NOTICES.md`), BUILD (say why each earlier outcome fails).

## Required checks
- Evidence comes from this session's commands or URLs, not memory.
- The licence of the package **and** of any model or data is known.
- New dependencies are listed with versions and pinned in `pyproject.toml`.
- No large code is copied from another repository.

## Output
A table `Capability | Candidate | Version | Licence | Footprint | Decision`; the chosen outcome; rejected options with one-line reasons. For experiments save it as `docs/EXPERIMENT-NN-<name>-AUDIT.md`; otherwise report inline.

## STOP
- The licence of the chosen option is unclear: reject it; stop if nothing else works.
- Only a paid or external API would work: ask the user.
- A reusable solution exists but the plan builds it anyway: switch to REUSE or ADAPT.
- The only path is a repo-wide rewrite: run `architecture-review`.
