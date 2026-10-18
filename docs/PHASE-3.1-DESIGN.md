# Phase 3.1 Design: Query Decomposition (conditional multi-query retrieval)

**Status: design only. Implementation has not started.** This document is for implementation review.

| | |
|---|---|
| Evidence base | [PHASE-2-BASELINE-RESULTS.md](PHASE-2-BASELINE-RESULTS.md) (run `20261001T173531Z-baseline-basic-rag-63bf3b5f-6227d9`), plus a retrieval-only probe run on 2026-10-18 (section 6) |
| Date | 2026-10-18 |
| Supersedes | The 2026-10-15 draft. The recommendation is unchanged; it now has direct evidence against the non-agentic alternatives. |

## 1. Phase 2 baseline summary

| Dimension | Result |
|---|---:|
| Questions | 42 |
| Passed / failed (triage) | 27 / 15 |
| Judge metrics expected / scored / missing | 175 / 169 / 6 (judge limits; counted as missing, not as failures) |
| Faithfulness | 0.847 (n=34) |
| Answer relevancy | 0.887 (n=30) |
| Context precision | 0.756 (n=29) |
| Context recall | 0.783 (n=35) |
| Answer correctness | 0.724 (n=30) |
| Abstention / clarification | 6/6 / 0/5 |
| Source-doc recall by category | A 1.00, B 1.00, C 0.83, D 0.71, F 1.00, G 0.92 (E has no source documents) |
| Latency p50 / p95 | 6.92 s / 20.14 s end to end; retrieval 22 ms / 44 ms (generation includes free-tier queueing) |
| LLM calls, tokens | 1.0 per question; ≈1,072 input and 218 output tokens per question; cost `null` |

## 2. Category analysis

| Cat. | n | Pass | Retrieval | Key Ragas metrics | Failure examples | Likely root cause |
|---|---:|---:|---|---|---|---|
| A: Direct factual | 7 | 6 | source-doc recall 1.00 | faith. 1.00, correctness 0.86 | A05 (correct but brief; correctness 0.34) | Judge strictness, not the system |
| B: Multi-sentence | 6 | 5 | 1.00 | faith. 0.94, recall 0.94 | B03: the function-name section of PEP 8 was not retrieved | Section-level retrieval miss (`top_k=4`) |
| C: Multi-document | 6 | 3 | **0.83** (4/6 full) | **precision 0.42, recall 0.64, correctness 0.59** | C03 (no PEP 518), C05 (no PEP 484, so answered from prior knowledge) | **All 4 chunks from one PEP** |
| D: Ambiguous | 5 | **0** | 0.71 (2/4 full) | clarification **0/5**, recall 0.40 | D01 answered for PEP 649 only; D02 has no referent | No ambiguity handling; retrieval collapse on D01 and D03 |
| E: Out-of-corpus | 6 | 6 | — | abstention **6/6** | — | Strong; must not regress |
| F: Lexical vs semantic | 6 | 4 | 1.00 | recall 0.94, correctness 0.72 | F04, F05 (correct answers, low judge scores) | Judge-side |
| G: Multi-hop | 6 | 3 | 0.92 (5/6 full) | recall 0.69, correctness 0.66 | G02 (second hop PEP 484 missing), G03 (PEP 585 header missing) | Retrieval miss: second document or section |

## 3. Failure matrix, with retrieval separated from generation

For each failure the question is: **was the required evidence retrieved?** This was checked against the retrieved chunks themselves, not inferred from the score.

