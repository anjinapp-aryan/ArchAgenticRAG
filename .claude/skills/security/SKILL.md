---
name: security
description: "Use before any commit or share, when handling API keys or .env, adding providers, logging, writing run artifacts, or when a credential may have leaked into code, logs, results or chat in ArchAgenticRAG. Reuses the repo's pre-commit secret hook plus a value-based scan, and knows the hook's blind spots."
---

# security

## Purpose
Keep credentials out of git, logs, results and chat. For vulnerability review of code, use the built-in `/security-review`; this skill covers secrets and artifacts.

## When to use
Before every commit; when adding providers, logging or error handling; when a key might have been exposed.

## Inputs
The staged or working-tree changes; the `.env` variable names (never values).

## Workflow
1. **`.env` is ignored:** `git check-ignore .env` must print `.env`. `.env.example` holds placeholders only.
2. **Versioned hook:** `.githooks/pre-commit` runs `python .claude/hooks/guard.py scan-staged` (labelled key shapes, shape-less tokens by variable name, values from `.env`; it never prints a value). Run it early on staged changes with `sh .githooks/pre-commit`. It applies to every commit once `git config core.hooksPath .githooks` is set in the clone (`guard.py verify` says if it is not). It fails closed if Python is missing. The old local `.git/hooks/pre-commit` is only active while `core.hooksPath` is unset.
3. **Value-based scan.** The hook's patterns miss some providers, so also search for the actual secret values without printing them:
   ```
   grep -E '^[A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*=.{12,}' .env | while IFS='=' read -r n v; do
     git grep -qIF --untracked -- "$v" -- . ':!.env' && echo "VALUE OF $n IN REPO FILES"
     grep -rIlF -- "$v" eval/results >/dev/null 2>&1 && echo "VALUE OF $n IN eval/results"
   done
   ```
4. **Artifacts.** Run records, manifests and errors hold provider and model names and variable **names**, never values. The fallback transport redacts keys echoed back by providers; keep it that way.
5. **Chat.** Never ask the user to paste a key. If a key appears in chat, say it must be rotated.

## Required checks
- Known hook blind spots (verified 2026-11-03 with synthetic tokens): OpenRouter `sk-or-v1-…`, SambaNova (UUID form) and Cloudflare tokens are **not** matched by the hook. Step 3 covers them. Report this to the user rather than editing the hook.
- Logs and exception text added by the change cannot contain headers or keys.
- New error paths use the existing redaction.

## Output
`PASS` or the exact finding (file, variable name, never the value), plus the commands run.

## STOP
- Any credential found in a diff, log, result or chat: do not commit, do not repeat the value, tell the user to rotate it.
- A key is already in git history: stop; rewriting history needs the user's decision.
