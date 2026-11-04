# AI Engineering Studio: research, reuse matrix and design record

Written 2026-11-03, before implementation. It records what was studied, what was reused, rejected and why, so the choices can be challenged later. Rules live in the other files of this folder; this file is the rationale.

## 1. Sources and how far they can be trusted

| Source | What was read | Caveat |
|---|---|---|
| `Donchitos/Claude-Code-Game-Studios`, commit `05ad7c8` (Release 1.2.0, 2026-10-19), MIT (LICENSE file) | cloned read-only into a scratch folder and read; nothing executed or copied | the repo is a template for game development; its numbers (49 agents, 74 skill folders, 18 hooks, 14 rules) were counted on disk |
| Open Source Radar page for that repo | star and growth statistics only | third-party analytics; its momentum labels are the site's own scores, and it states no licence, last commit or contributor data |
| Claude Code docs: memory, skills, sub-agents, hooks, hooks guide, settings (code.claude.com, read 2026-11-03) | conventions, frontmatter, events, exit codes | read through a reading agent; points it marked as summaries were treated as unverified |
| This repository | code, tests, git history, the previous session transcript (counts only) | |

Installed Claude Code is **2.1.181**. The docs describe features from later versions (`if` filters on hooks, `claude plugin validate`, `/skill-doctor`, native `AGENTS.md`). The design avoids every feature it could not confirm exists in 2.1.181.

## 2. What the reference does well, and what it costs

**Does well**
- Treats the repo as the source of truth, so a short request drives a whole procedure.
- Guards the moments that go wrong with deterministic hooks (commit, push, writes to guarded files), not with prose.
- Scopes rules to paths, so a rule is in front of the model when it edits the matching files.
- Has a static linter and a catalog for its own skills and agents, so a skill edit cannot silently drift.
- Keeps long reference material out of `CLAUDE.md` and reads it on demand.

**Costs and weaknesses**
- Weight: the median skill is 266 lines and the median agent 159 (maximum 614 and 420), against the docs' guidance of under 500 lines for a skill. Every agent restates a long collaboration protocol.
- A "May I write this?" step before every write. It is deliberate for a template used by beginners, and is the opposite of "faster".
- Bash and `jq` hooks. Its own code comments record a bug in which hooks "went silent on every Windows edit whenever jq was absent — jq is absent on a stock Windows Git Bash". The 826-line commit hook spends most of its length on JSON and path-escaping workarounds.
- No CI workflows exist in its `.github/`. Its skill linter prints observations, never verdicts, and the pass/fail judgement is left to an LLM-driven `/skill-test`, which is non-deterministic and spends tokens.
- A 130-entry deny list of glob variants of `rm -rf`, `git clean` and force-push flags, which is brittle by construction.

## 3. Reuse matrix

REUSE · ADAPT · COMPOSE · REFERENCE · REJECT. "Done" means the previous session already installed it.

