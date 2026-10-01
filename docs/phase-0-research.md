# ArchAgenticRAG — Phase 0: Ecosystem Research & Architecture

Status date: 2026-10-01. Metadata (stars, forks, last push, license) pulled from the GitHub REST API on that date.

**Evidence levels used below**

- **[SRC]** — repository was cloned and source code read (graph wiring, nodes, dependencies, tests, Docker, license file).
- **[LIC]** — license file read directly (not just the GitHub SPDX badge).
- **[META]** — metadata + README/known architecture only; no source audit in this phase.

No test suites were executed in Phase 0. "Has tests" means test files exist and were inspected, not that they pass.

---

## 1. Executive Summary

**Core decision:** build ArchAgenticRAG as a thin composition layer over **LangGraph** (orchestration), **Qdrant** (vector store with native hybrid search), **Docling** (ingestion), **Ragas** (evaluation) and **Langfuse** (tracing). Write only glue code, graphs and prompts. Do not write a framework.

**Starting-point code to adapt:** `GiovanniPasq/agentic-rag-for-dummies` (MIT) and the official `langchain-ai/langgraph` `examples/rag/*` notebooks (MIT). These two sources already cover most of the agentic patterns you want to learn, on modern LangGraph 1.x, under a clean license.

**Verdict on the three starting repositories:**

| Repo | Verdict | One-line reason |
|---|---|---|
| Grecil/Corrective-RAG | **REJECT** (for reuse) / REFERENCE (for reading) | No LICENSE file, so no reuse rights. ~280 LOC that closely follows the LangGraph CRAG tutorial. It drops the paper's "ambiguous" branch and has no tests. |
| backblaze-b2-samples/agentic-rag-vector-starter-kit | **REFERENCE** + selective **ADAPT** | MIT, good engineering discipline (layered architecture enforced by tests, 17 test files, RRF + cross-encoder). The pipeline is hand-rolled rather than graph-based, it is tied to B2, it has 2 stars, and its "RAGAS evaluation" is custom prompts, not the ragas library. |
| NirDiamant/Controllable-RAG-Agent | **REFERENCE** | Apache-2.0, a strong demonstration of plan → execute → replan with hallucination checks. Pinned to `langgraph==0.0.49` and ragas 0.1.7, hard-coded `gpt-4o`, ships pickled FAISS indexes, Harry Potter-specific, no tests. Study the design; don't port the code. |

**Licensing traps to avoid** (details in §6): everything under NirDiamant's `RAG_Techniques`, `GenAI_Agents` and `agents-towards-production` uses a custom **non-commercial** license. `langchain-ai/rag-from-scratch` and the official CRAG paper code have **no license**. Arize Phoenix is **Elastic License 2.0**. Open WebUI has a **branding-retention clause**. SearXNG is **AGPL-3.0**.

---

## 2. Agentic RAG Ecosystem Map

```
                         ┌──────────────────────── EVALUATION ─────────────────────────┐
                         │ Ragas (Apache) · DeepEval (Apache) · TruLens (MIT) · FlashRAG│
                         └──────────────────────────────────────────────────────────────┘
┌─────────── INGESTION ───────────┐   ┌──────────── RETRIEVAL ────────────┐   ┌──────── GENERATION / AGENT ─────────┐
│ Docling (MIT)                   │   │ Vector DB: Qdrant · pgvector ·    │   │ Orchestration: LangGraph (MIT)      │
│ Unstructured (Apache)           │──▶│   Chroma · LanceDB                │──▶│ Patterns: CRAG · Self-RAG ·         │
│ PyMuPDF4LLM                     │   │ Embeddings: FastEmbed · ST · BGE  │   │   Adaptive RAG · Plan-and-Execute  │
│ Chunking: LC text-splitters,    │   │ Hybrid: BM25/sparse + dense + RRF │   │ Tools: LangChain tools · MCP        │
│   Docling HybridChunker         │   │ Rerank: rerankers · bge-reranker  │   │ Web: Tavily · DuckDuckGo · SearXNG  │
└─────────────────────────────────┘   └───────────────────────────────────┘   │ Multi-agent: LangGraph subgraphs,   │
                                                                              │   Send (map-reduce), supervisor     │
                                                                              └─────────────────────────────────────┘
┌──────── OBSERVABILITY ────────┐   ┌──────────── SERVING / UI ─────────────┐   ┌────── FULL PLATFORMS (reference) ──────┐
│ Langfuse (MIT core)           │   │ FastAPI · LangGraph server             │   │ RAGFlow · Kotaemon · R2R · LightRAG ·  │
│ Phoenix (ELv2) · LangSmith    │   │ Streamlit · Gradio · Chainlit          │   │ GraphRAG · Haystack · LlamaIndex       │
│ OpenTelemetry                 │   │ agent-chat-ui (Next.js) · Open WebUI   │   │ (whole products; too big to compose)   │
└───────────────────────────────┘   └────────────────────────────────────────┘   └─────────────────────────────────────────┘

LEARNING-ONLY SOURCES: rag-from-scratch (no license) · NirDiamant RAG_Techniques/GenAI_Agents (non-commercial)
                       · AgenticRAG-Survey (no license, paper index) · self-rag & CRAG paper repos
```

### Pattern → canonical implementation

