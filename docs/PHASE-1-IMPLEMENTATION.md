# Phase 1: Basic RAG Implementation

This document describes the Basic RAG system that the Phase 2 evaluation harness measures. It is deliberately simple: one retrieval, one generation, no loops.

The reuse decisions and their evidence are in [PHASE-1-REUSE-AUDIT.md](PHASE-1-REUSE-AUDIT.md). The measured results are in [PHASE-2-BASELINE-RESULTS.md](PHASE-2-BASELINE-RESULTS.md).

## 1. Architecture

```text
Offline (once per index)                     Online (per question)

data/corpus/peps/*.rst                        question
   │  verify sha256 vs MANIFEST.json             │
   ▼                                             ▼
docutils PEP reader  (RST → doctree)          LangGraph  START
   │  drop TOC, unwrap links,                    │
   │  header fields → paragraphs, add <h1>       ▼
   ▼                                          retrieve ──► QdrantVectorStore.as_retriever(k=top_k)
html4css1 writer     (doctree → HTML)            │            │ embed query (FastEmbed, bge-small)
   ▼                                             │            ▼
Docling DocumentConverter (HTML → DoclingDocument)│         Qdrant server (cosine, 384-d)
   ▼                                             │
HybridChunker (bge-small tokenizer, 480 tokens)  ▼
   ▼                                          generate ──► ChatPromptTemplate | ChatOpenAI | StrOutputParser
FastEmbed bge-small-en-v1.5 (ONNX, CPU)          │            (Groq / Gemini / Ollama / … via OpenAI-compatible API)
   ▼                                             ▼
Qdrant collection + index metadata            END  → {question, documents, context, answer}
```

The graph is exactly `START → retrieve → generate → END`. There is no grading, rewriting, routing, reflection, tool calling or web search.

## 2. Reuse decisions

| Need | Decision | What |
|---|---|---|
| Orchestration | REUSE | LangGraph `StateGraph` |
| Graph shape | ADAPT (pattern) | Official LangGraph RAG examples, `retrieve` / `generate` nodes |
| RST parsing | REUSE | docutils PEP reader (Docling has no RST backend) |
| Document model + chunking | REUSE | Docling HTML backend + `HybridChunker` |
| Embeddings | REUSE | FastEmbed through LangChain `FastEmbedEmbeddings` |
| Vector store | REUSE | Qdrant server + `langchain-qdrant` `QdrantVectorStore` |
| Collection guard | ADAPT (pattern) | agentic-rag-for-dummies' vector-size check, extended to model and chunking |
| LLM client | REUSE | `langchain-openai` `ChatOpenAI` against any OpenAI-compatible endpoint |
| Provider selection | BUILD (small) | One preset table shared with the evaluator |

New code is limited to the glue: settings validation, the docutils tree transforms, chunk metadata, the index manifest and the graph factory.

## 3. Components

| Module | Responsibility |
|---|---|
| `src/archagenticrag/providers.py` | Provider presets (base URL, key variable) for Gemini, Groq, NVIDIA, OpenRouter, xAI, OpenAI and Ollama. Builds a `ChatOpenAI` (graph) or `AsyncOpenAI` (judge) client with `max_retries=6`. Shared with the evaluator. |
| `src/archagenticrag/rag/settings.py` | Strict pydantic models for the `system` config section. Unknown keys, unknown providers, non-local embeddings, a reranker, non-similarity search or an out-of-range `top_k` / `max_tokens` fail with `SettingsError`. |
| `src/archagenticrag/rag/ingestion.py` | Verifies corpus hashes, parses each PEP with docutils, converts and chunks it with Docling, and attaches metadata. |
| `src/archagenticrag/rag/vector_store.py` | Qdrant client, FastEmbed embeddings, collection creation with index metadata, and `open_store`, which refuses a mismatched or empty index. |
| `src/archagenticrag/rag/ingest.py` | CLI that indexes the corpus from an eval config. |
| `src/archagenticrag/graphs/basic_rag.py` | `build_graph(system=...)`: the LangGraph graph, prompt and state. |
| `docker-compose.yml` | Qdrant server `qdrant/qdrant:v1.19.1`. |

### State

```python
class RAGState(TypedDict, total=False):
    question: str
    documents: list[Document]   # read by the evaluator (contexts_key)
    context: str                # numbered, source-labelled passages sent to the LLM
    answer: str                 # read by the evaluator (answer_key)
```

### Chunk metadata

Each chunk carries:

- `doc_id` (for example `pep-0484`)
- `source` (corpus file path)
- `title`, `pep`, `status`
- `section` (Docling heading path, joined with ` > `)
- `chunk_id` (`pep-0484#012`)
- `chunk_index`

The evaluator uses `doc_id` to compute retrieval hits.

## 4. Configuration

All settings come from the `system` section of [eval/configs/baseline-basic-rag.yaml](../eval/configs/baseline-basic-rag.yaml). The same file drives ingestion, the graph and the evaluation, so the config fingerprint in each run id covers the whole system.

```yaml
system:
  generator:  {provider: groq, model: openai/gpt-oss-120b, temperature: 0}
  embedding:  {provider: local, model: BAAI/bge-small-en-v1.5}
  reranker: null
  retrieval:
    top_k: 4
    search_type: similarity
    embedding_dimension: 384
    qdrant: {url: http://localhost:6333, collection: peps_v1_bge_small_docling_480}
  chunking:
    strategy: docling_hybrid
    tokenizer: BAAI/bge-small-en-v1.5
    max_tokens: 480
    merge_peers: true
```

Rules:

- **Provider selection is explicit.** `generator.provider` must be one of the preset names. To run fully local, use `provider: ollama` and an installed model name.
- **API keys come from `.env` only.** The variable names are in `.env.example`. `.env` is gitignored, and a local pre-commit hook blocks key patterns.
- **Qdrant:** `url` sets host and port. `api_key_env` names the variable to read for a secured server. No cloud setting is assumed.
- **The index name is part of the config.** Changing the embedding model or chunking without changing the collection name is refused at graph build time (see section 9).

## 5. Local setup

Requirements: Python 3.12, Docker Desktop, and roughly 300 MB disk for models.

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[eval]" pytest pytest-asyncio
cp .env.example .env            # then fill in the key for the provider you use
```

FastEmbed downloads the ONNX model (`Qdrant/bge-small-en-v1.5-onnx-Q`) and the tokenizer on first use. No torch or GPU is needed.

## 6. Qdrant setup

```bash
docker compose up -d qdrant                          # REST :6333, gRPC :6334, volume qdrant_storage
curl http://localhost:6333/collections               # health check
python -m archagenticrag.rag.ingest eval/configs/baseline-basic-rag.yaml
```

The ingest command recreates the collection and stores this metadata with it:

- embedding model, provider and dimension
- chunking settings
- corpus id, source commit and manifest hash
- chunks per document
- library versions
- `indexed_at`

Measured on 2026-10-01: 13 documents, 455 chunks, 384-d cosine vectors. Parse, chunk, embed and upsert took about 45 s on CPU.

## 7. Ollama setup

Ollama is supported through its OpenAI-compatible endpoint (`http://localhost:11434/v1`, override with `OLLAMA_BASE_URL`). No key is needed.

```bash
ollama pull llama3.1:8b          # any chat model
# config:
#   generator: {provider: ollama, model: llama3.1:8b, temperature: 0}
```

**Status on this machine:** Ollama is not installed, so the Ollama path has **not** been run end to end. At the user's direction, the baseline uses Groq for generation. The code path is the same `ChatOpenAI` client used for Groq, so only the base URL changes.

## 8. Ingestion

1. **Integrity:** `load_corpus_manifest` re-hashes every file against `MANIFEST.json` and stops on any mismatch. `.gitattributes` keeps git from changing corpus line endings.
2. **Parse:** docutils `publish_doctree(..., reader="pep")` parses the PEP and its RFC 2822 header.
3. **Clean the tree.** These are the only content transforms:
   - Remove the auto-generated table of contents.
   - Replace hyperlinks with their text, so Docling does not split sentences around links.
   - Turn the header field list into `Field: value` paragraphs, so Title, Status, Python-Version and Superseded-By become retrievable text.
   - Insert the document title `PEP N - Title` as `<h1>`. Docling treats content before the first heading as page furniture, which chunkers skip.
4. **Render** with the `html4css1` writer, then convert with Docling's HTML backend.
5. **Chunk** with `HybridChunker(HuggingFaceTokenizer(bge-small, max_tokens=480), merge_peers=True)`. Chunk text is `contextualize(chunk)`, which adds the heading path, prefixed with the PEP title line when that is not already present. The largest chunk is 495 bge tokens, under the model's 512-token window.

## 9. Retrieval