| Failure | Question IDs | Evidence retrieved? | Evidence | Triage labels (harness) | Root cause | Freq. | Severity |
|---|---|---|---|---|---|---:|---|
| **Single-document collapse** | C03, C05, G02 (+D01, D03) | **No**: a required PEP is absent | all 4 chunks from 1 PEP in every case; C precision 0.42, recall 0.64 | GENERATION_FAILURE, HALLUCINATION, CONTEXT_FAILURE | One query vector lands near one PEP | 5 | **High**: wrong or ungrounded answers (C05, G02 answered from prior knowledge) |
| **Section-level miss** | G03, B03 (+D04) | **No**: right PEP, needed section absent | "3.9", "lowercase, with words separated" and the "Status:" header are absent from the context | GENERATION_FAILURE, HALLUCINATION | The needed section ranks below the top 4 | 3 | Medium: incomplete answers that say what is missing |
| **No clarification** | D01–D05 | Mixed: D02 and D05 yes (generation / query understanding); D01, D03, D04 no | clarification 0/5 | AMBIGUITY | No ambiguity detection in the graph or prompt | 5 | Medium: plausible but one-sided answers |
| **Judge-side** | A05, F05, F04, G01 | **Yes**: evidence present | answers verified correct by hand; scores 0.34, 0.49, 0.20, 0.33 | GENERATION_FAILURE, HALLUCINATION | LLM judge strictness or variance | 4 | None for the system; a risk for measurement |
| **Unscorable** | C04 | Yes | faithfulness not computable | OTHER | Judge output limit | 1 | None |
| Out-of-corpus | E01–E06 | n/a | 6/6 abstain | — | — | 0 | — |

**Split:**

- **8 of 15** failures start at retrieval: C03, C05, G02, G03, B03, D01, D03, D04.
- 2 are pure generation / query-understanding failures: D02, D05.
- 4 are judge-side.
- 1 is unscorable.

The harness labels several retrieval failures as GENERATION_FAILURE or HALLUCINATION, because its triage looks at context recall thresholds rather than at missing documents. This analysis uses the verified cause.

## 4. Top 3 problems

| Rank | Problem | Evidence | Why it matters |
|---|---|---|---|
| 1 | **Single-document retrieval collapse** | 5 of 13 multi-document items missed a PEP, always with 4 chunks from one PEP. C: precision 0.42, recall 0.64, correctness 0.59. Causes the 2 prior-knowledge answers (C05, G02). | Most frequent verified cause; highest severity (ungrounded answers); a core RAG architecture lesson; affects C, D and G |
| 2 | **No clarification for ambiguous questions** | D: 0/5 | A clear behaviour gap, but only 5 items, and 3 of them are also retrieval failures. Fix retrieval first so clarification can be measured cleanly. |
| 3 | **Section-level misses inside the right PEP** | G03, B03, D04 | Smaller (3 items). Partly addressed by #1's fix, since a focused sub-question names the missing fact. |

## 5. Agentic technique comparison

| Technique | Failure addressed | Evidence for or against | Complexity | Learning value | Recommendation |
|---|---|---|---|---|---|
| **Decomposition** | #1, part of #3 | All 5 collapse cases need a second, differently-worded query. Only multi-need questions are split, so A, B, E and F keep baseline retrieval (see section 6). | Low–medium: 1 LLM node and a `Send` fan-out | High: query analysis, parallel fan-out, state reducers | **Phase 3.1** |
| Query rewriting (single query) | — | Paraphrased queries are not a measured problem: F recall 0.94. One rewritten query still collapses onto one PEP. | Low | Medium | Reject for now |
| Reranking | #3 partly | Cannot add a PEP that was never retrieved (C03, C05, G02) | Medium (cross-encoder model) | Medium | Later, if section misses persist |
| Hybrid (BM25 + dense) | — | No lexical gap measured: F has source-doc recall 1.00 | Medium | Medium | Reject for now |
| Corrective RAG | #1's symptom (C05, G02) | It detects missing context but does not retrieve the missing PEP, and its web-search fallback is out of scope. Out-of-corpus abstention is already 6/6. | High | High | Later (3.x), if grounding gaps remain after 3.1 |
| Query routing | #2 | Only one index, so there is nothing to route between. Ambiguity is the real need. | Medium | Medium | Reject |
| Clarification (query analysis, then ask back) | #2 | D 0/5 | Low–medium | High | **Phase 3.2 candidate** |
| Multi-step / iterative retrieval | G02 (hop 2 not named in the question) | 1 item | Medium–high | High | Later, if G stays low after 3.1 |
| Reflection / Self-RAG | Grounding | Faithfulness 0.85 overall. Low items are judge-disputed or retrieval-caused. | High | High | Reject for now |
| Tool calling | — | No external tools needed: closed corpus | — | — | Reject |
| Multi-agent | — | No evidence of a need | High | High | Reject |
| *Non-agentic controls:* `top_k=8`, MMR | #1 | Section 6: MMR fixes coverage but hurts precision everywhere; `top_k=8` barely helps coverage | Trivial | Medium | **Run as controls B1 and B2** |

