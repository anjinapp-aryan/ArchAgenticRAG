---
name: git-checkpoint
description: "Use only when the user asks to commit, checkpoint, save or push work in ArchAgenticRAG. Runs the safe sequence: status, diff review, secret scan, tests, baseline and experiment verification, commit, verify. Never commits or pushes on its own initiative and never pushes unless asked."
---

# git-checkpoint

## Purpose
Turn a verified working tree into a clean commit without leaking secrets or disturbing frozen artifacts.

## When to use
Only when the user asks to commit, checkpoint or push. Otherwise do not commit.

## Inputs
The user's request (commit only, or commit and push); the branch.

## Workflow
1. **State:** `git status -sb`, `git branch --show-current`, `git log -3 --oneline`. If on `main`, create a feature branch first; merging into `main` is a separate, explicit decision.
2. **Review the diff:** `git diff --stat` plus untracked files. Nothing unexpected: no `.env`, no `eval/results/`, no scratch files, no large binaries. Run `change-review` if the change is large.
3. **Stage explicitly:** add the intended paths; prefer `git add -A` only after step 2 shows nothing unwanted.
4. **Secret scan:** `sh .git/hooks/pre-commit` on the staged changes, then the value-based scan from the `security` skill.
5. **Tests:** offline always; integration and live as the change warrants (`testing`). Record the status per category; a BLOCKED or NOT RUN category goes into the commit report, never into a claim of success.
6. **Baseline and experiment verification:** the fingerprint and register checks in `docs/ai-development/EXPERIMENT_RULES.md`; `git diff --cached --name-only` shows no frozen artifact unless the task authorised it.
7. **Commit:** message `type: summary` (as in the history: `feat:`, `fix:`, `docs:`), a body that says what and why, test status honestly, and the attribution trailer your environment requires. Never `--no-verify`, never amend a pushed commit.
8. **Verify:** `git show --stat HEAD`, `git status -sb` clean.
9. **Push only if asked:** `git push -u origin <branch>`. Never force-push; never push to `main` unless told to.

## Required checks
- The hook ran and passed; the value scan found nothing.
- The commit contains exactly the intended files.

## Output
Commit hash and message, files in the commit, test status per category, scan results, and the push result if one was requested.

## STOP
- A secret is found: do not commit; the user must rotate it.
- A frozen artifact or fingerprint changed, or tests regressed.
- The hook blocks the commit: fix the cause; do not bypass it.
- The user did not ask for a commit.
