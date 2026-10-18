# PHASE 1 REPORT

Basic RAG foundation for ArchAgenticRAG. Details live in [PHASE-1-IMPLEMENTATION.md](PHASE-1-IMPLEMENTATION.md), [PHASE-1-REUSE-AUDIT.md](PHASE-1-REUSE-AUDIT.md) and [PHASE-2-BASELINE-RESULTS.md](PHASE-2-BASELINE-RESULTS.md). This report summarises them.

## 1. Status

**Complete, pending architecture review.**

- Basic RAG, `START → retrieve → generate → END`, runs on the real local stack and is measured on all 42 golden questions.
- Ollama is supported in configuration but was **not exercised**: it is not installed on this machine, and at the user's direction the baseline used Groq.

| Exit criterion | State |
|---|---|
| Repository inspected; reuse audit; licence checks; THIRD_PARTY_NOTICES | ✅ |
| Basic RAG graph; `build_graph(system=...)` | ✅ |
| Docling ingestion; embeddings; Qdrant; documents indexed; retrieval | ✅ (455 chunks) |
| Local LLM (Ollama) works | ⚠️ not tested: Ollama not installed. The API provider path was used instead. |
| Genuine generated answers | ✅ 42/42 |
| Phase 2 evaluator calls the graph | ✅ |
| The original 71 Phase 2 tests still pass; Phase 1 tests pass | ✅ 123/123 offline (8 integration, 1 live when last run) |
| 42-question baseline executed | ✅ 42/42 answers. 169 of 175 metric values were scored; 6 judge-limit gaps are recorded. |
| No Agentic RAG feature implemented | ✅ |

## 2. Repository findings

Phase 1 found a directory with no git repository and no RAG code. Phase 0 research and the Phase 2 harness were present: `docs/`, `eval/`, `data/corpus/peps/`, `src/archagenticrag/evaluation/` and `tests/evaluation/`. The evaluation contract (`target.factory`, the input and output keys, `metadata["doc_id"]`), the provider presets and the pinned corpus were reused. The golden dataset, the corpus, the metric selection and the Ragas/Langfuse integration were not touched.

## 3. Reuse audit

See [PHASE-1-REUSE-AUDIT.md](PHASE-1-REUSE-AUDIT.md).

- **REUSE:** LangGraph, Docling, docutils, FastEmbed, Qdrant with `langchain-qdrant`, and `ChatOpenAI` over OpenAI-compatible APIs.
- **ADAPT (pattern only):** the official LangGraph RAG examples, and agentic-rag-for-dummies' collection guard.
- **Rejected:** `langchain-docling` (adds nothing over calling Docling directly), `rlm/rag-prompt` (unclear licence), sentence-transformers (needs torch), and hybrid or parent-child retrieval (later phases).

## 4. Licence decisions

- **Code dependencies:** all MIT, Apache-2.0 or BSD. docutils is public domain or BSD-2 for the parts used.
- **Corpus:** PEPs are public domain or CC0.
- **Model weights:** bge-small is MIT.
- **Adapted patterns:** both from MIT projects; their notices are in `THIRD_PARTY_NOTICES.md`.
- **No code was copied.**

## 5. Architecture

Offline: PEP `.rst` → docutils PEP reader (plus tree clean-up) → HTML → Docling → HybridChunker (480 tokens) → FastEmbed bge-small (384-d) → Qdrant.

Online: question → LangGraph `retrieve` (dense, k=4) → `generate` (prompt, then LLM) → answer. A diagram is in the implementation document, section 1.

## 6. Components reused

| Component | Library | Version |
|---|---|---|
| Graph orchestration | LangGraph | 1.2.12 |
| Document conversion, chunking | docling-slim, docling-core | 2.131.0, 2.99.0 |
| RST parsing | docutils | 0.23 |
| Embeddings | FastEmbed | 0.8.1 |
| Vector store | Qdrant server and client | 1.19.1, with langchain-qdrant 1.1.0 |
| LLM client | langchain-openai `ChatOpenAI` | 1.6.7 |

