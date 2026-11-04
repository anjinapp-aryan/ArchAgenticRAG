---
name: provider-development
description: "Use when adding or changing an LLM provider, model, credential, retry or fallback behaviour in ArchAgenticRAG, or when a task depends on provider quota. Reuses the OpenAI-compatible provider layer and the opt-in fallback transport, keeps provider identity auditable and never substitutes a model silently."
---

# provider-development

## Purpose
Change providers without touching graphs or breaking reproducibility. Design and limits: `docs/MULTI-PROVIDER-FALLBACK.md`.

## When to use
New provider; changed model, endpoint, credentials or retry policy; a fallback pool for a run; diagnosing 429s or quota.

## Inputs
Provider name and official docs URL; the role (generator or judge); whether it is for a controlled experiment.

## Workflow
1. **Read first:** `src/archagenticrag/providers.py` (presets, `ProviderStrategy`, `chat_model`, `async_client`), `src/archagenticrag/provider_fallback.py` (transport, classification, health), and the fallback doc.
2. **Reuse.** Every provider is an OpenAI-compatible endpoint behind the existing `openai`/`ChatOpenAI` clients. Add a preset in `PROVIDERS` (base URL, key variable name, optional URL variable). Do not add a provider SDK unless `reuse-audit` shows the endpoint cannot work.
3. **Verify the endpoint** from official docs and a keyless probe (`curl -s -o /dev/null -w '%{http_code}' <base>/models`). Do not add unofficial gateways, proxies or undocumented free endpoints.
4. **Credentials:** environment variables only, with placeholders in `.env.example`. Use existing names where they exist. Missing variables of a fallback provider are skipped and recorded; a missing primary is a configuration error.
5. **Fallback pools** are configured as `provider_strategy` (generator: `system.provider_strategy`, judge: `judge.provider_strategy`), never hard-coded. Only rate limits, 5xx, timeouts and unavailability fall back; authentication, invalid request, context length and model-not-found must surface.
6. **Identity.** Each request records primary and actual provider/model, fallback reason and attempts (`provider_calls`, `judge_provider_calls`). A fallback run is a different configuration and `benchmark.py` labels it.
7. **Tests:** offline with `httpx.MockTransport` (pattern in `tests/test_provider_fallback.py`); live smoke tests tiny and with simulated failures. Never burn quota to force a real 429.

## Required checks
- Baseline fingerprint unchanged (`EXPERIMENT_RULES.md`): `provider_strategy` stays out of the fingerprint while unset.
- No key or `Authorization` header in logs, errors, records or results (`security`).
- Reported model for each answer is the model that actually answered.

## Output
The preset or config change, the tests added, and the verification evidence (probe result, mocked and live test statuses).

## STOP
- The baseline fingerprint would change.
- The provider is unofficial or its terms are unclear (`license-audit`).
- A key would be printed, committed or requested in chat.
- A controlled experiment would run on a mixed or substituted model without that being the stated variable.
