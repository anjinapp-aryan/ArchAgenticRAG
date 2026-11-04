# AI development guide

The map to how AI agents develop this repository: what is where, which skill or agent to use when, and why it is built this way. Written 2026-11-03, updated the same day after the second round (agents, rules, hooks, tests).

## 1. Structure

```text
CLAUDE.md                          imports AGENTS.md; Claude Code specifics only
  └─ @AGENTS.md                    the constitution: hard rules, ask-first list, STOP list, commands, routing (always loaded)
       ├─ .claude/skills/   13     procedures, loaded on demand (description always visible)
       ├─ .claude/agents/    6     read-only specialists that run in their own context
       ├─ .claude/rules/     6     path-scoped reminders, loaded when a matching file is read or edited
       ├─ .claude/hooks/guard.py   three hooks wired in .claude/settings.json; also `guard.py verify`
       ├─ docs/ai-development/     rules and facts the skills point to, the frozen-artifact register, the research record
       └─ tests/ai_development/    keeps all of the above consistent; runs with the normal offline tests
```

| Layer | Holds | Loaded | Edit when |
|---|---|---|---|
| `AGENTS.md` | rules every agent must follow; commands; routing | every session | a rule changes. Keep the pair `AGENTS.md` + `CLAUDE.md` well under 200 lines |
| `CLAUDE.md` | Claude Code only: agents, hooks, rules, built-in complements | every session | a Claude-specific habit changes |
| Skills | **how to do** a task: workflow, checks, output, STOP | on demand | a procedure changes |
| Agents | who does bulky reading or independent review, with least-privilege tools | when delegated | a role's tools or skills change |
| Rules | the few things that bite for one area of the code | when a matching file is touched | an area gains a recurring mistake |
| Hooks | what must be prevented by code, not by prose | on tool calls | a new irreversible hazard appears |
| `docs/ai-development/` | **what is true** | on demand | a rule or fact changes |

Rules are stated once, in the document that owns them. Everything else links.

| Owner | Rule |
|---|---|
| `ARCHITECTURE_RULES.md` | layers, contract, where a change goes, config and fingerprint rules |
| `EXPERIMENT_RULES.md` | experiment elements, tiers, comparison method, decision vocabulary |
| `frozen-artifacts.json` | hashes and fingerprints of everything frozen (checked by `guard.py verify`) |
| `REUSE_FIRST_POLICY.md` | outcomes, what is already here, what was already rejected |
| `AGENT_WORKFLOW.md` | lifecycle, quality gates, approval boundaries, status vocabulary, full STOP list |
| `STUDIO_REUSE_AUDIT.md` | the research behind this design: reference project, conventions, reuse matrix |
| `PRODUCTIVITY_VALIDATION.md` | what was measured about its value, and what was not |

## 2. When to use which skill or agent

Agents are for bulky reading or an independent view; a quick lookup or any edit stays in the main conversation.

| Task | Chain |
|---|---|
| New capability | `reuse-audit` (or `reuse-auditor`) → `license-audit` → `architecture-review` (or `architect`) → `implementation` → `testing` → `change-review` (or `reviewer`) |
| New experiment, or "improve retrieval" | `experiment-design` (or `experimenter`) → `reuse-audit` → `architecture-review` → `implementation` → `evaluation` Tier 1 (or `evaluator`) → `testing` → decision; Tier 2 only when approved |
| New provider or fallback pool | `provider-development` → `reuse-audit` → `license-audit` → `security` → `testing` |
| Run, resume or compare evaluations | `evaluation` (or `evaluator`); `data-retention` for the artifacts |
| Investigate a failure | `failure-investigation` (or `researcher`) |
| Architecture question | `architecture-review` (or `architect`) |
| Dependency or model question | `reuse-audit` + `license-audit` (or `reuse-auditor`) |
| Cleanup or deletion | `data-retention` |
| Before a commit | `change-review` → `testing` → `security` → `git-checkpoint` |

## 3. Shorter prompts, honestly

| Instead of repeating the rules, say | The repository supplies |
|---|---|
| "Implement Experiment 04." | hypothesis and control rules, reuse audit, GO/NO-GO, config-diff test, registry entry, Tier 1 evaluation, report template, decision vocabulary, stop point |
| "Add a provider." | OpenAI-compatible preset, endpoint verification, environment variables, fallback classification, mocked tests, fingerprint protection, redaction |
| "Review this architecture." | `architecture-review` against `ARCHITECTURE_RULES.md`: placement, dependency direction, contracts, minimal change |
| "Run the evaluation." | prerequisites, `--defer-judge`, retry with `--no-judge`, paired comparison, judge only when asked |
| "Investigate this failure." | the triage table of failure classes that occurred here, then reproduce, root cause, minimal fix |
| "Commit this." | status, diff review, secret scans, tests with honest statuses, frozen-artifact check, commit, verification; push only if asked |

The measurement is in `PRODUCTIVITY_VALIDATION.md`: of 16 rule themes the user restated, all are now supplied, 3 are enforced by code and 5 more partly. It does **not** show a shorter prompt yet: the standing context is larger than one median prompt, and rule-restating lines are at most 7% of a prompt.

