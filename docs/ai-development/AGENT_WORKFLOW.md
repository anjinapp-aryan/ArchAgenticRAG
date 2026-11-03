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
