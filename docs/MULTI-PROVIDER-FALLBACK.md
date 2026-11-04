# Multi-Provider Free-Tier Fallback

Status: implemented 2026-10-28. Infrastructure only; opt-in per experiment config.

> Free-tier availability, quotas and provider policies can change. This infrastructure treats provider availability as runtime configuration, not a guarantee.

**A fallback-enabled run is a different run configuration from a single-provider run.**
- Its config fingerprint differs.
- Its manifest records the provider order.
- Every item records which provider and model actually answered.
- `benchmark.py` labels it `MULTI-PROVIDER FALLBACK RUN, not a single-provider result`.

Never report such a run as "a Gemini experiment" unless every request was served by Gemini.

## 1. Supported providers

Every provider is reached through its OpenAI-compatible endpoint, using the `openai` SDK and `langchain-openai` already installed. No provider SDK was added.

| Provider | Base URL | Evidence (2026-10-28) | Environment |
|---|---|---|---|
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | existing preset; live smoke test passed | `GEMINI_API_KEY` |
| Cerebras Cloud | `https://api.cerebras.ai/v1` | inference-docs.cerebras.ai/resources/openai; `/models` answers 403 without a key | `CEREBRAS_API_KEY` |
| Groq | `https://api.groq.com/openai/v1` | existing preset; live smoke test passed | `GROQ_API_KEY` |
| SambaNova Cloud | `https://api.sambanova.ai/v1` | docs.sambanova.ai OpenAI-compatibility page; `/models` answers 200 | `SAMBANOVA_API_KEY` |
| OpenRouter | `https://openrouter.ai/api/v1` | existing preset (separate smoke test 2026-10) | `OPENROUTER_API_KEY` |
| Cloudflare Workers AI | `https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1` | developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/ (chat completions); the path exists (405 on GET `/models`) | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` |
| NVIDIA, xAI, OpenAI, Ollama | existing presets | unchanged | existing |

**Verification status**
- **Verified live in this repo:** Gemini and Groq.
- **Not tested live:** Cerebras, SambaNova and Cloudflare. They are verified only against their documentation and endpoint existence, because no keys are configured.
- **Model listing not documented:** Cloudflare's `/models` endpoint is not documented, so `run_eval.py`'s preflight model check may fail for Cloudflare.
- **Not added:** unknown gateways, proxies and undocumented free endpoints, such as DSH.

## 2. Environment variables

The key names are the ones already used by the repository, plus the four new ones listed in `.env.example`.

- **Values are never printed or stored.** Only variable *names* appear in manifests, and only for skipped providers.
- **Unused `.env` entries:** a local `.env` may contain `LLM_PROVIDER`, `LLM_PROVIDER_ORDER` and similar entries. The code does not read them. The provider order belongs to the versioned experiment config, so it is part of the fingerprint.

## 3. Provider priority

The provider order is the config's order: the role's own `provider` first, then `fallbacks` top to bottom. Nothing is hard-coded in Python.

- A fallback provider whose variables are missing is **skipped and recorded** (`skipped: [{provider, model, missing_env}]`).
- A missing **primary** is a configuration error (`ProviderError`), because it was selected explicitly.
- A duplicated provider/model pair is rejected.

## 4. Generator provider pool

The generator pool is `system.provider_strategy`. It is passed to the graph factory with the rest of `system`, and the graph forwards it to `providers.chat_model(..., strategy=...)`.

The graphs contain no fallback logic. `basic_rag` and `decompose_rag` gained only the extra argument; with `None` the original client is built.

## 5. Judge provider pool

The judge pool is `judge.provider_strategy`, separate from the generator's. It applies to the Ragas judge LLM: the `AsyncOpenAI` client handed to `ragas.llms.llm_factory`. Judge **embeddings** (AnswerRelevancy) are not routed and keep their single provider.

## 6. Failure classification

`provider_fallback.classify_status` and `classify_exception` sort each failure into a type. Only the first four types fall back.

| Type | From | Fallback |
|---|---|---|
| RATE_LIMIT | HTTP 429; HTTP 413 whose message names a per-minute token/rate limit (Groq's "Request too large … TPM") | yes |
| TRANSIENT_SERVER_ERROR | HTTP 500, 502, other 5xx | yes |
| TIMEOUT | HTTP 408, 504; `httpx.TimeoutException` | yes |
| PROVIDER_UNAVAILABLE | HTTP 503; connection errors (`httpx.TransportError`) | yes |
| AUTHENTICATION_ERROR | HTTP 401, 403 | **no**: the SDK raises `AuthenticationError` |
| CONTEXT_LENGTH | HTTP 400/413/422 mentioning the context length | **no** |
| INVALID_REQUEST | other HTTP 400/413/422 | **no** |
| MODEL_NOT_FOUND | HTTP 404 | **no**. A different model is never substituted. |
| UNKNOWN | anything else | **no** |

For each attempt the record keeps status code, provider, model, error type, `retry_after_s` (`Retry-After` or `retry-after-ms`), whether the message names a daily quota, a timestamp and latency. It also keeps the provider's message, redacted and cut to 300 characters.

## 7. Retry policy

The policy is per role and set in config:

| Setting | Default | Range | Meaning |
|---|---|---|---|
| `max_retries_per_provider` | 1 | 0–3 | Extra attempts on the same provider before moving on |
| `retry_backoff_s` | 2 | 0–30 | **Fixed** wait between those attempts (no exponential growth) |
| `max_retry_after_s` | 10 | 0–60 | A `Retry-After` up to this long is honoured. A longer one moves straight to the next provider. |
| `timeout_s` | 60 | 0–600 | Per-request HTTP timeout |

- **Daily quotas** ("tokens per day", "(TPD)", "(RPD)", …) are not retried on the same provider.
- **Worst case per request:** each provider gets `1 + max_retries_per_provider` attempts, separated by at most `max_retry_after_s`.
- **No SDK retries:** in fallback mode the OpenAI SDK's own retries are off (`max_retries=0`), so this transport is the only retry logic. Single mode keeps the original `max_retries=6`.

## 8. Fallback policy

- **Per request.** A provider is never disabled for the rest of a run. Question 1 can use Gemini, question 2 Cerebras, and question 3 Gemini again. No circuit breaker.
- **Only the model changes.** The request body is sent unchanged to every provider except the `model` field, so temperature, max tokens and messages are identical.
- **Exhaustion.** If every participating provider fails with a fallback-eligible error, the client receives a synthetic HTTP 429 whose message starts with `PROVIDER_EXHAUSTED: every <role> provider failed (gemini:RATE_LIMIT, …)`.
  - For the generator, the item gets a system error (triage `OTHER`, never a retrieval failure).
  - For the judge, the metrics get a missing value with that error.
  - Either way it is resumable.

**Implementation.** `provider_fallback.FallbackTransport` is an httpx transport (sync and async) installed under the OpenAI SDK client. A transport covers both paths the project uses: LangChain `ChatOpenAI` for the graphs and `openai.AsyncOpenAI` for Ragas (section 15 explains why LiteLLM and `with_fallbacks` were not used).

## 9. Metadata

**Run level (`manifest.json`)**

`provider_strategy.generator` and `provider_strategy.judge` are each either `{mode: single, provider, model}` or `{mode: fallback, configured_order, participating, skipped, retry_policy}`.

**Item level (`items.jsonl`)**

`provider_calls` (generator) and `judge_provider_calls` (appended across resume sessions). They are present only when fallback mode made requests. One record per request:

```json
{
  "role": "generator",
  "primary_provider": "gemini", "primary_model": "gemini-2.5-flash",
  "actual_provider": "cerebras", "actual_model": "llama-3.3-70b",
  "fallback_used": true, "fallback_reason": "RATE_LIMIT", "outcome": "success",
  "attempts": [
    {"provider": "gemini", "model": "gemini-2.5-flash", "attempt": 1, "status_code": 429, "error_type": "RATE_LIMIT", "retry_after_s": null, "daily_quota": false, "timestamp": "…", "latency_s": 0.31, "message": "…"},
    {"provider": "gemini", "model": "gemini-2.5-flash", "attempt": 2, "status_code": 429, "error_type": "RATE_LIMIT"},
    {"provider": "cerebras", "model": "llama-3.3-70b", "attempt": 1, "status_code": 200, "error_type": null}
  ],
  "usage": {"input_tokens": 1071, "output_tokens": 210},
  "timestamp": "…"
}
```

`outcome` is `success`, `error` (a non-fallback failure, surfaced) or `PROVIDER_EXHAUSTED`.
- `usage` comes from the provider's response, and is `null` when the provider reports none.
- The existing `usage` per item is keyed by the model name the provider returned, so token counts follow the model that actually answered.

**Health summary**

`summary.json → provider_health[role][provider]` holds: requests (attempts), successful_requests, rate_limits, timeouts, server_errors, other_errors, fallbacks (requests this provider handed on), served_as_fallback, input_tokens, output_tokens (`null` if never reported). `run_eval.py` and `resume_eval.py` print it as **Provider Health**.

**Benchmark**

`benchmark.py` adds `provider_mode` and `providers_used` (role → `provider:model` → requests served) to each row and prints the fallback warning.

## 10. Resume behaviour

- **Generator.** A generator `PROVIDER_EXHAUSTED` is an item system error, so `resume_eval.py` re-runs that item. `--no-judge` re-runs it without judging.
- **Judge.** A judge `PROVIDER_EXHAUSTED` is a metric without a value, so `resume_eval.py` re-scores only those metrics. Answers and successful metrics are never redone (tested).
- **Stopping.** `resume_eval` stops a session at the first `PROVIDER_EXHAUSTED`, exactly as at a daily quota: when every provider is out, waiting is the only remedy. The full run (`run_eval.py`) does not stop; it records the error and moves to the next item.

## 11. Security

- **Keys.** Keys are read from the environment when the client is built. They are only ever placed in the `Authorization` header of the outgoing request.
- **Masking.** `Route.__repr__` omits the key. Any key echoed back in a provider message is replaced with `[REDACTED]` before it is stored.
- **Records.** Manifests and records hold provider names, model names and variable names only.
- **Tests:**
  - `test_api_keys_never_appear_in_records_errors_or_reprs` (records, exception text, reprs, plan);
  - `test_run_records_strategy_actual_providers_and_health` (the whole run directory).
- **Commits.** The pre-commit hook still blocks `.env` files and key patterns; `.env` stays gitignored.

## 12. Baseline protection

- **Opt-in.** Fallback is used only when a config sets `provider_strategy`. Without it, or with `mode: single`, `chat_model` and `async_client` build exactly the clients they built before (tested).
- **Fingerprint.** The fingerprint leaves both `provider_strategy` fields out while they are unset, so the baseline stays `63bf3b5f990cc9e5` (tested). Setting either field gives a new fingerprint, i.e. a new run.
- **Untouched.** The baseline config, results, graph behaviour and Ragas configuration are unchanged.

## 13. Example configurations

Fragments of an experiment config. They contain only names and environment-variable references, no secrets.

```yaml
system:
  generator:                       # primary generator: tried first
    provider: gemini
    model: gemini-2.5-flash
    temperature: 0
  provider_strategy:               # generator pool (omit for a single-provider run)
    mode: fallback
    fallbacks:                     # priority order, top first; unconfigured providers are skipped
      - {provider: cerebras, model: gpt-oss-120b}
      - {provider: groq, model: openai/gpt-oss-120b}
      - {provider: sambanova, model: Meta-Llama-3.3-70B-Instruct}
    max_retries_per_provider: 1
    retry_backoff_s: 2
    max_retry_after_s: 10
    timeout_s: 60