| Pattern | Paper | Best readable implementation | License |
|---|---|---|---|
| Corrective RAG (CRAG) | arXiv 2401.15884 | `langgraph/examples/rag/langgraph_crag.ipynb` (+ `_local`) | MIT |
| Self-RAG | arXiv 2310.11511 | `langgraph/examples/rag/langgraph_self_rag.ipynb` (LLM-as-grader version) | MIT |
| Adaptive RAG (routing) | arXiv 2403.14403 | `langgraph/examples/rag/langgraph_adaptive_rag.ipynb` | MIT |
| Agentic RAG (tool-calling retriever) | — | `langgraph/examples/rag/langgraph_agentic_rag.ipynb`; `agentic-rag-for-dummies` | MIT |
| Plan-and-execute / replan | Plan-and-Solve | `Controllable-RAG-Agent` (read only, outdated API) | Apache-2.0 |
| Query decomposition + map-reduce | — | `agentic-rag-for-dummies` (`Send` fan-out, `aggregate_answers`) | MIT |
| Human-in-the-loop clarification | — | `agentic-rag-for-dummies` (`interrupt_before=["request_clarification"]`) | MIT |
| Self-RAG with trained reflection tokens | arXiv 2310.11511 | `AkariAsai/self-rag` (needs fine-tuned Llama; research only) | MIT |
| Many RAG methods, benchmarked | — | `RUC-NLPIR/FlashRAG` | MIT |

---

## 3. Repository Comparison

### 3a. Deep audits [SRC]

#### Grecil/Corrective-RAG — REJECT (reuse) / REFERENCE (learning)

| Field | Finding |
|---|---|
| URL | https://github.com/Grecil/Corrective-RAG |
| License | **None.** There is no LICENSE file, so default copyright applies and you have no right to copy the code. |
| Stars / forks / last push | 30 / 8 / 2026-05-13 |
| Stack | Python 3.10, LangGraph, LangChain, Gemini (`gemini-3-flash-preview`), Gemini embeddings, FAISS, DuckDuckGo, Streamlit |
| Size | 281 LOC total across `graph.py`, `nodes/`, `tools/`, `models/` |
| Architecture | Linear graph: `retrieve → grade_documents → (generate \| transform_query → web_search → generate)`. `GraphState` = question/generation/web_search/documents. |
| Fidelity to paper | Partial. The paper has three outcomes (Correct / Incorrect / **Ambiguous**) plus a knowledge-refinement step (decompose, then recompose into strips). This repo has a binary per-document yes/no grade: if any single document is graded irrelevant, it goes to web search. No refinement step and no retry loop. |
| Code quality | Readable and very small. The grader prompt says *"if the document contains keywords related to the question, grade it as relevant"*, which is a weak criterion. JSON parsing has no fallback. The LLM is instantiated at import time. |
| Tests | None |
| Docker | Yes: a single Dockerfile for Streamlit, plus a devcontainer |
| Dependencies | Unpinned (`langchain`, `langgraph`, … with no versions), and it includes the deprecated `langchainhub`. Reproducibility risk. |
| Docs | Short README. The README says gemini-1.5-flash while the code uses gemini-3-flash-preview (drift). |
| Learning value | Medium. It is the CRAG tutorial split into files. The original LangGraph notebook teaches the same material with a license. |
| Reuse value | **Zero** (no license). |

#### backblaze-b2-samples/agentic-rag-vector-starter-kit — REFERENCE + selective ADAPT

| Field | Finding |
|---|---|
| URL | https://github.com/backblaze-b2-samples/agentic-rag-vector-starter-kit |
| License | MIT (© 2026 Backblaze, Inc.) [LIC] |
| Stars / forks / last push | 2 / 1 / 2026-09-11. Very low adoption; vendor sample. |
| Stack | Monorepo: Next.js 16 + React 19 + Tailwind v4 + shadcn/ui (`apps/web`), FastAPI + Pydantic (`services/api`), LanceDB on B2/S3, LangChain (OpenAI/Anthropic), sentence-transformers cross-encoder, pnpm |
| Size | ~5.9k LOC Python backend plus a sizeable TS frontend |
| Architecture | Strict layering `types → config → repo → service → runtime`, **enforced by an AST-based structural test** (`tests/test_structure.py`). SDKs (`boto3`, `lancedb`, `langchain*`) are confined to `repo/`. 300-line file limit. AGENTS.md / ARCHITECTURE.md / exec-plans docs. |
| Retrieval pipeline | `service/retrieval.py`: a single LLM call does intent routing and multi-query planning (up to 4 variants). Then batch embedding, vector or hybrid (BM25 via tantivy + dense) search, a hand-written RRF (k=60), a cross-encoder rerank (`ms-marco-MiniLM-L-6-v2`), and one LLM call for combined CRAG grade + sufficiency, with at most 2 retrieval loops. |
| CRAG | Three grades (correct/ambiguous/wrong); "wrong" strips evidence. **No web-search fallback.** On "wrong" it falls back to the LLM's general knowledge. |
| Orchestration | **Not LangGraph.** A Python generator yields step events. Easy to follow, but not a graph and has no checkpointing. |
| Evaluation | README says "RAGAS evaluation", but `service/eval_metrics.py` is *"RAGAS-inspired"*: two custom LLM-judge prompts. The ragas library is not imported. |
| Tests | 17 pytest files (chat, retrieval, chunker, pipeline, structure, error handling…), plus a Playwright e2e spec for upload. Not executed in Phase 0. |
| Docker | **No** Dockerfile or compose. Deployment is documented for Railway. |
| Dependencies | `>=` ranges (not locked for Python), B2 credentials required to run |
| Learning value | High for **engineering practice**: layering, structural tests, graceful degradation, a pipeline-step UI, a dashboard. Medium for agentic patterns. |
| Reuse value | Medium. Ideas and some UI components (pipeline-steps, citation panel) can be adapted with an MIT attribution notice. The backend is too coupled to B2/LanceDB to lift wholesale. |