| Mechanism | In Game Studios | Decision | In ArchAgenticRAG | Reason |
|---|---|---|---|---|
| Short constitution with `@` imports | `CLAUDE.md`, 83 lines | ADAPT, done | `AGENTS.md` + `CLAUDE.md` importing it | imports do not save context, so the pair stays tiny |
| On-demand reference docs | `.claude/docs/*` read when needed | ADAPT, done | `docs/ai-development/` | keeps always-loaded context small |
| Skills as procedures | 74 skills | ADAPT concept, REJECT scale | 13 skills of about 40 lines | most reference skills are game-specific; docs advise short skills |
| Specialist subagents | 49 agents in director, lead and specialist tiers | ADAPT concept, REJECT hierarchy and count | 6 read-only agents | docs: subagents cost context and usage. The wins are isolating bulky reading, independent review and tool limits |
| Coordination rules (delegation tiers, escalation, change propagation) | `coordination-rules.md` | REJECT | none | one human decides; tiers add overhead |
| Collaboration protocol, "May I write?" | every agent and `CLAUDE.md` | REJECT | ask-first list for risky categories only; hooks enforce a few | asking for every write is slow |
| Review modes and director gates | solo, lean and full panels | REJECT | one `reviewer` agent plus `change-review` | no need to scale review ceremony |
| Path-scoped rules | 14 `.claude/rules/*.md` with `paths:` | ADAPT | 6 short rules | loads the right rule when the matching file is read or edited |
| Commit and push validation hook | `validate-commit.sh`, `validate-push.sh` | ADAPT | `guard.py pre-bash` | the repo's real hazards: key leakage, frozen artifacts, destructive git and ingestion |
| Write guard for protected files | `validate-write.sh`, `write-guard.sh` | ADAPT | `guard.py pre-write` | frozen baseline, dataset, qrels, results |
| Read guard (refuses large whole-file reads) | `validate-read.sh` | REJECT | none | a context-size nicety; no incident here |
| Skill-change advisory | `validate-skill-change.sh` | ADAPT | `guard.py post-write` runs the lint tests | feedback at edit time |
| Session start, stop and pre-compact state recovery; `active.md` checkpoint | `session-*.sh`, `pre-compact.sh` | REFERENCE | auto-memory, git history, docs | Stop exit 2 forces Claude to continue; docs do not confirm a Stop warning channel |
| Notifications, agent logging, update check, status line | `notify.sh`, `log-agent*.sh`, `update-check.sh`, `statusline.sh` | REJECT | none | noise, not safety |
| Permission deny list | 130 entries in `settings.json` | REFERENCE | none; hooks cover force-push | brittle variants; hooks match structurally |
| Static skill lint | `skill-lint.sh`, `/skill-test static` | ADAPT | `tests/ai_development/` (pytest) | deterministic, runs in the existing test suite |
| LLM behavioural specs, catalog, rubric | `studio-tests/` | REJECT | none | non-deterministic and spends quota; static checks suffice |
| Spec templates | `studio-tests/templates/` | REJECT | existing experiment reports are the templates | avoids a second template set |
| Config store and stage machine | `project.yaml`, `gate-check`, `/set-stage` | REJECT | existing YAML configs and `eval/experiments.yaml` | already have one config system |
| Domain content | game design, engines, assets, localisation, sprints | REJECT | none | wrong domain |
| `SECURITY.md`, `CONTRIBUTING.md`, `UPGRADING.md`, `CHANGELOG.md` | present | REFERENCE | none | not needed for a lab repo |
| CI | none (empty `.github/`) | nothing to reuse | gap reported | adding CI is outside this task |

No code was copied. Credit for the ideas is recorded as a REFERENCE row in `THIRD_PARTY_NOTICES.md`.

## 4. Current Claude Code conventions that shaped the design

| Fact (docs, 2026-11-03) | Consequence |
|---|---|
| `CLAUDE.md` files are concatenated; under 200 lines per file; imports load with their parent | the pair `AGENTS.md` + `CLAUDE.md` stays small |
| `.claude/rules/*.md` exist; `paths:` globs scope a rule; loaded when Claude reads, writes or edits a matching file; `paths` is the only field read | six short, path-scoped rules; if `paths` were unsupported on 2.1.181 they load always, a small cost |
| Custom commands are merged into skills | no `.claude/commands/` |
| Skills: `name` and `description` only needed; description truncated near 1,500 characters; keep under 500 lines | skills stay near 40 lines; `name` + `description` only |
| Sub-agents: `.claude/agents/<name>.md`; `name` and `description` required; `tools`, `skills` optional; `description` drives delegation; they load `CLAUDE.md`; they can use project skills | agents carry a least-privilege `tools` list and preload the skills they need |
| Docs advise the main conversation for back-and-forth and quick changes, and warn that many agents consume context | agents are for bulky reading and independent review only; no implementer agent |
| Hooks: `hooks` key in `.claude/settings.json`; PreToolUse JSON `permissionDecision` (`allow`, `deny`, `ask`); exit 2 blocks; PostToolUse exit 2 shows stderr to Claude after the tool ran; default shell is bash, `CLAUDE_PROJECT_DIR` is set | hooks are one stdlib-only Python script; PostToolUse is feedback only |
| Stop exit 2 prevents stopping; no confirmed warning channel for Stop | no Stop hook |
| Trust rules for settings-file hooks are not documented | hooks fail open; activation is verified by the user |
| `/agents` wizard, `.claude/commands/`, `bypassPermissions` in project settings and old hook output formats are obsolete | not used |

## 5. Design

```text
AGENTS.md  CLAUDE.md                     constitution (updated: approval boundaries, agents)
.claude/
  agents/        6   researcher · reuse-auditor · architect · experimenter · evaluator · reviewer
  skills/       13   the 11 existing + implementation + failure-investigation
  rules/         6   path-scoped
  hooks/guard.py     one stdlib-only script: pre-write · pre-bash · post-write · verify
  settings.json      three hook entries, nothing else
docs/ai-development/
  (existing 5 docs updated) + STUDIO_REUSE_AUDIT.md (this file) + PRODUCTIVITY_VALIDATION.md + frozen-artifacts.json
tests/ai_development/   static consistency tests and hook behaviour tests (offline, in the normal suite)
```

