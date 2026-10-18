# Phase 2: Basic RAG Baseline Results

Measured results of the Phase 1 Basic RAG system (`START → retrieve → generate → END`) on the 42-question golden set. This is the control experiment for every later Agentic RAG change.

The numbers below are taken from `eval/results/20261001T173531Z-baseline-basic-rag-63bf3b5f-6227d9/summary.json` and `items.jsonl`. The results folder is gitignored, so this document is the committed record.

## 1. Run identity and reproducibility

| Field | Value |
|---|---|
| Run ID | `20261001T173531Z-baseline-basic-rag-63bf3b5f-6227d9` |
| Config | `eval/configs/baseline-basic-rag.yaml`, fingerprint `63bf3b5f990cc9e5` |
| Generator | Groq `openai/gpt-oss-120b`, temperature 0 |
| Judge | Groq `qwen/qwen3.8-27b`, temperature 0. AnswerRelevancy embeddings: Gemini `gemini-embedding-001` |
| Retrieval | FastEmbed `BAAI/bge-small-en-v1.5` (384-d), Qdrant `peps_v1_bge_small_docling_480`, dense cosine, `top_k=4` |
| Chunking | Docling HybridChunker, 480 tokens max, 455 chunks |
| Dataset | `peps-golden` 1.0.0, 42 items, sha256 `18a359e9…` |
| Corpus | python/peps @ `50803e5`, 13 PEPs, manifest sha256 `b3f7f85b…` |
| Code at start | `94f161b`, dirty. The `answer_correctness` switch (ADR 008, Amendment 1) was in the working tree. |
| Packages | ragas 0.4.3, langgraph 1.2.12, langfuse 4.16.0, qdrant-client 1.19.1, openai 3.3.0 |
| Sessions | Initial run 2026-10-01, then resumes on 2026-10-02, 10-03 (×2), 10-14 (×2) and 10-15 (×2). One killed session on 10-03 is not in the manifest (fixed in `f96c37c`). |

**Why the run is split.** Groq's free tier allows 200,000 judge tokens per day, and the full judge pass needs roughly 800k–1M. The run was therefore finished in place with `eval/runners/resume_eval.py`:

- Answers and successful scores were never recomputed.
- Before each session, a snapshot of `items.jsonl` was compared afterwards: no recorded value was lost or changed.
- The config fingerprint, dataset hash and corpus hash matched the manifest in every session.

## 2. Integrity checks

| Check | Result |
|---|---|
| 42 unique IDs, same set and order as the dataset | ✅ |
| Duplicate records | none |
| System (generation) errors | 0. E05 and F05 hit the generator's rate limit in the first session and were re-run. |
| Answers present | 42/42 |
| Latency, LLM calls, tokens recorded | 42/42 |
| Cost | `null`: no published price was entered for the free-tier models |
| Expected metric values missing | **6 of 175**, listed below |

### Missing metric values (recorded explicitly, by user decision 2026-10-15)

| Item | Metric | Why it could not be scored |
|---|---|---|
| C04 | faithfulness | The judge's reply exceeds Ragas' default `max_tokens=1024` (`IncompleteOutputException`). Failed 4 times. |
| G02 | context_precision, answer_correctness | Groq rejects the request: Ragas asks for 1,024 output tokens, the free tier allows 1,000 per minute ("Request too large … OTPM") |
| G03 | faithfulness, answer_relevancy, context_precision | Same rejection as G02 |

No judge setting fixes both problems: C04 needs more than 1,024 output tokens, while G02 and G03 need less than 1,000. The judge was kept unchanged. These values count as missing, not as 0. Averages below use the `n` actually scored.

## 3. Overall metrics

| Metric | Mean | n | Applies to |
|---|---:|---:|---|
| Faithfulness | **0.847** | 34 | answer + clarify items |
| Answer relevancy | **0.887** | 30 | answer items |
| Context precision | **0.756** | 29 | answer items |
| Context recall | **0.783** | 35 | answer + clarify items with evidence |
| Answer correctness | **0.724** | 30 | answer items (`AnswerCorrectness`, recall-weighted) |
| Abstention | **1.000** | 6 | out-of-corpus items |
| Clarification | **0.000** | 5 | ambiguous items |
| Triage pass rate | **27/42 (64%)** | 42 | all |

| Latency (seconds) | Mean | p50 | p95 |
|---|---:|---:|---:|
| End to end | 7.27 | 6.92 | 20.14 |
| Retrieval | 0.026 | 0.022 | 0.044 |
| Generation | 7.23 | 6.90 | 20.11 |

| Usage | Value |
|---|---|
| LLM calls (system under test) | 42 total, 1.0 per question |
| Generator tokens | 45,018 input, 9,174 output (≈1,072 in and 218 out per question) |
| Judge tokens | not captured: Ragas calls bypass the target's callbacks (ADR 008) |
| Cost | `null` |

