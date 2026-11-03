---
name: testing
description: "Use when running, adding or reporting tests in ArchAgenticRAG: offline, integration (Docker and Qdrant) and live (real providers). Reports PASS, FAIL, SKIPPED, NOT RUN and BLOCKED separately and never claims all tests pass when anything was skipped, deselected or blocked."
---

# testing

## Purpose
Know what was actually verified, and say so precisely. Status vocabulary: `docs/ai-development/AGENT_WORKFLOW.md`.

## When to use
After any code change, before any commit, and when asked about test status.

## Inputs
What changed; which prerequisites are available.

## Workflow
1. **Offline (default, about 15 s):** `.venv/Scripts/python -m pytest -q`. Needs no service. It deselects integration and live tests, so those are **NOT RUN**, not passed.
2. **Integration (about 1–2 min):** `.venv/Scripts/python -m pytest -m integration -q`. Needs Qdrant on `localhost:6333` (`docker compose up -d qdrant`, Docker Desktop running), the indexed collections, and FastEmbed/Docling models. Without them the tests skip or error: report BLOCKED with the reason.
3. **Live (about 4 min):** `.venv/Scripts/python -m pytest -m live -q`. Calls real providers with `.env` keys and consumes free-tier quota, including a little judge quota. Run only when the change touches providers, evaluation or the real stack, or when asked.
4. **New behaviour:** write offline tests first, with fakes (fake chat model, `DeterministicFakeEmbedding`, in-memory Qdrant, `httpx.MockTransport`); integration tests only for what needs real Qdrant, read-only on baseline collections; live tests tiny.
5. **Report per category** in the format in `AGENT_WORKFLOW.md`, with counts, deselected count and the command used.

## Required checks
- Never weaken, delete or loosen a test to get green; never change expected behaviour to make a test pass.
- Know the quirk: the live evaluator tests assert only that metrics exist, so they can PASS while the judge is out of quota and every metric value is missing. Report that as PASS with the caveat.
- Frozen pins (baseline fingerprint, config-diff tests) failing is a STOP.
- Do not run live tests while an official evaluation run is generating.

## Output
A status line per category (PASS, FAIL, SKIPPED, NOT RUN, BLOCKED) with reasons, and the failing test names with the shortest decisive error line.

## STOP
- A test regressed: find the cause; do not patch around it.
- Required tests cannot run (BLOCKED): report it, do not claim success.
- A pinned baseline or experiment test fails.
