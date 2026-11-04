# Productivity validation of the AI engineering studio

Measured 2026-11-03. This file separates what was **measured**, what is **arithmetic from measurements**, and what is **not yet measurable**. No speed-up figure is claimed, because none has been measured.

Method: one script (kept out of the repository) read the previous session's transcript for this project, replayed its real commands and edits through the new hooks, counted sizes, and timed the hooks. Prompt text was never printed or copied; only counts and theme frequencies are recorded here.

## 1. Before: what had to be written (measured)

| Measure | Value |
|---|---|
| Pasted task prompts in the transcript | 15 |
| Words per task prompt | min 508 · median 1,555 · max 2,565 · total 25,673 |
| Other user messages | 32, median 6 words |
| Standing-rule themes restated per task prompt (of 16 tracked) | median 9 · min 3 · max 15 |
| Themes restated in at least 3 of the 15 prompts | 15 of 16 |
| Non-empty prompt lines that mention any standing-rule theme | 394 of 5,655 (7%), an upper bound: such a line can still carry task content |

Themes by number of the 15 prompts that restate them: reuse-first 14 · licence check 13 · audit or design before implementing 12 · fresh reuse audit 12 · baseline and frozen artifacts 11 · required final-report structure 11 · STOP conditions 10 · do not modify unrelated parts 10 · test-status honesty 9 · provider identity 8 · git status and diff reporting 8 · do not commit or push 6 · judge quota 6 · secrets 5 · controlled variables 5 · retrieval is not answer quality 2.

Theme detection is by regular expression and counts a prompt once per theme. It is a measure of repetition, not of importance.

## 2. After: what the repository now supplies, and what it costs (measured)

| Measure | Value |
|---|---|
| Always loaded (`AGENTS.md` + `CLAUDE.md`) | 109 lines · 1,244 words |
| Always visible descriptions (13 skills + 6 agents) | 825 words |
| **Standing context per session** | **2,069 words** |
| On demand | 13 skills (35–50 lines, median 38) · 6 agents (26–28 lines) · 6 rules (15–19 lines, 855 words in total) · 6 docs (50–120 lines) |
| Reference project for comparison | skills: median 266 lines · agents: median 159 lines |

**The standing context is larger than one median task prompt (2,069 words against 1,555).** The studio therefore does not reduce the text the model reads. What it changes is who supplies the rules: they are loaded every session instead of retyped, and some are enforced instead of requested. If the user stops restating them, the saving is at most the rule-mentioning share of a prompt, which the measurement above bounds at 7% of lines (about 110 words for a median prompt). Most of a prompt is task-specific: the steps, the output format and the scope.

## 3. Which repeated instructions are now supplied, and which are enforced

"Enforced" means code stops or flags a violation. "Supplied" means the rule is in front of the model but only the model's compliance upholds it.

| Theme (prompts restating it) | Supplied by | Enforced |
|---|---|---|
| Reuse-first (14), fresh reuse audit (12) | `AGENTS.md` rule 1, `reuse-audit`, `reuse-auditor`, `REUSE_FIRST_POLICY.md` | no |
| Licence check (13) | `license-audit`, `THIRD_PARTY_NOTICES.md` | no |
| Audit or design before implementing (12) | `CLAUDE.md` working agreements, lifecycle in `AGENT_WORKFLOW.md` | no |
| Baseline and frozen artifacts (11) | rule 2, `EXPERIMENT_RULES.md`, `frozen-artifacts.json` | **yes**: write guard asks, shell guard asks, commit gate denies, `guard.py verify`, register test, fingerprint pin tests |
| Final-report structure (11) | the "Output" section of each skill; the experiment report template | no. This is task-specific by nature |
| STOP conditions (10) | `AGENTS.md`, `AGENT_WORKFLOW.md` | partly: destructive commands are asked or denied |
| Do not modify unrelated parts (10) | rules 2 and 10, path rules | partly: frozen artifacts only |
| Test-status honesty (9) | rule 5, `testing`, `tests.md` | no |
| Provider identity (8) | rule 6, `provider-development` | **yes**, in code: per-request records, benchmark label, tests |
| Git status and diff reporting (8) | `git-checkpoint` | no |
| Do not commit or push (6) | rule 11 and "Ask first" | partly: push to `main` asked, force-push denied |
| Judge quota (6) | rule 9, `evaluator` | no |
| Secrets (5) | `security` | **yes**: commit gate (values from `.env` and key shapes) and the local git hook |
| Controlled variables (5) | `experiment-design` | partly: each experiment has a config-diff test |
| Retrieval is not answer quality (2) | rule 4, `EXPERIMENT_RULES.md` | partly: the benchmark keeps the layers apart |

Of 16 themes, 3 are fully enforced and 5 more are partly enforced; 8 rest on instruction only. Several of the enforced ones already had code behind them before this work (fingerprint pins, provider records, the git hook). What the hooks add is enforcement at the moment an agent acts, and a single versioned register of frozen files.

## 4. Hooks on real work (measured)

The hooks were replayed over every shell command and every file edit of the previous session. Replay uses today's repository state, so a command that was legitimate when run (for example, creating a collection that is now frozen) is flagged.

| Replay | Count |
|---|---|
| Shell commands | 517, of which 12 were `git commit` |
| Flagged | **8 (1.5%)** |
| Write or Edit calls | 194 |
| Flagged as frozen | **2** (the baseline config and `golden.json`, both edited before they were frozen) |
| Edits that would trigger the pin check · the lint check | 6 · 49 |