**Latency caveat.** Generation ran on Groq's free tier at `max_concurrency: 2`, so latency includes provider queueing and rate-limit back-off. The first questions answered in about 1 s, and later ones took 6–10 s. Retrieval latency (about 22 ms) is the clean number.

## 4. Category results

| Category | n | Pass | Faith. | Ans. rel. | Ctx prec. | Ctx recall | Ans. corr. | Source-doc recall* |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A: Direct factual | 7 | 6 | 1.00 | 0.94 | 0.89 | 0.93 | 0.86 | 1.00 (7/7) |
| B: Multi-sentence | 6 | 5 | 0.94 | 0.90 | 0.76 | 0.94 | 0.76 | 1.00 (6/6) |
| C: Multi-document | 6 | 3 | 0.82 | 0.93 | **0.42** | **0.64** | **0.59** | 0.83 (4/6) |
| D: Ambiguous | 5 | **0** | 0.60 | — | — | 0.40 | — | 0.71 (2/4) |
| E: Out-of-corpus | 6 | 6 | — | — | — | — | — | — (abstention 6/6) |
| F: Lexical vs semantic | 6 | 4 | 0.87 | 0.84 | 0.93 | 0.94 | 0.72 | 1.00 (6/6) |
| G: Multi-hop | 6 | 3 | 0.77 | 0.81 | 0.75 | 0.69 | 0.66 | 0.92 (5/6) |

\* Source-doc recall: the share of the item's expected source documents that appear among the 4 retrieved chunks. This is computed without an LLM judge.

**What the categories show**

- **A and B (single document):** retrieval always found the right PEP, and answers are grounded (faithfulness 0.94–1.00). The few misses are incomplete answers, not wrong ones.
- **C (multi-document):** the weakest answerable category on precision (0.42), recall (0.64) and correctness (0.59). 2 of 6 questions never retrieved one of the two PEPs they ask about.
- **D (ambiguous):** **0 of 5** clarifications. The system always either picks one interpretation (D01 answered only about PEP 649) or says the documents lack the answer (D02, D04). It never asks which PEP is meant, and the prompt has no instruction to do so.
- **E (out-of-corpus):** **6 of 6** correct abstentions. The "say when the documents do not contain the answer" instruction works.
- **F (lexical vs semantic):** dense retrieval coped with paraphrased questions (source-doc recall 1.00, context recall 0.94). The 2 failures are judge-scored answer issues, not retrieval issues (section 5).
- **G (multi-hop):** 3 of 6 pass. G02 and G03 never retrieved the second hop.

### Retrieval collapses onto one document

13 golden items need two or more source documents:

- 8 retrieved all of them.
- **5 missed one: C03, C05, D01, D03 and G02. In every one of those 5, all 4 retrieved chunks came from a single PEP.**

Overall, 16 of 42 questions received four chunks from one document. Dense similarity ranks the chunks of the single closest PEP highest. Every chunk carries its PEP title line, so chunks of the same document resemble each other.

### Measurement caveat: `evidence_in_context`

The harness also checks whether each golden evidence quote appears verbatim in the retrieved text. That check under-reports:

- The golden quotes are raw reStructuredText (` ``pyproject.toml`` `, `[5]_`).
- The chunks are rendered text (`pyproject.toml`).
- For example, A06, F01 and G04 retrieved the right passage but score 0.

This analysis therefore relies on source-doc recall and Ragas context recall. Normalising the quotes is a follow-up item for the harness. It does not change the measured system.

## 5. Failure analysis

The 15 non-passing items, with the earliest stage that failed. Triage labels come from the harness thresholds. The "verified cause" column comes from reading the retrieved chunks and answers.

