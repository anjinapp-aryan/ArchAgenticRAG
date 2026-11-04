# Agent workflow and quality gates

One lifecycle, with the quality gates as its checkpoints. (The separately proposed quality-gates file was merged here: gates and lifecycle describe the same sequence, and two files would restate each other.)

## Lifecycle

```text
UNDERSTAND → INSPECT → AUDIT → DESIGN → GO / NO-GO → IMPLEMENT → TEST → REVIEW → DOCUMENT → CHECKPOINT
```

An audit or design request **ends at GO / NO-GO**. Implementation starts only after a GO and the user's go-ahead.

Experiments:

```text
HYPOTHESIS → REUSE AUDIT → ARCHITECTURE REVIEW → IMPLEMENT → RETRIEVAL EVALUATION (Tier 1) → ANSWER EVALUATION (Tier 2, if approved) → DECISION
```

## Quality gates

Skip a gate only when its "applies" column says it does not; do not mark a gate passed without evidence.

| Gate | Applies | Passes when | Skills |
|---|---|---|---|
| 0 Scope | always | the ask, the boundaries and the stopping point are clear; ambiguity is resolved or flagged | |
| 1 Reuse | new capability, dependency or model | reuse audit done, licences known, outcome chosen | `reuse-audit`, `license-audit` |
| 2 Architecture | structural change | smallest compatible design; GO or GO WITH CONDITIONS | `architecture-review` |
| 3 Implementation | any code | change is additive and in scope; frozen artifacts untouched | `change-review` |
| 4 Tests | any code | statuses reported per category; no regression; new behaviour covered | `testing` |
| 5 Security | before any commit | no credentials in the diff, logs or results; scans clean | `security` |
| 6 Evaluation | experiments | Tier 1 complete; Tier 2 only if approved; comparison controlled and paired | `experiment-design`, `evaluation` |
| 7 Documentation | behaviour or results changed | report, README status, registry and notices match the evidence | |
| 8 Checkpoint | when asked to commit | earlier gates evidenced; commit verified; push only if asked | `git-checkpoint` |

The proposed 0–8 model was kept: the repository's own phases (audit, implement, retrieval evaluation, answer evaluation, decision) map onto it without change.

## Human approval boundaries

Ask first (do not start) for the items below; everything else inside the approved scope proceeds without asking. "Enforced" means a hook in `.claude/hooks/guard.py` acts. The hook has two strengths:

- **deny** blocks the call in every permission mode (verified live on 2026-11-03).
- **ask** prompts the user in normal modes, but in a bypass-permissions, non-interactive session it was approved automatically (also verified live). Treat an `ask` as advisory in that mode.

For that reason irreversible targets are denied, not asked: run results (`eval/results`, gitignored, one copy) and ingestion into an existing collection. The user can unlock them by setting `ARCHAGENTICRAG_ALLOW_DESTRUCTIVE=1` in the environment before starting Claude Code; an agent cannot set it from inside a tool call.

| Ask the user before | Enforced |
|---|---|
| Changing the baseline, an earlier experiment's config, the golden set, the corpus or qrels | yes: write guard and Bash guard ask |
| Changing or deleting run results; ingestion into an existing collection | yes: deny (user override only) |
| Pushing to `main`, force-pushing, `reset --hard`, `clean -f`, discarding all changes | yes: ask or deny |
| Committing with a leaked key or a changed frozen artifact | yes: deny |
| A major architecture change, a breaking interface change, or a change that touches production | no |
| A new paid dependency or external service; a component with an unclear licence | no |
| Spending judge quota; starting Ragas judging | no |
| Growing the scope beyond what was approved; starting the next experiment | no |

Proceed without asking: implementing inside an approved design, adding tests and docs, creating a new config or branch for the current experiment, running offline tests, read-only investigation.

## Status vocabulary

Tests: `PASS` · `FAIL` · `SKIPPED` · `NOT RUN` · `BLOCKED` (prerequisite missing). Deselected tests are `NOT RUN`.
Design: `GO` · `GO WITH CONDITIONS` · `NO-GO`.
Experiment: `WIN` · `MIXED` · `NO IMPROVEMENT` · `REGRESSION`. Evaluation: `COMPLETE` · `IN PROGRESS` · `RETRIEVAL ONLY` · `FAILED` · `NOT RUN`.

Report them like this, never as a single "all tests pass":

```text
Offline:     PASS (N passed; M deselected = NOT RUN)
Integration: BLOCKED (Docker engine down)
Live:        NOT RUN (no code changed; uses free-tier quota)
```

## STOP conditions

Stop, name the condition, show the evidence (command and output), say what was **not** done, offer options. Do not fix forward, and do not revert changes you did not make.

1. The baseline, a frozen artifact, a fingerprint or a result file changed unexpectedly.
2. Configuration drift between compared runs.
3. A licence is unclear for something about to be added.
4. A major architectural rewrite appears necessary.
5. Tests regressed, or required tests cannot be executed.
6. A credential is exposed (diff, log, result, chat): do not commit, tell the user to rotate it.
7. A reusable solution exists but the plan builds it anyway.
8. The comparison becomes uncontrolled: more than one variable, or a different provider or model answered.
9. The scope grows without approval.
10. The only path needs a paid API.
11. A step would be destructive to data: ingestion into an existing collection, deleting a run or a collection, rewriting history.
12. A step would spend judge quota nobody asked for.