#### NirDiamant/Controllable-RAG-Agent — REFERENCE

| Field | Finding |
|---|---|
| URL | https://github.com/NirDiamant/Controllable-RAG-Agent |
| License | Apache-2.0 [LIC]. This differs from the author's other repos, which are non-commercial. |
| Stars / forks / last push | 1,625 / 268 / 2026-09-21 |
| Stack | LangGraph **0.0.49** (pinned, 2024-era API), LangChain, OpenAI `gpt-4o` hard-coded in ~12 places, FAISS, Streamlit, ragas 0.1.7, Groq (commented out) |
| Size | 1,665 LOC across 3 .py files (`functions_for_pipeline.py` alone is 1,182 lines) plus notebooks |
| Architecture | Plan-and-execute agent: anonymize question → plan → break plan into retrieval/answer tasks → task handler → three retrieval subgraphs (chunks / chapter summaries / book quotes), each with a "keep only relevant content" filter and a distillation grounding check → answer with CoT → hallucination check → replan loop → de-anonymize. |
| Key ideas worth learning | (1) **Question anonymization** before planning, so the planner can't answer from prior knowledge. (2) **Multi-granularity indexes** (chunks, summaries, quotes). (3) **Grounding checks at two levels** (distilled content vs. retrieved content, answer vs. context). (4) **Replanning** driven by "can it be answered already?" |
| Code quality | Notebook-to-script style: global chains, duplicated prompt and LLM construction, no config layer. Loads FAISS `index.pkl` files, and pickle deserialization of untrusted files is a code-execution risk. |
| Tests | None |
| Docker | Dockerfile + docker-compose (Streamlit) |
| Dependencies | ~200 pins including Jupyter/Bokeh/OpenTelemetry noise. Pins are 2024 versions, so expect breakage on a modern Python/LangGraph stack. |
| Learning value | **High** for plan/execute/replan and hallucination control. |
| Reuse value | Low. Porting it to LangGraph 1.x costs more than re-expressing the design in your own graph. |

#### GiovanniPasq/agentic-rag-for-dummies — ADAPT (recommended base)

| Field | Finding |
|---|---|
| URL | https://github.com/GiovanniPasq/agentic-rag-for-dummies |
| License | MIT (© 2025 Giovanni Pasqualino) [LIC] |
| Stars / forks / last push | 4,220 / — / 2026-08-30 |
| Stack | **LangGraph 1.2.11**, Qdrant (`langchain-qdrant`) + FastEmbed sparse (hybrid), Ollama / HuggingFace, PyMuPDF4LLM (PDF→Markdown), **Langfuse 4.x**, **Ragas 0.4.3**, Gradio 6, Dockerfile |
| Size | ~2.1k LOC in `project/`, plus notebooks (`agentic_rag`, `evaluation`, `observability`, `pdf_to_markdown`) |
| Architecture | Two-level graph. Main graph: `summarize_history → rewrite_query → (request_clarification [HITL interrupt] \| agent subgraph ×N via fan-out) → aggregate_answers`. Agent subgraph: `orchestrator (LLM with tools) ⇄ ToolNode → should_compress_context → compress_context`, with a `fallback_response`. Parent–child chunk store. `InMemorySaver` checkpointer. |
| Covers | Query rewriting, clarification (HITL), query decomposition + parallel sub-agents, tool-calling retrieval, context compression, hybrid search, parent-document retrieval, tracing, Ragas eval |
| Missing | Explicit CRAG relevance grading node, web-search fallback, Self-RAG hallucination/answer graders, routing to non-KB sources, API backend, tests |
| Tests | **None** (notebook-based evaluation only) |
| Learning value | **High.** Modern idioms (`Command`, `Send`, subgraphs, interrupts). |
| Reuse value | **High** as a skeleton to fork, rename and extend. Keep the MIT notice. |

#### langchain-ai/langgraph `examples/rag/` — ADAPT

| Field | Finding |
|---|---|
| URL | https://github.com/langchain-ai/langgraph/tree/main/examples/rag |
| License | MIT |
| Stars / last push | 42.5k / 2026-10-01 (CRAG notebook last touched 2026-01-26) |
| Contents | `langgraph_crag(_local)`, `langgraph_self_rag(_local, _pinecone_movies)`, `langgraph_adaptive_rag(_local, _cohere)`, `langgraph_agentic_rag` |
| Why | These are the canonical, framework-maintainer implementations of exactly the patterns in the learning path, each in about one page. `_local` variants run on Ollama, so no API costs. |
| Caveat | They are notebooks, not packages. Some use Tavily (an API key with a free tier). Extract the nodes into modules. |

### 3b. Ecosystem candidates [META unless marked]