## 7. Components adapted

- **The LangGraph RAG example pattern** (`langgraph_crag.ipynb` @ `4be610c`): retrieve and generate nodes, with grading, rewriting and web search removed.
- **The collection guard from agentic-rag-for-dummies** (@ `2461e52`): refuse a vector-size mismatch, extended to check the embedding model and chunking settings.

## 8. New code written

- `rag/settings.py`: strict validation.
- `rag/ingestion.py`: the docutils tree transforms and chunk metadata.
- `rag/vector_store.py`: the index manifest and guard.
- `rag/ingest.py`: the CLI.
- `graphs/basic_rag.py`: the graph factory and prompt.
- `providers.py`: shared presets.
- Additive harness changes: generation latency, target metadata, latency percentiles, resume.

## 9. Qdrant

- Docker image `qdrant/qdrant:v1.19.1` (`docker compose up -d qdrant`).
- Collection `peps_v1_bge_small_docling_480`: 455 points, 384-d cosine.
- The index manifest (model, chunking, corpus hash, versions) is stored as collection metadata.
- `open_store` refuses a missing, empty or mismatched index.

## 10. Embeddings

- `BAAI/bge-small-en-v1.5` through FastEmbed, as ONNX on CPU (`Qdrant/bge-small-en-v1.5-onnx-Q` @ `aa8f8b0`).
- No key, no server, no torch.
- The dimension is checked against the config and the collection.

## 11. Ollama / LLM

- One `ChatOpenAI` client covers Ollama (`http://localhost:11434/v1`), Groq, Gemini, OpenRouter, NVIDIA, xAI and OpenAI.
- The baseline generator is Groq `openai/gpt-oss-120b` at temperature 0.
- **The Ollama path is untested** because Ollama is not installed.
- An OpenRouter key was smoke-tested in a separate project and is not integrated.

## 12. Basic RAG graph

- **State:** `question`, `documents`, `context`, `answer`.
- **retrieve:** `retriever.invoke` with `RunnableConfig` passed through, so the evaluator's callbacks fire.
- **generate:** `ChatPromptTemplate | llm | StrOutputParser`. The prompt says to answer only from the numbered context, not invent facts, say when the documents do not contain the answer, and be concise.
- The compiled graph carries `eval_metadata`, which holds the index and the prompt.

## 13. Tests

123 offline tests pass:

- Phase 2 harness, including resume (8 tests) and early stop.
- settings, ingestion, vector store (in-memory Qdrant) and graph contract (fake LLM).

Also:

- 8 integration tests with real Docling, FastEmbed and Qdrant: known questions retrieve the right PEP.
- 1 live test: A01 through the evaluator.

## 14. Phase 2 integration

The evaluator was not redesigned. Changes were additive:

- generation timing;
- target metadata in the manifest;
- latency percentiles;
- resumable runs (`eval/runners/resume_eval.py`), needed because of free-tier judge quotas;
- `answer_correctness` switched to a question-aware Ragas `AnswerCorrectness` after `FactualCorrectness` scored correct short answers 0 (ADR 008, Amendment 1).

## 15. Baseline results

| Metric | Value |
|---|---|
| Faithfulness | 0.847 (n=34) |
| Answer relevancy | 0.887 (n=30) |
| Context precision | 0.756 (n=29) |
| Context recall | 0.783 (n=35) |
| Answer correctness | 0.724 (n=30) |
| Abstention | 1.00 (6/6) |
| Clarification | 0.00 (0/5) |
| Pass rate | 27/42 |
| Latency p50 / p95 | 6.9 s / 20.1 s (retrieval p50 22 ms) |
| Generator tokens | 45,018 in, 9,174 out |
| Cost | null |

Full tables are in the results report.

## 16. Failure analysis