**Agents: six, all without Write or Edit.** The main conversation implements, because it holds the context and the docs advise it for focused changes. A separate `implementer` was rejected for that reason, and `security-reviewer` was merged into `reviewer`.

**Skills: thirteen.** Added `implementation` (the minimal-change procedure that each prompt used to restate) and `failure-investigation` (a triage table of failure classes that actually occurred in this project: Docker down, quota, model cache wiped, console encoding, hybrid tie-order).

**Hooks: three entries, one script, no hook on events that only add noise.**

| Hook | Problem it prevents | Trigger | Action | False-positive risk |
|---|---|---|---|---|
| Frozen write guard | Editing the baseline config, golden set, corpus, qrels or run results by accident | PreToolUse `Write\|Edit` on a path listed in `frozen-artifacts.json` | `deny` for run results (irreversible), `ask` for files git can restore | very low: those paths are not edited in routine work. Measured in `PRODUCTIVITY_VALIDATION.md` |
| Command guard | Key leakage into a commit; commit of changed frozen artifacts; force-push; push to `main`; `reset --hard` / `clean -f` / discarding all changes; ingestion that recreates an existing collection; shell deletion or overwrite of frozen paths | PreToolUse `Bash\|PowerShell` | `deny` (leak, frozen change, force-push, run results, ingestion into an existing collection) or `ask` (the rest) | low: it parses commands and ignores quoted text, heredocs and line continuations; measured against every command of the previous session |

**Why irreversible cases are `deny`, not `ask`.** A live probe on 2026-11-03 showed a hook `deny` blocking a command in a bypass-permissions, non-interactive session, while an `ask` for a harmless `rm -rf` of a frozen path was approved automatically. So `ask` is advisory in that mode. Run results exist only on the local machine and an index cannot be restored, so those are denied, with an override only the user can set (`ARCHAGENTICRAG_ALLOW_DESTRUCTIVE=1` in the environment before starting Claude Code; a tool call cannot change the hook's environment).
| Drift check | A config or settings edit that breaks a fingerprint pin; an edit to the studio files that breaks the lint tests | PostToolUse `Write\|Edit` on matching paths | pin tests (about 2 s) after a config edit; after a studio edit only the checks that read that file (inline checks plus one lint test, about 1 s); the cross-file checks run at the commit gate. Failure exits 2 so Claude sees it | may still fire on a half-written skill file; it only reports and never blocks. Measured: `PRODUCTIVITY_VALIDATION.md` |

`guard.py verify` is also a plain command: it compares the frozen artifacts with `frozen-artifacts.json`. The skills call it instead of repeating hash commands.

**Skill tests.** Static checks as pytest tests in the existing suite: frontmatter, names, required sections, size budgets, routing coverage, links, quoted commands and flags, agent tool and skill references, rule globs, hook wiring, no duplicated rule lines. The LLM-driven behavioural specs were rejected.

## 6. Design review

| Check | Result |
|---|---|
| Does each new piece solve an observed problem? | yes. Hooks map to incidents or hazards recorded in this project; rules and agents map to repeated prompt text (measured in `PRODUCTIVITY_VALIDATION.md`) |
| Could a skill or doc do it instead? | the three hooks exist because prose cannot prevent a destructive command or a leaked key. Everything else is prose |
| Duplicate rules? | each rule keeps one owner; rules, agents and skills link to it. The lint test fails on identical long lines |
| Context cost | always-loaded stays under the 200-line guidance; skills, agents and rules load on demand |
| Windows | stdlib Python, no `jq`; paths handled with `pathlib`; ASCII-only output |
| Fails safe | any internal error in `guard.py` exits 0 (no block); only the explicit rules block |
| What was verified live | skills appeared in the skill list, the PostToolUse hook fired, a PreToolUse `deny` blocked a command, and the `tests.md` rule loaded. An `ask` was auto-approved in bypass mode, so irreversible cases became `deny` |
| What needed a restart | agents: a call to `researcher` failed with "not found" in the creating session and worked after a restart, with its skill and the project rules loaded |
| What was not verified | the trust prompt for hooks in a committed `settings.json` |
| What would make this over-engineered | adding agents or hooks without a measured recurring need. The maintenance rules in `AI_DEVELOPMENT_GUIDE.md` say so |