## 6. New evidence: retrieval-only probe (2026-10-18)

This probe uses no LLM and changes nothing in the repository. Script: session scratchpad `retrieval_probe.py` / `retrieval_probe2.py`. It queries the baseline Qdrant collection with each golden question.

**Multi-document coverage** (13 items needing 2 or more PEPs; fully covered = every needed PEP is in the results):

| Mode | Fully covered |
|---|---|
| Baseline dense, k=4 | 8/13 |
| Dense, k=8 (control B1) | 9/13 |
| MMR, k=4, fetch_k=20 (control B2) | 11/13, but C02 regresses (was covered) |
| MMR, k=8 | 13/13 |

**The cost of MMR on questions that were already strong.** "On-target" is the share of retrieved chunks that come from the question's expected PEPs:

| Category | k=4 on-target | MMR k=4 on-target |
|---|---:|---:|
| A | 0.93 | **0.68** |
| B | 0.79 | **0.58** |
| F | 0.67 | **0.38** |
| C | 0.92 | 0.71 |
| G | 0.92 | 0.71 |

**Section-level misses** (is the needed text in the context?):

| Item | k=4 | k=8 | MMR k=4 |
|---|---|---|---|
| G03 | ✗ | ✓ | ✗ |
| D04 | ✗ | ✓ | ✗ |
| B03 | ✗ | ✗ | ✗ |

**Conclusion:**

- **MMR proves that diversity fixes the collapse.** But it diversifies *every* query, cutting on-target context by 0.21–0.29 on A, B and F, which are the categories that already pass.
- **`top_k=8` adds volume, not diversity** (9/13).
- The measured need is **conditional diversity**: spread retrieval across sub-questions only when the question has several information needs. That per-question decision is the agentic step. It is why decomposition, not a global retrieval setting, is the recommendation.
- The controls still run, so the claim is tested, not assumed.

## 7. Recommended Phase 3.1

```text
RECOMMENDED PHASE 3.1:
Query decomposition: split multi-need questions into ≤3 sub-questions, retrieve for each in parallel, merge.
```

