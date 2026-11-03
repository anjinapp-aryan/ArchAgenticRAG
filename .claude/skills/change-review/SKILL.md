---
name: change-review
description: "Use to review a finished change, diff, branch or PR in ArchAgenticRAG against the project's own rules: scope, architecture, tests, security, dependencies and licences, experiment integrity and documentation. Adds the repo-specific checks on top of the built-in /code-review, which finds generic bugs."
---

# change-review

## Purpose
Catch what a generic reviewer would not know: frozen artifacts, controlled-experiment integrity, honest test reporting, licences. Named `change-review` so it does not shadow the built-in `/code-review`; run that too for generic correctness bugs.

## When to use
After implementing, before `git-checkpoint`, and when asked to review a diff, branch or PR.

## Inputs
The diff (`git diff`, `git diff main...HEAD`, or a PR number) and the original task.

## Workflow
1. **Scope:** `git diff --stat`. Every file traces to the task; no drive-by moves, renames or reformatting.
2. **Frozen artifacts:** `git diff --name-only | grep -E '^(data/corpus|eval/datasets|eval/configs/(baseline|control|exp0|phase))'` should show only intended additions. Verify the register in `EXPERIMENT_RULES.md` (fingerprints, hashes). Results are gitignored, so check `eval/results` by hash or modification time.
3. **Architecture:** placement and dependency direction per `ARCHITECTURE_RULES.md`; `build_graph(system)` and manifest-referenced names unchanged; new optional config fields excluded from fingerprints while unset.
4. **Correctness:** edge cases, error paths, determinism, resource use. Also run the built-in `/code-review`.
5. **Tests:** new behaviour covered offline; no test weakened; statuses reported honestly (`testing`).
6. **Security:** run the `security` checks.
7. **Dependencies and licences:** `pyproject.toml` pins, `THIRD_PARTY_NOTICES.md` rows, `license-audit` evidence.
8. **Experiment integrity:** one variable; controlled variables identical; retrieval and answer claims separated; no tuning to the golden set.
9. **Documentation:** README status, registry, reports and ADRs match the evidence and the numbers in the run files.

## Required checks
Each finding cites `file:line` and a fix; no style nits unless they change meaning.

## Output
Findings ordered by severity (blocker, major, minor), then a verdict: APPROVE, APPROVE WITH CHANGES or BLOCK.

## STOP
- A frozen artifact or fingerprint changed unexpectedly: BLOCK.
- Tests regressed or required tests were not run.
- A credential or an unclear licence is in the diff.