## 4. Design decisions

| Decision | Reason |
|---|---|
| `CLAUDE.md` imports `AGENTS.md`; `AGENTS.md` is the single source of rules | the docs recommend the import and warn against symlinks on Windows; installed Claude Code (2.1.181) predates native `AGENTS.md` loading |
| One workflow file with the quality gates | gates and lifecycle describe the same sequence |
| Skill `change-review`, not `code-review` | a built-in `/code-review` exists; the docs do not say which wins on a clash |
| Docs hold rules, skills hold procedures | one owner per rule |
| Six agents, none with Write or Edit; no `implementer`, no `security-reviewer` | docs warn that many agents cost context; the main conversation holds the context to implement; review needs only reading |
| Hooks in stdlib Python, three entries, no Stop or SessionStart hook | the reference project's bash and `jq` hooks failed silently on Windows; Stop exit 2 forces continuation; the rest was noise |
| Irreversible actions are `deny`, with a human-only override | an `ask` is auto-approved in bypass-permissions mode (observed) |
| Static tests, no LLM behavioural specs | deterministic, free, and run with the normal suite |
| No new scripts for validation or retention | existing tools suffice; no linter or CI exists and none was added |

## 5. Existing mechanisms reused

pytest markers (`integration`, `live`) · config fingerprints and config-diff tests · run manifests with dataset and corpus hashes · `write_run` refusing to overwrite · `resume_eval.py` · `benchmark.py` and `eval/experiments.yaml` · `build_qrels.py` · the local pre-commit secret hook · `THIRD_PARTY_NOTICES.md` · `docs/adr/` · precedent audits and experiment reports · `.env.example` · built-in `/code-review` and `/security-review`.

## 6. Known gaps (reported, not fixed here)

- **The git pre-commit hook is not versioned** (`.git/hooks`), so a fresh clone is unprotected, and its patterns miss OpenRouter, SambaNova and Cloudflare key shapes. `guard.py` adds a value-based scan and wider shapes only for commits Claude itself runs. A versioned git hook with wider patterns needs the owner's decision.
- **An `ask` can be auto-approved.** In a bypass-permissions, non-interactive session an `ask` decision did not stop a command (live probe). `deny` is enforced in every mode. Frozen files that git can restore are therefore only advisory in that mode.
- **Project agents are discovered only at session start.** A call to `researcher` failed with "not found" in the session that created the files, and worked after a restart (the agent saw its preloaded `failure-investigation` skill and the `AGENTS.md` rules). Adding or renaming an agent needs a new session. `claude plugin validate .claude/agents` needs a newer CLI than 2.1.181.
- **`eval/results/` is gitignored.** Run data exists only on the local machine; reports quote the numbers. The hook denies agent changes to it, but there is no backup.
- **No linter, formatter or CI.** Quality gates rely on tests and review.
- **Hybrid retrieval is non-deterministic** (RRF ties), which `EXPERIMENT_RULES.md` accounts for. The Experiment 02 report predates that finding.

## 7. Conventions this relies on, and what was verified

Read from the official Claude Code docs on 2026-11-03; parts were summarised by a reading agent.

- `CLAUDE.md`: files are concatenated; imports load with their parent and do not save context; under 200 lines per file.
- Skills: `.claude/skills/<name>/SKILL.md`, `name` and `description`; description truncated near 1,500 characters; keep under 500 lines. Custom commands are merged into skills.
- Agents: `.claude/agents/<name>.md`, `name` and `description` required; `tools` and `skills` optional; the description drives delegation.
- Rules: `.claude/rules/*.md`, `paths:` globs, loaded when a matching file is read, written or edited.
- Hooks: `hooks` in `.claude/settings.json`; exit 2 blocks (PreToolUse) or shows stderr to Claude (PostToolUse); JSON `permissionDecision` of `allow`, `deny` or `ask`; default shell is bash.

**Verified live in this installation:** the 13 skills appear in the skill list; the PostToolUse hook fires and its stderr reaches the agent; a PreToolUse `deny` blocks a command; an `ask` did not; the path-scoped `tests.md` rule was injected into context right after a file under `tests/` was written; after a restart the six agents are listed and `researcher` loaded with its preloaded skill.
**Not verified:** the trust prompt for hooks in a committed `settings.json`; the other five rules loading (only `tests.md` was observed); whether delegating to an agent beats working in the main conversation.
**Not stated in the docs:** which wins when a project skill and a built-in share a name; a maximum `SKILL.md` size.

## 8. Maintaining the system

- New rule: put it in `AGENTS.md` only if every task needs it; otherwise in the owning doc. Never in two places.
- New skill, agent, rule or hook: only for a repeatable need with a measured or observed cost. Reuse before adding. An agent gets no Write or Edit; a hook needs a named hazard and a test.
- `tests/ai_development` is the guard against drift. If it fails after you edit this layer, fix the cause: a broken link, an unrouted skill and a changed frozen artifact are real findings.
- If a frozen artifact is legitimately changed, update `frozen-artifacts.json` in the same change. A new experiment's config joins the register only when its run is final.
- Dated facts (versions, hashes, hook coverage) carry a "verified" date; re-verify before relying on them.
