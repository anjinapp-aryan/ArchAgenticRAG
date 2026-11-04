@AGENTS.md

# Claude Code notes

The shared rules are in `AGENTS.md` (imported above). Keep this file for Claude Code specifics only. Anything other agents also need belongs in `AGENTS.md`. Claude Code loads both files into context at every session start, so keep the pair well under 200 lines.

## Skills

Project skills are in `.claude/skills/<name>/SKILL.md`. Their descriptions are always visible and the body loads when a skill is used, so use them instead of re-deriving a procedure. The task-to-skill routing table is in `AGENTS.md`. Skills can also be invoked as `/<name>`.

## Agents

Project agents in `.claude/agents/` run in their own context and have no Write or Edit tools. Delegate bulky reading or an independent review; keep quick lookups, interactive work and every edit in the main conversation.

| Agent | Use for |
|---|---|
| `researcher` | broad read-only investigation, failure evidence, documentation |
| `reuse-auditor` | REUSE / ADAPT / COMPOSE / REFERENCE / BUILD decisions with licences |
| `architect` | placement, boundaries and GO / NO-GO designs |
| `experimenter` | experiment design and interpreting results |
| `evaluator` | running and comparing evaluations; never starts judging unasked |
| `reviewer` | independent review of a diff against the project rules |

## Hooks and rules

- `.claude/settings.json` wires three hooks to `.claude/hooks/guard.py` (stdlib Python, fails open): a write guard for frozen artifacts, a command guard (key leaks in commits, force-push, destructive git, ingestion into an existing collection, deleting run results) and a drift check (pin tests after config edits; file-local lint after studio edits; cross-file checks wait for the commit gate). The versioned git hook `.githooks/pre-commit` needs `git config core.hooksPath .githooks` once per clone. A `deny` is enforced in every permission mode; an `ask` may be auto-approved in bypass mode. If a hook blocks an irreversible action, report it; only the user can unlock it (`docs/ai-development/AGENT_WORKFLOW.md`). Design: `docs/ai-development/STUDIO_REUSE_AUDIT.md`.
- `.claude/rules/*.md` are path-scoped and load when a matching file is read or edited.
- `tests/ai_development/` keeps all of this consistent and runs with the normal offline tests.

## Working agreements

- **Audit and design requests** produce a report and stop. Implement only after a GO and the user's go-ahead.
- **Built-in skills complement ours.** Use `/code-review` for generic bug-finding and `/security-review` for vulnerability review. The project skills `change-review` and `security` add the repo-specific checks. The project skill is deliberately not named `code-review`, so it cannot shadow the built-in.
- **Scratch work stays out of the repo.** Probes and ad-hoc analysis scripts go in the session scratchpad. Promote only what is reused.
- **Do not edit `.claude/settings*.json` or git hooks unasked.** Report gaps instead.
- **Shell.** The Bash tool is Git Bash and PowerShell is available. Prefer repo-relative paths, and set `PYTHONIOENCODING=utf-8` when printing non-ASCII from Python.