| Item | Triage label | Verified cause | Earliest failing stage | Evidence |
|---|---|---|---|---|
| C03 | GENERATION_FAILURE | **Missing document.** All 4 chunks were from PEP 621 and none from PEP 518. The model correctly said PEP 518 was not covered. | Retrieval | answer correctness 0.11, source-doc recall 0.5 |
| C05 | HALLUCINATION | **Missing document, then filled from prior knowledge.** All 4 chunks were from PEP 526. The answer about PEP 484 type comments was right but unsupported by context. | Retrieval → grounding | faithfulness 0.60, source-doc recall 0.5 |
| G02 | CONTEXT_FAILURE | **Missing second hop.** All 4 chunks were from PEP 604. The PEP 484 `Optional` part was answered from prior knowledge. | Retrieval → grounding | context recall 0.00, faithfulness 0.50 |
| G03 | GENERATION_FAILURE | **Missing section.** The PEP 585 header (Python-Version 3.9) was not in the top 4, so the answer said the version was unknown. | Retrieval (within document) | answer correctness 0.41; "3.9" absent from context |
| B03 | HALLUCINATION | **Missing section.** The "Function and Variable Names" section of PEP 8 was not retrieved, so the answer gave 2 of 3 conventions and said the third was missing. | Retrieval (within document) | context recall 0.67, faithfulness 0.67 |
| D01 | AMBIGUITY | Answered about PEP 649 only, without asking. 2 of the 3 candidate PEPs were not retrieved either. | Query understanding (and retrieval) | clarification 0, source-doc recall 0.33 |
| D02 | AMBIGUITY | "When was it accepted?" has no referent. The system said the documents lack the answer instead of asking what "it" is. | Query understanding | clarification 0 |
| D03 | AMBIGUITY | Answered for PEP 621 only. PEP 518 was not retrieved. | Query understanding (and retrieval) | clarification 0, source-doc recall 0.5 |
| D04 | AMBIGUITY | "Deferred annotations proposal" fits both PEP 563 and PEP 649. It said status was unavailable because the header chunks were not retrieved. | Query understanding (and retrieval) | clarification 0 |
| D05 | AMBIGUITY | Picked one interpretation without asking | Query understanding | clarification 0 |
| A05 | GENERATION_FAILURE | The answer (`NAME := expr`) is correct but omits "assignment expression" and "walrus operator" from the ground truth. | Judge strictness / brevity | answer correctness 0.34 |
| F05 | GENERATION_FAILURE | Correct, detailed answer about `__annotate__`, just under the threshold | Judge (borderline) | answer correctness 0.49 vs threshold 0.5 |
| F04 | HALLUCINATION | The answer is correct and matches the retrieved PEP 518 chunk. The judge gave no reason. | Judge (disputed) | faithfulness 0.20, context precision 1.0, recall 0.67 |
| G01 | HALLUCINATION | Correct answer. The `Superseded-By` header and `__annotate__` are both in the context. | Judge (disputed) | faithfulness 0.33 |
| C04 | OTHER | Good answer. Faithfulness could not be scored (section 2). | — (judge limit) | context recall 0.67, answer correctness 0.70 |

**By verified cause**

| Cause | Items | Count |
|---|---|---:|
| Retrieval missed a whole document (single-document collapse) | C03, C05, G02 (+ D01, D03 inside the ambiguity failures) | 3 (+2) |
| Retrieval missed a section within the right document | G03, B03 (+ D04) | 2 (+1) |
| No clarification for ambiguous questions | D01–D05 | 5 |
| Answer correct, judge score below threshold or disputed | A05, F05, F04, G01 | 4 |
| Unscorable | C04 | 1 |

Two failures (C05, G02) show a **grounding problem caused by retrieval**: when a needed document was missing, the generator answered from its own knowledge instead of saying the context was insufficient. On the out-of-corpus questions it did abstain, so it abstains on obviously unrelated questions but not on partially covered ones.

## 6. Failure matrix

| Failure | Evidence | Root cause | Candidate technique (hypothesis) | Priority |
|---|---|---|---|---|
| Multi-document collapse | C03, C05, G02; C context precision 0.42 and recall 0.64; 5 of 13 multi-document items missed a document, all with 4 chunks from 1 PEP | One dense query embeds close to a single PEP; top-4 is filled by that PEP's chunks | **Query decomposition / multi-query retrieval** (cheaper controls: MMR diversity, larger `top_k`) | **1** |
| No clarification on ambiguous questions | D01–D05, clarification 0/5 | Nothing in the graph or prompt detects ambiguity or asks back | Query analysis, then a clarify route | 2 |
| Section-level misses inside the right PEP | G03, B03, D04: the header or a specific section is not in the top 4 | `top_k=4` with about 35 chunks per PEP; header chunks rank low for content questions | Decomposition (the sub-question names the needed fact); larger `top_k` or reranking | 3 |
| Answering from prior knowledge when context is partial | C05, G02 (faithfulness 0.60 and 0.50) | The generator fills gaps instead of saying the context is insufficient | Relevance grading / CRAG, or a stronger grounding prompt | 4 (mostly a symptom of #1) |
| Judge strictness / disputed scores | A05, F05, F04, G01 | LLM judge variance; short ground truths | No system change. Re-check the judge (or a second judge) before claiming deltas on these items | Measurement |
| Out-of-corpus questions | E01–E06 all abstain correctly | none | none: **already strong, must not regress** | — |

## 7. Conclusions

1. **Basic RAG is solid on single-document questions** (A and B: source-doc recall 1.00, faithfulness ≥ 0.94) and on **out-of-corpus abstention (6/6)**.
2. **The largest measured weakness is retrieval for questions that span documents.** Category C has precision 0.42, recall 0.64 and correctness 0.59; G has recall 0.69. The cause is verified: one query vector, with the top 4 filled by one PEP.
3. **Ambiguity handling is absent (0/5).** The failure is clear, but it involves only 5 items, and part of it is retrieval as well (D01, D03, D04).
4. **About a quarter of the "failures" (4 of 15) are judge-side.** Deltas on A05, F05, F04 and G01 must not be read as real improvements without inspection.

The Phase 3.1 choice and its design are in [PHASE-3.1-DESIGN.md](PHASE-3.1-DESIGN.md).