| Repo | License | ★ | Last push | Lang | Role | Decision | Why |
|---|---|---|---|---|---|---|---|
| langchain-ai/langgraph | MIT | 42.5k | 2026-10-01 | Py | Orchestration | **REUSE** | Industry default for cyclic, stateful agent graphs. Checkpointing, interrupts, subgraphs, `Send`. |
| langchain-ai/langchain | MIT | 147k | 2026-09-30 | Py | Integrations (loaders, splitters, retrievers, tools) | **REUSE** (integration packages only) | Use `langchain-core` plus specific integrations. Avoid legacy chains. |
| docling-project/docling | MIT | 68.2k | 2026-09-30 | Py | PDF/DOCX/PPTX/HTML parsing, layout, tables, `HybridChunker` | **REUSE** | Best OSS document parser right now. LangChain + LlamaIndex integrations exist. |
| Unstructured-IO/unstructured | Apache-2.0 | 15.5k | 2026-09-30 | Py | Parsing | REFERENCE (alternative) | Heavier system dependencies. Docling is enough. |
| qdrant/qdrant | Apache-2.0 | 34.9k | 2026-09-30 | Rust | Vector DB | **REUSE** | Native dense + sparse hybrid, payload filters, one Docker container, good LangChain integration, used by the ADAPT base. |
| pgvector/pgvector | PostgreSQL (permissive) | 23.2k | 2026-09-30 | C | Vector in Postgres | COMPOSE (optional, Phase 9) | Use this if you want one DB for app state + vectors in production. |
| chroma-core/chroma | Apache-2.0 | 29.4k | 2026-10-01 | Rust/Py | Embedded vector DB | REFERENCE | Fine for a 10-minute demo. Qdrant covers everything Chroma does and adds hybrid search. |
| FlagOpen/FlagEmbedding | MIT | 12.2k | 2026-08-24 | Py | BGE-M3 embeddings, bge-reranker | **REUSE** (models) | Strong multilingual dense/sparse and rerankers. Check each model card's license. |
| AnswerDotAI/rerankers | Apache-2.0 | 1.6k | 2025-12-20 | Py | Unified reranker API | COMPOSE | One interface for cross-encoders, ColBERT, API rerankers. Activity is slowing, so `sentence-transformers.CrossEncoder` is the fallback. |
| vibrantlabsai/ragas (formerly explodinggradients/ragas) | Apache-2.0 | 15.9k | **2026-02-24** | Py | RAG metrics | **REUSE** | De-facto RAG metric set (faithfulness, context precision/recall, answer relevancy). **Risk:** the repo moved orgs and the last push was over 7 months ago. Pin the version and keep DeepEval as a hedge. |
| confident-ai/deepeval | Apache-2.0 | 18.5k | 2026-09-29 | Py | Pytest-style LLM evals | COMPOSE | CI-friendly assertions (`assert_test`). Use for regression gates. |
| truera/trulens | MIT | 3.6k | 2026-09-30 | Py | RAG triad evals | REFERENCE | Overlaps with Ragas. |
| RUC-NLPIR/FlashRAG | MIT | 3.6k | 2026-10-01 | Py | Research toolkit, 15+ RAG methods, benchmarks | REFERENCE / COMPOSE (benchmarks) | Use its datasets and method catalog to compare your variants. Too research-oriented to embed. |
| langfuse/langfuse | MIT core + `ee/` commercial [LIC] | 35.2k | 2026-09-30 | TS | Tracing, prompt mgmt, eval datasets | **REUSE** (self-host via Docker) | Native LangGraph/LangChain callback, used by the ADAPT base. Don't touch `ee/` features. |
| Arize-ai/phoenix | **Elastic License 2.0** [LIC] | 11.7k | 2026-10-01 | Py | Tracing + evals | REFERENCE | Fine for local use. ELv2 forbids offering it as a hosted service and is not OSI-open. Langfuse covers the same need. |
| LangSmith | Proprietary SaaS | — | — | — | Tracing | Optional | Zero-config with LangGraph. Not open source. |
| langchain-ai/agent-chat-ui | MIT | 3.2k | 2026-09-28 | TS | Next.js chat UI for LangGraph servers | **COMPOSE** (Phase 9) | Speaks the LangGraph server protocol out of the box (streaming, interrupts, tool calls). |
| Chainlit/chainlit | Apache-2.0 | 12.5k | 2026-09-18 | Py | Python chat UI with step visualization | COMPOSE (Phases 1–8) | Shows intermediate steps natively, which is good for learning. Gradio (from the ADAPT base) is also fine. |
| open-webui/open-webui | **Custom (BSD + branding clause)** [LIC] | 154k | 2026-10-01 | Py/Svelte | Full chat platform | REJECT (as embedded UI) | Branding must be retained. Fine to *run* as an external client, but don't fork or rebrand it. |
| infiniflow/ragflow | Apache-2.0 | 91.6k | 2026-09-30 | Go/Py | Full RAG product (DeepDoc parser, agent canvas) | REFERENCE | A whole product. Study DeepDoc and template chunking. Composing it means running their entire stack. |
| Cinnamon/kotaemon | Apache-2.0 | 25.8k | 2026-07-14 | Py | RAG UI product | REFERENCE | Good UX ideas (citation viewer). Gradio-bound. |
| SciPhi-AI/R2R | MIT | 8.0k | **2025-11-07** | Py | RAG API server | REJECT | Activity has stalled for 11 months. |
| HKUDS/LightRAG | MIT | 39.9k | 2026-09-30 | Py | Graph + vector RAG | REFERENCE (stretch, Phase 8+) | Lightweight GraphRAG alternative. Optional extension. |
| microsoft/graphrag | MIT | 36.2k | 2026-09-28 | Py | Knowledge-graph RAG | REFERENCE | Expensive indexing. Out of scope for the core path. |
| deepset-ai/haystack | Apache-2.0 | 26.6k | 2026-09-30 | Py | Pipeline framework | REFERENCE | Excellent, but it is a competing orchestration framework. Using two frameworks doubles the learning load. |
| run-llama/llama_index | MIT | 52.4k | 2026-09-29 | Py | Data framework + Workflows | REFERENCE | Same reason. Learn its ingestion and indexing ideas, don't compose it. |
| crewAIInc/crewAI, openai/openai-agents-python, pydantic/pydantic-ai | MIT | 59k / 30k / 20k | 2026-10-01 | Py | Agent frameworks | REFERENCE | Compare their multi-agent abstractions in Phase 7. Don't mix them into the runtime. |
| langchain-ai/open_deep_research | MIT | 12.7k | archived | Py | Multi-agent research (supervisor + researchers) | REFERENCE / ADAPT (patterns) | Best LangGraph multi-agent reference. Archived, so copy patterns, not dependencies. |
| langchain-ai/rag-research-agent-template | MIT | 313 | archived | Py | LangGraph RAG template | REFERENCE | Archived. Superseded. |
| weaviate/Verba | BSD-3 | 7.7k | archived | Py | RAG app | REJECT | Archived. |
| searxng/searxng | **AGPL-3.0** | 37.8k | 2026-09-30 | Py | Self-hosted meta-search | COMPOSE (as a separate container only) | Fine to call over HTTP. Don't vendor or modify it. |
| Tavily (langchain-tavily) | Commercial API, MIT client | — | — | — | Web search tuned for LLMs | **COMPOSE** | Used by the LangGraph CRAG examples. Free tier. DuckDuckGo (`ddgs`) is the no-key fallback. |
| langchain-ai/rag-from-scratch | **None** | 9.4k | 2025-06-26 | Notebooks | RAG fundamentals course | REFERENCE only | Best basic-RAG learning material. No license, so don't copy code. |
| NirDiamant/RAG_Techniques | **Custom non-commercial** [LIC] | 29.6k | 2026-09-21 | Notebooks | 30+ RAG technique notebooks | REFERENCE only | Excellent catalog. License forbids commercial use and is not OSI. Never copy into the repo. |
| NirDiamant/GenAI_Agents, agents-towards-production | **Custom non-commercial** [LIC] | 24.4k / 21.5k | 2026-09 | Notebooks | Agent tutorials | REFERENCE only | Same license. |
| HuskyInSalt/CRAG | **None** | 474 | 2024-10-08 | Py | Official CRAG paper code | REFERENCE | Read for the T5 evaluator + decompose-recompose. No license. |
| AkariAsai/self-rag | MIT | 2.4k | 2024-05-25 | Py | Official Self-RAG (trained reflection tokens) | REFERENCE | Needs a fine-tuned Llama-2 checkpoint. Use the LLM-as-grader approximation instead. |
| asinghcsu/AgenticRAG-Survey | None | 1.7k | 2025-10-20 | — | Survey + taxonomy | REFERENCE | Reading list. |