- The `retrieve` node calls `QdrantVectorStore.as_retriever(search_type="similarity", search_kwargs={"k": top_k})`.
- The query is embedded with the same FastEmbed model, and Qdrant returns the `top_k` nearest chunks by cosine similarity.
- Because it is a LangChain retriever, it fires retriever callbacks. The evaluator uses them to time retrieval.

Before the graph is built, `open_store` checks that:

- the collection exists;
- its vector size matches the embedding model (`langchain-qdrant` `validate_collection_config`);
- its recorded embedding model and chunking settings match the config;
- it is not empty.

Any mismatch fails with an instruction to re-run the ingest command. A stale index can never be evaluated silently.

## 10. Generation

The `generate` node runs `ChatPromptTemplate | chat model | StrOutputParser`. The system prompt tells the model to:

1. answer only from the numbered context passages;
2. not use outside knowledge or invent facts;
3. say clearly when the documents do not contain the answer;
4. keep the answer concise.

Each passage is labelled `[i] (doc_id › section)`. Temperature is 0. There is no answer grading, retry or reflection.

## 11. Tests

| Suite | Marker | Needs | What it covers |
|---|---|---|---|
| `tests/evaluation/` | default | nothing | The Phase 2 harness (71 original tests plus retargeted and added ones) |
| `tests/rag/test_settings.py` | default | nothing | Baseline config parses. Unknown provider, reranker, `top_k=0`, hybrid search and other invalid values fail with a clear message. Ollama needs no API key. |
| `tests/rag/test_ingestion.py` | default | corpus | Manifest hashes verify, a tampered file is rejected, the PEP header is extracted and kept as body text (no TOC, no external links), every corpus PEP parses |
| `tests/rag/test_vector_store.py` | default | in-memory Qdrant | Collection created with index metadata, re-indexing is idempotent, dimension mismatch rejected, missing or differently built index refused, similarity search returns `top_k` |
| `tests/rag/test_basic_rag.py` | default | in-memory Qdrant, fake embeddings, recording chat model | Factory is the configured target, graph is exactly retrieve then generate, question flows through both nodes, prompt rules, source labels, `eval_metadata`, invalid config and missing index fail clearly, Phase 2 evaluator runs the graph |
| `tests/integration/test_local_stack.py` | `integration` | Qdrant server | Real Docling + FastEmbed + Qdrant. All 13 documents chunked, header retrievable, chunks fit 512 tokens, known questions retrieve the right PEP. |
| `tests/integration/test_live_evaluation.py` | `live` | Qdrant index, `.env` keys | Golden item A01 through `run_evaluation` with the real graph and judge |

```bash
pytest                     # offline: 115 tests
pytest -m integration      # 8 tests, needs docker compose up -d qdrant
pytest -m live             # 1 test, needs the baseline index and API keys
```

## 12. Evaluation integration

The Phase 2 evaluator was not redesigned. It imports `target.factory` (`archagenticrag.graphs.basic_rag:build_graph`), calls it with `system=<config section>`, and invokes the compiled graph per question. It reads `answer` and `documents[*].metadata["doc_id"]`.

Additive changes made to the evaluator:

- LLM calls are timed and counted through the existing callback handler, giving `generation_latency_s`.
- `graph.eval_metadata` (index description and prompt) is recorded in each run manifest.
- The summary reports retrieval and generation latency percentiles.
- `answer_correctness` now uses Ragas `AnswerCorrectness` (question-aware, recall-weighted) instead of `FactualCorrectness`. The judge smoke test showed that `FactualCorrectness` scored correct answers 0 on short references. See ADR 008.

## 13. Known limitations

- **Ollama not exercised.** The local LLM path is configured and shares code with the API path, but this machine has no Ollama install. The baseline generator is Groq `openai/gpt-oss-120b`.
- **Free-tier rate limits** shape the run: Groq allows 8,000 tokens per minute per model, and the run uses `max_concurrency: 2`. Latency numbers therefore include provider queueing and retry back-off, and are not pure model latency.
- **Cost is `null`.** No published price was entered for the free-tier models.
- **Dense retrieval only, fixed `top_k=4`.** Questions that need more than four chunks, or exact identifiers, are expected to suffer. This is intentional and measured, not fixed.
- **Generator citation artefacts.** gpt-oss sometimes appends markers like `【1†L1-L4】` to answers. They are left in place; the prompt does not ask for citations.
- **Chunk size is not tuned.** 480 tokens was chosen to fit bge-small's 512-token window, not by experiment.
- **The judge is an LLM.** Scores from Groq `qwen/qwen3.8-27b` carry judge noise. The judge is a different model family from the generator, to limit self-preference bias.
