---
name: implementation
description: "Use to implement an approved change in ArchAgenticRAG with the smallest possible diff: new experiment code, a setting, a provider preset, a fix. Applies after reuse-audit and architecture-review returned GO. Establishes the baseline state first, writes offline tests with fakes, keeps frozen artifacts untouched and finishes with a verification run."
---

# implementation

## Purpose
Turn an approved design into code without disturbing anything else, and prove it.

## When to use
After a GO (or for a trivial, clearly scoped fix). Not for audits or designs: those stop at GO / NO-GO.

## Inputs
The approved design or the fix description; the files it names; the experiment or baseline that must stay reproducible.

## Workflow
1. **Pre-conditions.** On a feature branch, not `main`. `python .claude/hooks/guard.py verify` is clean. Run the offline tests once so any later failure is attributable, and note the count.
2. **Read the rules** that load for the files you touch (`.claude/rules/`) and the owning doc in `docs/ai-development/`.
3. **Tests first, offline.** Fakes only (fake chat model, `DeterministicFakeEmbedding`, in-memory Qdrant, `httpx.MockTransport`). A config change gets a test pinning its diff against the control.
4. **Smallest diff.** Reuse installed components; add optional settings that default to current behaviour and stay out of fingerprints while unset; no moves, renames or drive-by cleanup.
5. **Test after each unit.** Offline suite; the pin tests run automatically after config and settings edits.
6. **Update what the change makes stale:** `eval/experiments.yaml`, README status, `THIRD_PARTY_NOTICES.md` for a new dependency or adapted pattern, the report or audit.
7. **Verify at the end:** offline, plus integration when the stack is touched (BLOCKED if Docker is down), `guard.py verify`, then `change-review`.
8. **Do not commit** unless asked (`git-checkpoint`).

## Required checks
- Baseline fingerprint and frozen register unchanged.
- No test weakened; new behaviour covered offline.
- Test statuses reported per category.

## Output
What changed (files), why it is the smallest option, tests added, verification results per category, and anything left open.

## STOP
- The work needs a design change or a rewrite: return to `architecture-review`.
- A pin or frozen-artifact check fails.
- The scope grows beyond the approved design.