| | |
|---|---|
| Why this capability? | It fixes the most frequent, most severe verified cause (#1) at its root, and only for questions that need it. It also partly addresses #3. |
| Targeted failures | C03, C05, G02, D01, D03 (collapse); G03, B03, D04 (section misses) |
| Categories that should improve | C, G; the retrieval half of D |
| Metrics that should improve | C and G context recall and context precision, C answer correctness, multi-document coverage, C/G faithfulness (fewer prior-knowledge answers) |
| What could regress | A, B, F precision if single-need questions are split; E abstention if extra context tempts an answer; latency and tokens (+1 LLM call) |
| Unchanged | Corpus, 42 questions, embeddings, Qdrant collection, chunking, per-query `top_k=4`, generator and its prompt, judge, metrics, triage thresholds |

## 8. Experiment design

| Run | System | Config (new files; the baseline config is untouched) |
|---|---|---|
| Baseline | Basic RAG (existing run) | `eval/configs/baseline-basic-rag.yaml` |
| B1 | Basic RAG, `top_k: 8` | `eval/configs/control-b1-topk8.yaml` |
| B2 | Basic RAG, MMR k=4, fetch_k=20 | `eval/configs/control-b2-mmr.yaml` |
| **3.1** | Basic RAG + decomposition | `eval/configs/phase3-1-decomposition.yaml` |

- **Same harness:** `run_eval.py`, then `resume_eval.py` until done.
- **Same judge limits:** the same 6 values may again be unscorable. They are reported the same way, and comparisons use items scored in both runs.
- **The decompose node uses the generator model** (Groq `openai/gpt-oss-120b`), so no new model enters the comparison.
- **Run order:** B2, B1, then 3.1. The cheap controls run first; if one meets the gates, 3.1 is reconsidered before it is built.

## 9. Success criteria (fixed now, before any Phase 3.1 result exists)

| Criterion | Baseline | B2 probe (coverage only) | 3.1 target | Type |
|---|---:|---:|---:|---|
| Multi-document items fully covered | 8/13 | 11/13 | **≥ 11/13** | must |
| Multi-document misses with all chunks from 1 PEP | 5 | — | ≤ 1 | must |
| C context recall | 0.64 | — | **≥ 0.80** | must |
| C answer correctness | 0.59 | — | **≥ 0.70** | must |
| G context recall | 0.69 | — | ≥ 0.80 | must |
| C context precision | 0.42 | — | ≥ 0.55 | should |
| A/B/F on-target retrieval share (probe metric) | 0.93 / 0.79 / 0.67 | 0.68 / 0.58 / 0.38 | **≥ 0.88 / 0.74 / 0.62** (within 0.05 of baseline) | must |
| A and B pass counts | 6/7, 5/6 | — | not lower | must |
| E abstention | 6/6 | — | **6/6** | must |
| Faithfulness overall | 0.847 | — | ≥ 0.83 | must |
| Answer relevancy overall | 0.887 | — | ≥ 0.86 | must |
| Pass rate | 27/42 | — | > 27/42 | should |
| LLM calls per question | 1.0 | 1.0 | ≤ 2.0 | must |
| Generator tokens per question | ≈1,290 | — | ≤ 2.5× | must |
| Retrieval latency p50 | 22 ms | — | ≤ 100 ms | should |
| **Against B1 and B2** | — | — | Beat both on C+G context recall **and** keep A/B/F on-target within 0.05 of baseline (B2 fails this) | **must** |

Judge-disputed items (A05, F05, F04, G01) are inspected by hand before any delta on them is counted.

## 10. Fresh reuse audit (2026-10-18)

| Repository | Licence | Activity | Relevant capability | Reuse potential | Decision |
|---|---|---|---|---|---|
| [GiovanniPasq/agentic-rag-for-dummies](https://github.com/GiovanniPasq/agentic-rag-for-dummies) @ `394c4f7` (`project/rag_agent/schemas.py`, `prompts.py`, `edges.py`; unchanged since `f0d9a3c`) | MIT | 4.3k★, pushed 2026-10-17 | `QueryAnalysis` schema (`questions: list[str]`). Rewrite rules: "Split only truly separate information needs, with a maximum of 3", "Preserve … names … exactly", "Do not add facts". `route_after_rewrite` returns `Send("agent", …)` per sub-question. | High: the exact pattern needed | **ADAPT** the schema shape, the decomposition rules and the `Send` fan-out, with a notice in THIRD_PARTY_NOTICES. **Do not copy:** the clarification branch (3.2 scope), the agent/tool loop, the conversation memory, or per-sub-question answering. |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) 1.2.12 (installed) | MIT | 43k★, pushed 2026-10-18 | `langgraph.types.Send` (verified installed), `Annotated[list, operator.add]` reducers, the map-reduce pattern ([graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api)) | High; no new dependency | **REUSE** |
| `langchain-openai` `ChatOpenAI.with_structured_output` (installed) | MIT | — | Typed sub-question list | High | **REUSE** |
| `langchain-qdrant` `max_marginal_relevance_search` / `as_retriever(search_type="mmr")` (installed) | MIT | — | MMR | Control B2 only | **REUSE** (control) |
| `langchain_classic.retrievers.multi_query.MultiQueryRetriever` ([reference](https://reference.langchain.com/python/langchain-classic/retrievers/multi_query)) | MIT | Deprecated in favour of a runnables pattern | Paraphrase multi-query with unique union | Low: paraphrases do not split needs, and `langchain-classic` is not installed | **REFERENCE** (dedup semantics) / **REJECT** as a dependency |
| [langchain-ai/rag-from-scratch](https://github.com/langchain-ai/rag-from-scratch) | **None** | 9.5k★, last push 2025-06 | Decomposition notebooks | Concepts only | **REFERENCE**; no code |
| [NirDiamant/RAG_Techniques](https://github.com/NirDiamant/RAG_Techniques) | **Custom non-commercial** (NOASSERTION) | 30k★ | Query transformations | Forbidden for commercial products and services | **REJECT** |
| [run-llama/llama_index](https://github.com/run-llama/llama_index) `SubQuestionQueryEngine` | MIT | 52k★ | Sub-question engine | Would add a second framework | **REFERENCE** |

**Result:** COMPOSE LangGraph `Send` with structured output, and ADAPT the decomposition rules. New code is limited to 1 node, 1 router, 1 merge function and 1 prompt.

## 11. Proposed architecture

### Current

```text
START → retrieve → generate → END
```

### Proposed Phase 3.1

```text
START
  │
  ▼
decompose          LLM, structured output → 1–3 self-contained sub-questions
  │                (original question always first; single need → only the original)
  │ Send × N       conditional fan-out: N=1 reproduces baseline retrieval exactly
  ▼
retrieve_one       existing retriever (dense, k=4) for one sub-question
  │                results accumulate via a list reducer
  ▼
merge              unique union by chunk_id, original-question hits first, cap 8 chunks
  │
  ▼
generate           UNCHANGED node and prompt
  │
  ▼
END
```

It remains a DAG: no loops, no grading, exactly 2 LLM calls per question.

### State changes

| Field | Status | Type | Written by | Read by |
|---|---|---|---|---|
| `question` | existing | `str` | input | decompose, generate |
| `sub_questions` | **new** | `list[str]` | decompose | router, evaluator (recorded for analysis) |
| `retrieved` | **new** | `Annotated[list[Document], operator.add]` | retrieve_one (per `Send`) | merge |
| `documents` | existing | `list[Document]` | **merge** (was retrieve) | generate, evaluator |
| `context` | existing | `str` | merge | generate |
| `answer` | existing | `str` | generate | evaluator |

`retrieve_one` receives `{"sub_question": str}` through `Send`. The evaluator contract (`question` in, `answer` and `documents` out) is unchanged.

## 12. Files and code impact

| File | Change | Notes |
|---|---|---|
| `src/archagenticrag/graphs/decompose_rag.py` | **new** | `build_graph(system=...)`: the decompose node, `Send` router, `retrieve_one`, merge; reuses `basic_rag.PROMPT` and `format_documents` |
| `src/archagenticrag/graphs/basic_rag.py` | small, behaviour-preserving | Pass `settings.retrieval.search_type` and MMR `fetch_k` to `as_retriever` (needed by B2). The default stays `similarity`, so the baseline is unchanged; a test pins this. |
| `src/archagenticrag/rag/settings.py` | additive | `RetrievalSettings.search_type: Literal["similarity", "mmr"]`, optional `fetch_k`; new optional `DecompositionSettings` (`max_sub_questions` 1–3, `max_context_chunks`) |
| `src/archagenticrag/evaluation/config.py` and `runner.py` | additive, optional | `target.record_keys: [sub_questions]` to persist extra state per item. Without it, sub-questions are not inspectable after a run. |
| `eval/configs/control-b1-topk8.yaml`, `control-b2-mmr.yaml`, `phase3-1-decomposition.yaml` | **new** | Copies of the baseline config with only the documented differences |
| `THIRD_PARTY_NOTICES.md`, `docs/PHASE-1-REUSE-AUDIT.md` (or a new 3.1 audit) | update | agentic-rag-for-dummies @ `394c4f7` attribution |
| Baseline config, golden dataset, corpus, Ragas metrics, judge | **no change** | — |

## 13. Tests required

All offline, using a fake LLM and in-memory Qdrant:

1. A single-need question gives `sub_questions == [question]` and **exactly the baseline retrieval** (same chunk IDs as `basic_rag`).
2. The decomposer output is capped at 3, the original question is always first, and blank or duplicate sub-questions are dropped.
3. `Send` fan-out produces one `retrieve_one` call per sub-question.
4. Merge dedups by `chunk_id`, keeps the original question's hits first, and respects `max_context_chunks`.
5. The generate prompt and node are byte-identical to the baseline.
6. Evaluator contract: `run_target` returns `answer` and `documents` with `doc_id` metadata; `sub_questions` is recorded when `record_keys` is set.
7. Settings: invalid `max_sub_questions` is rejected; `search_type: mmr` is accepted; the baseline config still parses with `search_type` defaulting to `similarity`.
8. A decomposer failure (bad JSON or an LLM error) falls back to `[question]`, so retrieval still happens and the error is recorded, not swallowed.

Plus one integration test on the real Qdrant: C03 retrieves both PEP 518 and PEP 621. Plus one live test: C03 runs end to end through the evaluator.

## 14. Learning objectives

| Area | What this experiment teaches |
|---|---|
| Architecture | The difference between a global retrieval knob (MMR, `top_k`) and a per-query decision, and why controls are needed to tell them apart |
| LangGraph | Structured-output nodes, dynamic `Send` fan-out (map-reduce), reducer-based state merging, keeping the evaluator contract stable while the graph changes |
| Retrieval behaviour | Why dense top-k collapses onto one document; how query focus changes embedding neighbourhoods; on-target share versus coverage |
| Agent decision-making | When an LLM should split a question, the cost of over-splitting, and fallback when the decision fails |
| Evaluation | Pre-registered success criteria, controls, separating judge noise from real deltas, comparing only items scored in both runs |
| Trade-offs, latency, reliability | +1 LLM call and parallel retrieval versus quality; decomposer failure modes; free-tier quota effects on experiment turnaround |

## 15. Risks and trade-offs

| Risk | Effect | Mitigation |
|---|---|---|
| Over-splitting single-need questions | Lower precision on A, B, F | "Single need → original only" rule; on-target gate; test 1 |
| Out-of-corpus questions decomposed into plausible-looking sub-questions | Possible answer instead of abstention | E 6/6 gate; generate prompt unchanged |
| Hop 2 not nameable up front (G02 does not mention PEP 484) | Parallel decomposition cannot follow a chain | Measured. If G stays low, iterative retrieval is a later candidate. |
| Decomposer invents PEP numbers or facts | Retrieval steered wrong | "Do not add facts" rule; `sub_questions` recorded for inspection |
| Gains come from more context, not from decomposition | Wrong attribution | B1 at the same 8-chunk budget |
| Judge noise or free-tier limits | False deltas; multi-day runs | Hand inspection of disputed items; resume mechanism; compare items scored in both runs |
| Extra generator calls (+42 per run) | Quota and latency | Well within Groq's daily request limit; latency gate |

## 16. Implementation status

**Not started.** No Phase 3 code, configs or tests exist. Basic RAG, the benchmark, the golden dataset, the Ragas configuration and the judge are unchanged. The only actions taken were a read-only retrieval probe against the existing index and edits to this document.