judge:
  llm:                             # primary judge
    provider: cerebras
    model: qwen-3-32b
    temperature: 0
  embedding: {provider: gemini, model: gemini-embedding-001}
  provider_strategy:               # judge pool, independent of the generator's
    mode: fallback
    fallbacks:
      - {provider: gemini, model: gemini-2.5-flash}
      - {provider: sambanova, model: Qwen3-32B}
```

`.env` (placeholders; never commit):

```text
GEMINI_API_KEY=
CEREBRAS_API_KEY=
GROQ_API_KEY=
SAMBANOVA_API_KEY=
OPENROUTER_API_KEY=
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_ACCOUNT_ID=
```

Check model names against each provider's model list before a run; `run_eval.py`'s preflight does this for every participating provider. The names above are illustrative.

**Comparability**
- A judge pool spanning different model families changes the judge between items. Ragas scores from such a run are comparable with a single-judge run only on the items the same judge scored. Use `judge_provider_calls` to select them.
- For a controlled comparison, keep `mode: single`, or use a fallback chain that serves the same model on every provider (e.g. `gpt-oss-120b` on Cerebras and Groq).

## 14. Limitations

- **Streaming.** Streaming responses are not supported in fallback mode. The project does not stream.
- **Embeddings.** Judge embeddings are not routed.
- **Untested providers.** Cerebras, SambaNova and Cloudflare are unexercised until keys are added. Their rate-limit headers are not documented (only Cerebras documents 429), so `Retry-After` handling falls back to `retry_backoff_s`.
- **Classification.** Classification relies on HTTP status codes and a few message markers. An unusual provider response is `UNKNOWN` and does not fall back, which is safe but may stop a run that could have continued.
- **No shared state.** There is no circuit breaker and no cross-request quota tracking: every request starts again at the primary provider.
- **Different models across providers.** A different model on a fallback provider is a confound. The records make it visible but cannot remove it.

## 15. Reuse audit

| Option | Version / license | Covers the generator (LangChain) | Covers the judge (Ragas → `AsyncOpenAI`) | Per-attempt audit record | Decision |
|---|---|---|---|---|---|
| OpenAI SDK built-in retries | openai (installed), Apache-2.0 | same provider only | same provider only | no | Kept for single mode; turned off in fallback mode |
| LangChain `Runnable.with_fallbacks` | langchain-core (installed), MIT | yes | **no** (Ragas does not use LangChain models) | no; exceptions filtered by type only | Not adopted |
| LiteLLM Router | litellm 1.106.5, MIT; **109** declared dependencies | via ChatLiteLLM | would replace the Ragas client path | via its callbacks | Not adopted: very large dependency, and a second provider layer next to the existing one |
| httpx transport under the existing OpenAI clients | httpx (installed), BSD-3 | yes | yes | yes | **Built** (`provider_fallback.py`, ~400 lines incl. health summary) |