The 8 flagged commands, by cause: ingestion into a collection that exists today (3, now `deny`), `git push origin main` (3, `ask`; all requested by the user at the time), an in-place edit of the baseline config before it was frozen (1, `ask`), a redirect into a config that is frozen today (1, `ask`). All eight are the intended behaviour under today's rules. The other 509 commands raised no flag. I cannot claim the hooks would have prevented any past incident; none of the eight was a mistake when it ran.

**Live probes in this session** (both harmless by construction):

| Probe | Result |
|---|---|
| `git push --force --dry-run …` | blocked by the hook (`deny` is enforced) |
| `rm -rf eval/results/<nonexistent>` while the rule was still `ask` | **ran** (an `ask` was approved automatically in this bypass-permissions, non-interactive session) |
| the same `rm -rf`, after run results were changed to `deny` | blocked |

This is why run results and existing collections are `deny`. It also means an `ask` is only advisory in bypass mode.

**Behaviour of the checks themselves**
- 106 offline tests cover the guard: a labelled table of commands that must be flagged and commands that must not, the secret scan, the fail-open path and the PostToolUse contract.
- Mutation check: three deliberate breakages of the guard (push-to-main rule off, key-pattern anchor removed, heredoc handling off) were each caught by the tests, and the file was restored byte-identical.
- The replay found two parser bugs that the hand-written tests had missed: a backslash-newline continuation split one command into two, and a `->` inside a quoted `sed` script hid a real redirect. Both were fixed and now have regression tests.

**Noise while building the studio itself**

The drift hook sent 18 messages during construction. 16 were intermediate states: 12 because the test directory did not exist yet (fixed by skipping the check when there is nothing to run), and 4 in the middle of multi-edit sequences, where one edit depends on the next. 2 were real catches: two new skills not yet routed from `AGENTS.md`, and a wrong expectation in one of my new tests. This is the worst case, since it is bulk-editing interdependent files. Routine experiment work has not been measured.

**Noise after the two-tier change (measured 2026-11-04)**

Change: after a studio edit the hook now runs the checks that depend only on that file (inline checks, plus one parametrised lint test for a skill, agent or rule). Checks that read several files (routing from `AGENTS.md` and `CLAUDE.md`, link and path checks) moved to the commit gate, which runs them on the whole change. Pin tests after config edits are unchanged.

Method: eight synthetic edits, replayed through the hook as it was at `HEAD` and as it is now, in a scratch copy of the repository (same files, same tests, results folder included). Two sequences create a skill in steps and name a skill before it exists. Two edits are real defects (skill name differs from its directory; description missing). One edit is a harmless docs sentence. One run of each, so timings are indicative only.

| Measure | Before | After |
|---|---|---|
| Harmless edits blocked (6) | 2 | 1 |
| Real defects caught (2) | 2 | 2 |
| Hook time over the 8 edits | 92.6 s (about 10 s per studio edit) | 5.9 s (about 1 s per skill edit, 0.1 s otherwise) |

The remaining block is a skill file written with a front matter and no sections yet: it is malformed at that moment, so the lint is right to say so. Writing a skill in a single Write avoids it. The one block removed was "skill exists but is not yet routed", which the commit gate now reports instead. The scale is small (eight edits, synthetic), and the harness was fixed twice before this run (a too-short description in my own sample and a results folder missing from the copy), so treat the counts as an illustration of the mechanism, not a rate.

**Cost of the hooks**

| Measure | Value |
|---|---|
| One hook call (Python start included), median | about 115 ms for shell and write guards |
| `guard.py verify` (14 hashes, 6 fingerprints) | about 0.37 s |
| Studio lint and hook tests | about 1.2 s (in the normal offline suite) |
| Pin check after a config edit | about 2.3 s |
| Arithmetic only: replayed session size (517 + 194 calls) at 115 ms | about 80 s of added latency over the whole session |

## 5. Not measured yet

- **Agent value.** Discovery is confirmed: a call to `researcher` failed in the session that created the files and worked after a restart, with its skill and the project rules loaded. Whether delegating to an agent beats working in the main conversation has not been measured, and no claim about it is made.
- **End to end.** The claim "short requests now work" needs a comparison on a real task, which does not exist yet.

For the next real task (for example Experiment 04), record in its report:

1. the words in the user's request, against the 1,555-word median above;
2. the number of times the user had to restate a standing rule or request a check;
3. how many hook asks or denies occurred, and whether each was correct;
4. any quality check that was missed;
5. hook messages that were intermediate states rather than defects (the count above is the reference: 1 of 8 synthetic edits).

One task is one data point. Do not turn a single comparison into a rate; repeat on the next task of the same kind before stating one.

Compare like with like (a task of the same kind). A result with no improvement is a valid result.

## 6. What the evidence supports

| Claim | Status |
|---|---|
| The repository now supplies all 16 tracked themes (15 of them were restated in 3 or more prompts) | supported (section 3) |
| Prompt size falls | **not supported yet.** The bound is about 7% of lines; the standing context costs more than a median prompt |
| Repeated explanation falls | supported as a possibility, not measured end to end |
| Manual coordination falls | not measured |
| Fewer missed quality checks | partly supported: frozen-artifact changes and key leaks are now checked in the agent loop; honesty of test reporting is still the agent's duty |
| The system adds little friction | measured for shell and edit hooks (1.5% flagged, about 115 ms each); not measured for routine experiment work |

Possible next step if prompt size is the goal: a reusable brief or template for the repeated task types (audit, experiment, implementation), since 11 of 15 prompts restated a required report structure and 12 an audit-before-implementation preamble. This was not built: the data above does not yet show that a template would be reused.