---

## 4. REUSE Matrix

| Capability | Best Existing Project | Decision | Reason |
|---|---|---|---|
| Ingestion | Docling (`DocumentConverter`, `langchain-docling`) | **REUSE** | Handles PDF layout, tables, OCR and DOCX/PPTX/HTML. Covers what Grecil's PyMuPDF and the ADAPT base's PyMuPDF4LLM do, with better structure. |
| Chunking | Docling `HybridChunker`; `langchain-text-splitters`; parent–child pattern from agentic-rag-for-dummies | **REUSE** + ADAPT | Structure-aware chunks plus parent-document retrieval. No custom splitter needed. |
| Embeddings | FastEmbed / sentence-transformers with BGE-M3 (FlagEmbedding) or Ollama `nomic-embed-text`; OpenAI optional | **REUSE** | Local, free, and dense + sparse in one model. Swappable via LangChain `Embeddings`. |
| Vector database | Qdrant (Docker) via `langchain-qdrant` | **REUSE** | Native hybrid search + RRF, filters, snapshots. Used by the ADAPT base. |
| Retrieval | `QdrantVectorStore` hybrid mode + `ParentDocumentRetriever` pattern | **REUSE** | Qdrant does fusion server-side, so the hand-written RRF from the Backblaze kit is unnecessary. |
| Reranking | `rerankers` or `sentence-transformers.CrossEncoder` with `BAAI/bge-reranker-v2-m3` or `ms-marco-MiniLM-L-6-v2` | **COMPOSE** | Drop-in node after retrieval. The Backblaze kit shows the latency rationale (~100–200 ms per 20 candidates vs. LLM grading). |
| Query rewriting | `rewrite_query` from agentic-rag-for-dummies; `transform_query` from LangGraph CRAG; multi-query / HyDE patterns | **ADAPT** | A prompt plus structured output. Copy, then tune. |
| Relevance grading | `grade_documents` from `langgraph_crag.ipynb` with structured output | **ADAPT** | Canonical. Upgrade it to the 3-way correct/ambiguous/wrong grade (the Backblaze kit's `crag.py` grade prompt is MIT and can be borrowed). |
| Corrective RAG | `langgraph_crag.ipynb` (control flow) + Backblaze `crag.py` (3-way grade) + paper (refinement) | **ADAPT** | Combine the flow, the grading and the missing "ambiguous → retrieve + web" branch. |
| Routing | `langgraph_adaptive_rag.ipynb` router (vectorstore / web / direct) | **ADAPT** | Canonical adaptive-RAG router. The Backblaze single-call intent+plan is a cost-optimized variant to study. |
| Reflection | `langgraph_self_rag.ipynb` hallucination + answer graders; Controllable-RAG grounding checks (design) | **ADAPT** | LLM-as-grader Self-RAG. The trained-token Self-RAG repo is for reading only. |
| Web search | Tavily (`langchain-tavily`) primary; `ddgs` fallback; SearXNG optional container | **COMPOSE** | Standard tools. Nothing to build. |
| Tool calling | LangChain `@tool` + `bind_tools` + LangGraph `ToolNode`; `langchain-mcp-adapters` for MCP tools | **REUSE** | Framework-native. |
| Agent orchestration | LangGraph `StateGraph`, `Command`, checkpointer, `interrupt` | **REUSE** | Core runtime. |
| Multi-agent | LangGraph subgraphs + `Send` (from agentic-rag-for-dummies); supervisor pattern from open_deep_research | **ADAPT** | Patterns exist and are proven. Copy their structure. |
| Evaluation | Ragas (metrics) + DeepEval (CI gates) + FlashRAG/BEIR-style datasets | **REUSE** | Do not write custom judge prompts the way the Backblaze kit did. |
| Tracing | Langfuse `CallbackHandler` | **REUSE** | One line to attach to a LangGraph invoke. |
| Observability | Langfuse self-hosted (docker compose) + OpenTelemetry; structured JSON logs (idea from the Backblaze kit) | **REUSE** | Covers traces, costs, prompt versions and eval scores in one tool. |
| Frontend | Phases 1–8: Chainlit (or Gradio from the ADAPT base). Phase 9: `agent-chat-ui` | **COMPOSE** | Zero UI code early on; a production-grade Next.js UI later. |
| Backend | Phase 9: FastAPI wrapping compiled graphs (layering idea from the Backblaze kit), or the LangGraph dev server (verify server license before production use) | **COMPOSE** | A thin HTTP layer. Streaming via `graph.astream_events`. |

---

## 5. Architecture Recommendations

### Target architecture (what we compose)

```
            ┌──────────── UI: Chainlit → agent-chat-ui ─────────────┐
            └──────────────────────────┬────────────────────────────┘
                                       │ HTTP / SSE
            ┌──────────────── FastAPI (thin) ────────────────────────┐
            │  /ingest   /chat (stream)   /eval   /health            │
            └───────┬───────────────────┬──────────────────────────┬─┘
                    │                   │                          │
     ┌──────────────▼───┐  ┌────────────▼─────────────────────┐  ┌─▼──────────────┐
     │ Ingestion        │  │ LangGraph "brain"                │  │ Eval harness   │
     │ Docling →        │  │  router ─┬─ vectorstore path     │  │ Ragas +        │
     │ HybridChunker →  │  │          │   retrieve → rerank → │  │ DeepEval       │
     │ embed (BGE/      │  │          │   grade (CRAG 3-way)  │  │ golden set     │
     │ FastEmbed) →     │  │          │   ├ rewrite → retry   │  └────────────────┘
     │ Qdrant upsert    │  │          │   └ web search        │
     └──────────────────┘  │          ├─ web path (Tavily)    │
                           │          └─ direct answer        │
                           │  generate → reflect (hallucination│
                           │  + answer graders) → loop / END   │
                           │  multi-agent: planner → Send(sub- │
                           │  agents) → aggregate              │
                           └───────────────┬──────────────────┘
                                           │ callbacks
                                  ┌────────▼────────┐
                                  │ Langfuse (Docker)│
                                  └─────────────────┘
          Infra (docker compose): qdrant · langfuse(+postgres, clickhouse) · ollama (optional) · api · ui
```

### Principles

1. **One orchestration framework.** Use LangGraph only. Do not mix in Haystack, LlamaIndex Workflows or CrewAI at runtime.
2. **Fork, then strip.** Start from `agentic-rag-for-dummies`, keep the MIT notice, and port the four LangGraph example graphs in as separate, swappable graph modules.
3. **Each pattern is its own graph module** (`graphs/basic.py`, `crag.py`, `self_rag.py`, `adaptive.py`, `agentic.py`, `multi_agent.py`) with a shared state schema and shared node library. This lets you A/B test patterns on the same eval set, which is the main portfolio story.
4. **Model-agnostic via LangChain chat model interfaces.** Ollama for free local runs, Claude/OpenAI for quality runs. Config-driven; never hard-code a model (the anti-pattern seen in Controllable-RAG-Agent).
5. **Borrow the Backblaze kit's engineering discipline** (layered packages, an AST structural test, a file size cap, an AGENTS.md knowledge base, graceful degradation per node), not its pipeline code.
6. **Evaluation from Phase 1.** Every pattern ships with Ragas numbers on the same golden set. That comparison table is what makes the portfolio project credible.
7. **No pickle indexes in the repo.** Persist in Qdrant and rebuild from source documents.

---

## 6. License Analysis

### Do NOT copy code from

| Repo | License | Problem | Allowed use |
|---|---|---|---|
| Grecil/Corrective-RAG | None | All rights reserved by default | Read only |
| langchain-ai/rag-from-scratch | None | All rights reserved by default | Watch/read only |
| HuskyInSalt/CRAG | None | All rights reserved by default | Read only |
| asinghcsu/AgenticRAG-Survey | None | All rights reserved by default | Use as a reading list |
| NirDiamant/RAG_Techniques | Custom non-commercial | Non-OSI. Commercial use prohibited. Attribution required. Any contribution grants the author an *exclusive* license. | Read only. Don't copy into a portfolio repo that could later be used commercially (e.g. at a job). Don't contribute unless you accept the CLA. |
| NirDiamant/GenAI_Agents, agents-towards-production | Custom non-commercial | Same as above | Read only |

### Use with conditions

| Component | License | Condition |
|---|---|---|
| Arize Phoenix | Elastic License 2.0 | Cannot be provided as a hosted/managed service. Not open source by OSI definition. Prefer Langfuse. |
| Langfuse | MIT + `ee/` commercial | Only use non-`ee` features when self-hosting |
| Open WebUI | BSD-3 + branding clause | Cannot remove or replace "Open WebUI" branding. Run it as an external tool only. |
| SearXNG | AGPL-3.0 | Run it unmodified as a separate service over HTTP. Don't vendor or modify it. |
| Tavily, OpenAI, Anthropic, LangSmith | Commercial ToS | API keys stay in `.env`. Never commit them. |
| Embedding/reranker model weights | Per model card | Check each Hugging Face model card. BGE-M3 and bge-reranker-v2-m3 are permissive as of writing; re-verify when choosing. |
| LangGraph server (`langgraph-api` / Agent Server) | Verify | The library is MIT, but the server runtime has separate licensing tiers. Verify before production; FastAPI is the safe default. |

### Safe to reuse or adapt (keep the notices)

MIT: LangGraph, LangChain, agentic-rag-for-dummies, backblaze starter kit, Docling, FlagEmbedding, FlashRAG, LightRAG, GraphRAG, agent-chat-ui, open_deep_research, self-rag code, pydantic-ai, crewAI, openai-agents.
Apache-2.0: Controllable-RAG-Agent, Qdrant, Chroma, Ragas, DeepEval, Chainlit, rerankers, Haystack, RAGFlow, Kotaemon, Unstructured. Apache-2.0 requires preserving the NOTICE file and stating changes.

**Action:** keep a `THIRD_PARTY_NOTICES.md` from day one, listing every adapted file with its origin URL, commit SHA and license.

---

## 7. Learning Path

Each step names the source to study, the source to adapt, and the measurable outcome.

| # | Topic | Study (read) | Adapt / run | Outcome you can show |
|---|---|---|---|---|
| 1 | **Basic RAG** | rag-from-scratch videos 1–4; RAG_Techniques "simple RAG" | Docling → Qdrant → retriever → LLM chain | Answer questions over 20–50 PDFs; first Ragas baseline |
| 2 | **Agentic RAG** | `langgraph_agentic_rag.ipynb` | Retriever as a tool; LLM decides whether to retrieve | Same eval set; compare against #1 |
| 3 | **Corrective RAG** | CRAG paper; `langgraph_crag.ipynb`; Grecil (as a negative example); Backblaze `crag.py` | 3-way grade → rewrite → web fallback | Ragas on out-of-corpus questions; show web-fallback rate |
| 4 | **Routing** | `langgraph_adaptive_rag.ipynb`; Adaptive-RAG paper | Router: vectorstore / web / direct | Routing accuracy on a labeled question set |
| 5 | **Query rewriting** | agentic-rag-for-dummies `rewrite_query`; RAG_Techniques HyDE / multi-query notebooks (read only) | Multi-query + HyDE + decomposition nodes; Qdrant hybrid; reranker | Context recall/precision delta per technique |
| 6 | **Reflection** | Self-RAG paper; `langgraph_self_rag.ipynb`; Controllable-RAG grounding checks | Hallucination grader + answer grader + bounded retry loop | Faithfulness delta; loop-count distribution |
| 7 | **Tool calling** | LangGraph `ToolNode`; MCP adapters | Calculator / SQL / web / MCP tool alongside retrieval | Task success on tool-requiring questions |
| 8 | **Multi-agent** | agentic-rag-for-dummies (`Send` fan-out); open_deep_research supervisor; Controllable-RAG plan/replan | Planner → parallel research sub-agents → aggregator; HITL clarification | Multi-hop QA (HotpotQA subset via FlashRAG) |
| 9 | **Evaluation** | Ragas docs; DeepEval docs; FlashRAG benchmarks | Golden dataset, Ragas batch runs, DeepEval CI gates, Langfuse datasets | Pattern comparison table (the portfolio centerpiece) |
| 10 | **Production architecture** | Backblaze kit layering + structural tests; agent-chat-ui | FastAPI + streaming, docker compose, auth stub, rate limits, cost tracking | One-command `docker compose up` demo |

---

## 8. Proposed Repository Structure (not created yet)

```
ArchAgenticRAG/
├── AGENTS.md                      # agent/human entry point (Backblaze-kit idea)
├── README.md
├── THIRD_PARTY_NOTICES.md         # origin + SHA + license of every adapted file
├── pyproject.toml                 # uv-managed, locked deps
├── docker-compose.yml             # qdrant, langfuse stack, ollama (profile), api, ui
├── .env.example
├── docs/
│   ├── phase-0-research.md        # this document
│   ├── architecture.md
│   ├── adr/                       # architecture decision records (one per REUSE/REJECT call)
│   └── learning-log/              # per-phase notes + eval results
├── src/archagenticrag/
│   ├── config/                    # pydantic-settings; model/provider selection
│   ├── ingestion/                 # docling loader, chunking, indexer (thin wrappers)
│   ├── retrieval/                 # qdrant store, hybrid retriever, reranker
│   ├── llm/                       # chat-model + embedding factories (Ollama/Claude/OpenAI)
│   ├── nodes/                     # shared LangGraph nodes: grade, rewrite, route, reflect, web_search, generate
│   ├── graphs/                    # one module per pattern
│   │   ├── basic_rag.py
│   │   ├── agentic_rag.py
│   │   ├── corrective_rag.py
│   │   ├── adaptive_rag.py
│   │   ├── self_rag.py
│   │   └── multi_agent.py
│   ├── tools/                     # LangChain tools, MCP adapters
│   ├── observability/             # langfuse handler, logging
│   └── api/                       # FastAPI app (Phase 9)
├── ui/                            # chainlit app (early) → agent-chat-ui (Phase 9)
├── eval/
│   ├── datasets/                  # golden QA sets (JSON), corpus manifest
│   ├── run_ragas.py
│   └── test_regression.py         # deepeval gates
├── notebooks/                     # one exploration notebook per phase
├── data/                          # sample corpus (gitignored except manifest)
└── tests/
    ├── unit/                      # node logic with fake LLMs
    ├── graph/                     # graph wiring / routing tests
    └── test_structure.py          # layering rules (adapted from Backblaze kit, MIT)
```

---

## 9. Phase Plan

| Phase | Goal | Reuse / compose | New code (glue only) | Exit criteria |
|---|---|---|---|---|
| **0** | Research & architecture | — | — | This document approved |
| **1** | Foundations + Basic RAG | Fork agentic-rag-for-dummies → strip; Docling; Qdrant (Docker); Ollama or API model; Langfuse (Docker) | Config, ingestion CLI, `basic_rag` graph, Chainlit UI | `docker compose up` works; ask questions over a sample corpus; traces visible in Langfuse |
| **2** | Evaluation harness (early) | Ragas, DeepEval | 30–50 Q/A golden set, eval runner, results table | Baseline scores recorded in `docs/learning-log/` |
| **3** | Agentic + Corrective RAG | `langgraph_agentic_rag`, `langgraph_crag`, Backblaze `crag.py` prompt, Tavily | `agentic_rag`, `corrective_rag` graphs, 3-way grader | Eval delta vs. baseline; web fallback demonstrated |
| **4** | Routing + query rewriting + rerank | `langgraph_adaptive_rag`, `rewrite_query`, rerankers, Qdrant hybrid | `adaptive_rag` graph, rewrite/HyDE/multi-query nodes, rerank node | Routing accuracy measured; context precision improvement |
| **5** | Reflection (Self-RAG) | `langgraph_self_rag` | Hallucination + answer graders, bounded loops | Faithfulness delta; no infinite loops (recursion limit tests) |
| **6** | Tool calling | LangGraph `ToolNode`, MCP adapters | 2–3 tools | Tool-requiring question set passes |
| **7** | Multi-agent | `Send` fan-out (agentic-rag-for-dummies), open_deep_research supervisor | `multi_agent` graph, HITL clarification | Multi-hop eval; trace shows parallel sub-agents |
| **8** | Benchmark & compare | FlashRAG datasets (optional), Langfuse datasets | Comparison report across all graphs | Published table: quality × latency × cost per pattern |
| **9** | Production architecture | FastAPI, agent-chat-ui, structural test idea | API, streaming, compose profiles, CI (lint + unit + DeepEval gate) | One-command deploy; CI green; README demo GIF |
| **10** (stretch) | Graph RAG | LightRAG | Graph-index path as a router branch | Eval comparison vs. vector-only |

---

## 10. Phase 0 boundary

No application code has been written. The only artifact is this document.

---

# PHASE 0 STATUS

**RESEARCH COMPLETE** for architecture and reuse decisions.

### Known gaps (to close at the start of Phase 1, not blockers)

1. No test suites were executed. The Backblaze kit (17 test files) and the agentic-rag-for-dummies Docker build should be run in a Phase 1 spike to confirm they work.
2. Repositories marked **[META]** in §3b had no source audit; decisions on them are low-stakes (REFERENCE/REJECT) except Docling, Qdrant, Ragas and Langfuse, which are widely adopted and will be validated in Phase 1.
3. The LangGraph server licensing and the license of each chosen embedding/reranker model card need verification when selected.
4. Ragas activity risk (last push 2026-02-24, org move). Confirm the current release and maintenance status before pinning.

### Next steps

1. **Review and approve** this document. Confirm: LangGraph + Qdrant + Docling + Ragas + Langfuse, and agentic-rag-for-dummies as the fork base.
2. **Decide the model provider policy:** local Ollama only, API only (Claude/OpenAI), or both via config.
3. **Pick a sample corpus** for the golden eval set (e.g. 20–50 public technical PDFs or architecture docs; must be redistributable).
4. **Phase 1 spike (time-boxed):** `git init`, run agentic-rag-for-dummies + Qdrant + Langfuse via Docker, run the Backblaze kit tests, then record findings as ADRs in `docs/adr/`.
5. Begin Phase 1 implementation only after steps 1–3 are answered.
