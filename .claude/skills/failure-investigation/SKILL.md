---
name: failure-investigation
description: "Use when something fails in ArchAgenticRAG: a test, a run, an evaluation item, a provider call, a Docker or Qdrant error, a metric that looks wrong. Classifies the failure first (environment, provider quota, data or state, non-determinism, code defect), reproduces it, finds the root cause with evidence and only then fixes."
---

# failure-investigation

## Purpose
Find the cause before changing anything. Most failures in this project were environmental or quota, not code.

## When to use
Any unexpected error or result. Skip nothing because "it looks like X".

## Inputs
The exact failing command, the shortest decisive error line, and the run id or item id if any.

## Workflow
1. **Capture evidence:** the command, the error line, timestamps, run and item ids. Do not paraphrase the error.
2. **Classify** with this table (all of these have happened here):

| Symptom | Class | First check and action |
|---|---|---|
| `WinError 10061` / connection refused to `localhost:6333`; `docker info` fails | Environment | Docker Desktop stopped or Qdrant down. Start Docker; if the engine hangs, ask the user before restarting. Report integration as BLOCKED meanwhile |
| `Could not load model` / model re-download | Environment | FastEmbed cache under `%TEMP%` was cleared. Set `FASTEMBED_CACHE_PATH` to a permanent folder (`.env.example`) |
| `UnicodeEncodeError ... cp1252` when printing | Environment | Windows console. Set `PYTHONIOENCODING=utf-8` |
| 429 with "tokens per minute" | Provider quota | Retry later; `resume_eval.py <run> --no-judge`; never run quota work concurrently with a run |
| 429 with "tokens per day" or `PROVIDER_EXHAUSTED` | Provider quota | Stop; resume the next day. Do not retry in a loop |
| `ResumeError` dataset changed; fingerprint or hash mismatch | Data or state | A frozen artifact moved. Run `guard.py verify`; STOP, do not fix forward |
| Chunk catalog differs from qrels | Data or state | Collection re-indexed or chunking changed. Compare with the qrels file; do not recreate the baseline |
| Hybrid results differ between identical calls | Non-determinism | RRF score ties. Repeat 5-10 times and compare ranges before calling it a regression |
| A metric is `null` | State | Judge failed or was deferred; check the item's `error` and the run's `judge_deferred` before suspecting code |
| Assertion in own code, wrong output | Code defect | Continue below |

3. **Reproduce minimally:** the smallest command that shows it, offline if possible.
4. **Hypotheses:** list 2-3, rank them, and test each with one command. Change one thing at a time.
5. **Root cause statement:** one sentence, with the evidence that proves it and what was ruled out.
6. **Fix:** smallest change plus a regression test for code defects. No code change for environment or quota; fix the environment or wait.
7. **Record:** if the class was new, add a row to the table above.

## Required checks
- The cause is proven, not inferred from a similar past incident.
- Frozen artifacts untouched (`guard.py verify`).

## Output
Failure report: symptom, evidence, class, root cause, fix or action, regression test, what was ruled out.

## STOP
- The cause is still unknown after several distinct hypotheses: report what is known, do not guess a fix.
- The fix would change a frozen artifact or spend quota nobody approved.
- The only remedy is a repeated retry of a provider that is out of quota.
