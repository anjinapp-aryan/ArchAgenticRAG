@AGENTS.md

# Claude Code notes

The shared rules are in `AGENTS.md` (imported above). Keep this file for Claude Code specifics only. Anything other agents also need belongs in `AGENTS.md`. Claude Code loads both files into context at every session start, so keep the pair well under 200 lines.

## Skills

Project skills are in `.claude/skills/<name>/SKILL.md`. Their descriptions are always visible and the body loads when a skill is used, so use them instead of re-deriving a procedure. The task-to-skill routing table is in `AGENTS.md`. Skills can also be invoked as `/<name>`.

## Working agreements

- **Audit and design requests** produce a report and stop. Implement only after a GO and the user's go-ahead.
- **Built-in skills complement ours.** Use `/code-review` for generic bug-finding and `/security-review` for vulnerability review. The project skills `change-review` and `security` add the repo-specific checks. The project skill is deliberately not named `code-review`, so it cannot shadow the built-in.
- **Scratch work stays out of the repo.** Probes and ad-hoc analysis scripts go in the session scratchpad. Promote only what is reused.
- **Do not edit `.claude/settings*.json` or git hooks unasked.** Report gaps instead.
- **Shell.** The Bash tool is Git Bash and PowerShell is available. Prefer repo-relative paths, and set `PYTHONIOENCODING=utf-8` when printing non-ASCII from Python.
