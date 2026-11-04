# Git hooks

A versioned `pre-commit` hook that blocks a commit staging a secret. It replaces the old hand-copied `.git/hooks/pre-commit`, which was local to one machine and recognised only seven of sixteen key formats.

## Install (once per clone)

```bash
git config core.hooksPath .githooks
```

This works the same on Windows (Git Bash or any shell with Git for Windows) and Linux. Check it with `git config --get core.hooksPath`, which should print `.githooks`. Once it is set, git ignores `.git/hooks/`, so the old local hook can stay or be deleted.

Needs: Git, a POSIX `sh` (bundled with Git for Windows), and Python 3 on `PATH` as `python3` or `python`. No packages are installed: the scanner is `.claude/hooks/guard.py scan-staged`, standard library only.

On Linux the file must be executable. If git prints "hook was ignored because it's not set as executable", run `git update-index --chmod=+x .githooks/pre-commit` and commit that.

## What it blocks

- an `.env` file (`.env.example` is allowed);
- added lines containing a key in the format of OpenAI, Anthropic, Gemini, Groq, OpenRouter, Cerebras, NVIDIA, xAI, Langfuse, GitHub or AWS, a private-key header, or a long high-entropy literal assigned to a key, token or password;
- a value assigned to a known provider variable such as `SAMBANOVA_API_KEY` or `CLOUDFLARE_API_TOKEN` (those two providers have no recognisable key shape, so the variable name is what identifies them);
- the exact value of any secret-looking variable in your local `.env`, whatever the provider.

`CLOUDFLARE_ACCOUNT_ID` is not treated as a secret. Placeholders (empty values, `your-key-here`, `<key>`, `${VAR}`) are allowed.

The message names the kind of secret and the file, never the text that matched.

## Limits

- It scans what is staged, not history. A key that was already committed must be rotated and removed from history by a person.
- A provider with no key shape and a variable name the scanner does not know can still pass; the value check against your `.env` covers keys you actually hold.
- `git commit --no-verify` skips it. Use that only for a false positive, never for a real key.
- Another clone has no protection until it runs the install command above.

## Fixing a false positive or adding a format

Edit `SECRET_RULES`, `SECRET_VARIABLES` or `PLACEHOLDER` in `.claude/hooks/guard.py`, and add a case to `tests/ai_development/test_secret_scanning.py`. Test keys must be assembled at runtime, never written out, or the scanner will block the test file itself.

## Uninstall

```bash
git config --unset core.hooksPath
```
