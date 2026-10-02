# Third-party notices

## Evaluation corpus

`data/corpus/peps/*.rst` are unmodified copies of Python Enhancement Proposals from
https://github.com/python/peps (commit `50803e5f0aa404f34093c16d13a9bd7d21d904d1`).

Each document states that it is placed in the public domain, or that it is "in the public domain or under the CC0-1.0-Universal license, whichever is more permissive".

Per-file details are in `data/corpus/peps/MANIFEST.json`.

## Adapted patterns (no code copied)

| Project | License | Commit | What we adapted | Where |
|---|---|---|---|---|
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) `examples/rag/langgraph_crag.ipynb`, `langgraph_agentic_rag.ipynb` | MIT, Copyright (c) LangChain, Inc. | `4be610c6bc7c042038f671d6def9f523ca385a69` | The retrieve → generate node structure and the context formatting | `src/archagenticrag/graphs/basic_rag.py` |
| [GiovanniPasq/agentic-rag-for-dummies](https://github.com/GiovanniPasq/agentic-rag-for-dummies) `project/db/vector_db_manager.py` | MIT, Copyright (c) 2025 Giovanni Pasqualino | `2461e5251c6b9a6be71d13176ab43301f3c0a068` | Refusing a Qdrant collection whose vector size does not match the embedding model | `src/archagenticrag/rag/vector_store.py` |

Both projects are MIT licensed. Their notice is reproduced here:

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions: The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

## Model weights (downloaded at runtime, not redistributed)

| Model | License | Source |
|---|---|---|
| BAAI/bge-small-en-v1.5 (embeddings, tokenizer) | MIT | https://huggingface.co/BAAI/bge-small-en-v1.5 (`5c38ec7`). The ONNX export is https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q (`aa8f8b0`, MIT). |

## Libraries (used as dependencies, not copied)

| Package | License | Use |
|---|---|---|
| langgraph 1.2.12 | MIT | Graph orchestration |
| langchain-openai 1.6.7 | MIT | Chat model client for OpenAI-compatible providers |
| langchain-community 0.3.31 | MIT | FastEmbedEmbeddings wrapper; Ragas dependency |
| langchain-core | MIT | Documents, prompts, callbacks |
| langchain-qdrant 1.1.0 | MIT | Qdrant vector store / retriever |
| qdrant-client 1.19.1 | Apache-2.0 | Qdrant client |
| fastembed 0.8.1 | Apache-2.0 | Local ONNX embeddings |
| onnxruntime | MIT | Embedding inference |
| docling-slim 2.131.0, docling-core 2.99.0 | MIT | HTML conversion, HybridChunker |
| docutils 0.23 | Public domain (core and PEP reader); parts BSD-2 / GPL-3 per its COPYING | reStructuredText → HTML |
| beautifulsoup4 | MIT | Docling HTML backend |
| transformers, tokenizers | Apache-2.0 | Tokenizer for chunk sizing (no model inference) |
| ragas 0.4.3 | Apache-2.0 | Evaluation metrics |
| langfuse 4.16.0 (Python SDK) | MIT | Experiment runner, datasets |
| openai | Apache-2.0 | OpenAI-compatible client for the Ragas judge |
| pydantic, PyYAML | MIT | Config and schema validation |
| python-dotenv | BSD-3-Clause | Loads `.env` |

## Services (not redistributed)

| Service | License / terms |
|---|---|
| Qdrant server (`qdrant/qdrant:v1.19.1` Docker image) | Apache-2.0 |
| Groq, Google Gemini and NVIDIA NIM APIs | Provider terms of service |