Of the 15 non-passing items:

| Failure | Items |
|---|---|
| Retrieval missed a whole document | C03, C05, G02 |
| Retrieval missed a section | G03, B03 |
| No clarification | D01–D05 |
| Judge-side (answer correct, score low or disputed) | A05, F05, F04, G01 |
| Unscorable | C04 |

C05 and G02 also answered from prior knowledge when context was partial. Details are in the results report, section 5.

## 17. Category analysis

| Category | Pass | Observed pattern | Candidate technique |
|---|---|---|---|
| A: Direct factual | 6/7 | Strong: right document, grounded answers | none |
| B: Multi-sentence | 5/6 | Strong. One section-level miss (B03). | none / wider retrieval |
| C: Multi-document | 3/6 | Precision 0.42, recall 0.64. Four chunks from one PEP. | decomposition |
| D: Ambiguous | 0/5 | Never asks for clarification | clarify / routing |
| E: Out-of-corpus | 6/6 | Correct abstention every time | none: must not regress |
| F: Lexical vs semantic | 4/6 | Dense retrieval handles paraphrase (recall 0.94); failures are judge-side | none |
| G: Multi-hop | 3/6 | Second hop not retrieved (G02, G03) | decomposition / iterative retrieval |

These are candidates only.

## 18. Problems discovered

1. Docling has no reStructuredText backend; docutils was added in front of it.
2. Docling treats content before the first heading as furniture, which dropped the PEP headers; fixed with an `<h1>` title.
3. Inline links fragmented the chunks.
4. Windows CRLF line endings would have broken the corpus hashes.
5. Ragas `FactualCorrectness` ignores the question, so correct terse answers scored 0.
6. Free-tier limits:
   - Gemini: 5 requests/minute.
   - NVIDIA NIM: timeouts and 404s.
   - Groq: 200,000 tokens/day, plus an intermittent 1,000 output-tokens/minute limit that rejects Ragas' 1,024-token requests.
7. The first resume tool waited out the daily quota inside an item (fixed in `f96c37c`).
8. `evidence_in_context` under-reports because the golden quotes are raw reStructuredText.
9. Footnote references survive as `[[5]](#toml)` in some chunks.

## 19. Known limitations

- Ollama is untested.
- Latency includes free-tier queueing.
- Judge tokens are not captured.
- 6 metric values could not be scored.
- Judge variance affects about 4 items.
- `top_k` and chunk size are not tuned.
- Retrieval is dense only.
- The generator adds `【n†Lx】` citation markers.
- The run's start commit was dirty: the metric change was in the working tree, and it was recorded in ADR 008.

## 20. Recommended Phase 3 experiments

1. **Phase 3.1: query decomposition with parallel per-sub-question retrieval**, against controls B1 (`top_k=8`) and B2 (MMR). Design: [PHASE-3.1-DESIGN.md](PHASE-3.1-DESIGN.md).
2. **Phase 3.2 candidate:** query analysis with a clarify route for ambiguous questions.
3. **Later, evidence permitting:** iterative multi-hop retrieval; relevance grading or CRAG for answers made from partial context.

## 21. Exact reproduction commands

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[eval]" pytest pytest-asyncio
cp .env.example .env                       # add GROQ_API_KEY and GEMINI_API_KEY (never commit .env)
docker compose up -d qdrant
.venv/Scripts/python -m archagenticrag.rag.ingest eval/configs/baseline-basic-rag.yaml
.venv/Scripts/python -m pytest                          # offline
.venv/Scripts/python -m pytest -m integration           # needs Qdrant
.venv/Scripts/python eval/runners/validate_dataset.py eval/datasets/peps-v1/golden.json
.venv/Scripts/python eval/runners/run_eval.py eval/configs/baseline-basic-rag.yaml
.venv/Scripts/python eval/runners/resume_eval.py eval/results/<run_id>   # repeat after quota resets
```
