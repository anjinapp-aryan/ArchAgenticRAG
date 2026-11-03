# AI development guide

The map to how AI agents develop this repository: what is where, which skill to use when, and why it is built this way. Written 2026-11-03.

## 1. Structure

```text
CLAUDE.md                  imports AGENTS.md; Claude Code specifics only
  └─ @AGENTS.md            the constitution: hard rules, STOP list, commands, routing (always loaded)
       ├─ .claude/skills/  11 procedures, loaded on demand (description always visible)
       └─ docs/ai-development/   rules and policy the skills point to (read when needed)
```

| Layer | Holds | Loaded | Edit when |
|---|---|---|---|
| `AGENTS.md` | rules every agent must follow; commands; routing | every session | a rule changes. Keep the pair `AGENTS.md` + `CLAUDE.md` well under 200 lines |
| `CLAUDE.md` | Claude Code only: skill usage, built-in complements | every session | a Claude-specific habit changes |
| Skills | **how to do** a task: workflow, checks, output, STOP | on demand | a procedure changes |
| `docs/ai-development/` | **what is true**: architecture rules, experiment rules, reuse policy and decisions, workflow and gates | on demand | a rule or fact changes |

Rules are stated once, in the document that owns them. Skills link to rules instead of copying them.

| Owner | Rule |
|---|---|
| `ARCHITECTURE_RULES.md` | layers, contract, where a change goes, config and fingerprint rules |
| `EXPERIMENT_RULES.md` | experiment elements, tiers, comparison method, decision vocabulary, frozen-artifact register |
| `REUSE_FIRST_POLICY.md` | outcomes, what is already here, what was already rejected |
| `AGENT_WORKFLOW.md` | lifecycle, quality gates, status vocabulary, full STOP list |

## 2. When to use which skill

| Task | Chain |
|---|---|
| New capability | `reuse-audit` → `license-audit` → `architecture-review` → implement → `testing` → `change-review` |
| New experiment | `experiment-design` → `reuse-audit` → `architecture-review` → implement → `evaluation` (Tier 1) → `testing` → decision; Tier 2 only when approved |
| New provider or fallback pool | `provider-development` → `reuse-audit` → `license-audit` → `security` → `testing` |
| Run, resume or compare evaluations | `evaluation`; `data-retention` for the artifacts |
| Architecture question | `architecture-review` |
| Dependency or model question | `reuse-audit` + `license-audit` |
| Cleanup or deletion | `data-retention` |
| Before a commit | `change-review` → `testing` → `security` → `git-checkpoint` |

## 3. Shorter prompts

| Instead of repeating the rules, say | The repository supplies |
|---|---|
| "Implement Experiment 04." | hypothesis and control rules, reuse audit, GO/NO-GO, config-diff test, registry entry, Tier 1 evaluation, report template, decision vocabulary, stop point |
| "Add a provider." | OpenAI-compatible preset, endpoint verification, environment variables, fallback classification, mocked tests, fingerprint protection, redaction |
| "Review this architecture." | `architecture-review` against `ARCHITECTURE_RULES.md`: placement, dependency direction, contracts, minimal change |
| "Run the evaluation." | prerequisites, `--defer-judge`, retry with `--no-judge`, paired comparison, judge only when asked |
| "Commit this." | status, diff review, secret scans, tests with honest statuses, baseline verification, commit, verification; push only if asked |

## 4. Design decisions (compared with the proposed layout)

| Proposal | Decision | Reason |
|---|---|---|
| `CLAUDE.md` → `AGENTS.md` as documents | `CLAUDE.md` starts with `@AGENTS.md`; `AGENTS.md` is the single source of rules | The docs recommend an import for repos that keep both, and say a symlink is risky on Windows. The installed Claude Code (2.1.181) is older than the version the docs say reads `AGENTS.md` natively, so the import is the dependable route |
| Separate workflow and quality-gates files | merged into `AGENT_WORKFLOW.md` | the gates are the lifecycle's checkpoints; two files would restate each other |
| Skill `code-review` | named `change-review` | a built-in `/code-review` exists and the docs do not say which wins on a name clash. `change-review` adds repo-specific checks and defers generic bug-finding to the built-in |
| Policy docs and skills of the same name | docs hold rules and facts, skills hold procedures | avoids two copies of each rule |
| 11 skills | kept all 11 | each has a distinct trigger and output; a shorter list would merge unrelated procedures. Frontmatter is only `name` and `description` |
| Quality-gate model 0–8 | kept, with an "applies" column | the repository's own phases map onto it without change |
| New scripts or a docs validator | none | existing tools suffice (pytest, `benchmark.py`, `resume_eval.py`, the pre-commit hook, `THIRD_PARTY_NOTICES.md`, ADRs). No linter or CI exists; none was added |

## 5. Existing mechanisms reused

pytest markers (`integration`, `live`) · config fingerprints and config-diff tests · run manifests with dataset and corpus hashes · `write_run` refusing to overwrite · `resume_eval.py` · `benchmark.py` and `eval/experiments.yaml` · `build_qrels.py` · the local pre-commit secret hook · `THIRD_PARTY_NOTICES.md` · `docs/adr/` · precedent audit and experiment reports · `.env.example` · built-in `/code-review` and `/security-review`.

## 6. Known gaps (reported, not fixed here)

- **The pre-commit hook is not versioned** (`.git/hooks`), so a fresh clone is unprotected, and its patterns miss OpenRouter, SambaNova and Cloudflare key shapes. The `security` skill compensates with a value-based scan. A versioned hook with wider patterns needs the owner's decision.
- **`eval/results/` is gitignored.** Run data exists only on the local machine; reports quote the numbers. See `data-retention`.
- **No linter, formatter or CI.** Quality gates rely on tests and review.
- **Hybrid retrieval is non-deterministic** (RRF ties), which `EXPERIMENT_RULES.md` accounts for. The Experiment 02 report predates that finding.

## 7. Conventions this relies on, and what is uncertain

Read from the official Claude Code documentation (memory and skills pages) on 2026-11-03; parts were summarised by a reading agent.

- `CLAUDE.md` and imports: files are concatenated, not overridden; `@path` imports resolve relative to the importing file, up to four hops deep, and are loaded with it, so imports do not save context. Guidance is under 200 lines per file.
- Skills: `.claude/skills/<name>/SKILL.md` with `name` and `description`; the description is truncated near 1,500 characters in the listing; keep `SKILL.md` under 500 lines; commit the folder.
- **Not stated in the docs:** which wins when a project skill and a built-in share a name; a maximum `SKILL.md` size; whether a skill added mid-session is picked up. After adding or renaming skills, check the next session lists them.
- Native `AGENTS.md` loading and its version are taken from the docs and not verified on this machine.

## 8. Maintaining the system

- New rule: put it in `AGENTS.md` only if every task needs it; otherwise in the owning doc. Never in two places.
- New skill: only for a repeatable procedure with its own trigger, inputs, output and STOP. Reuse before adding. Keep it short and link to rules.
- Dated facts (versions, hashes, hook coverage) carry a "verified" date; re-verify before relying on them.
- If a frozen artifact is legitimately changed, update the register in `EXPERIMENT_RULES.md` in the same change.
- Check links and commands still exist whenever files are renamed.
