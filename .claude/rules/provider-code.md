---
paths:
  - "src/archagenticrag/providers.py"
  - "src/archagenticrag/provider_fallback.py"
  - "tests/test_provider_fallback.py"
  - "tests/evaluation/test_provider_fallback_eval.py"
  - ".env.example"
---

# Provider and credential code

Loaded when you read or edit provider code. Procedure: `provider-development` and `security` skills. Design: `docs/MULTI-PROVIDER-FALLBACK.md`.

- Keys come from environment variables only. `.env.example` holds names with empty values. Never print, log or store a value; records carry provider and model names and variable names.
- Providers are OpenAI-compatible presets behind the existing clients. A provider SDK needs a `reuse-audit` first.
- Fallback is opt-in per config and must never be silent: the record keeps primary and actual provider and model, reason and attempts.
- Only rate limits, 5xx, timeouts and unavailability fall back; authentication, invalid request, context length and model-not-found must surface.
- Provider settings that are unset must not change any config fingerprint.
- Test with `httpx.MockTransport`. Never spend quota to provoke a real 429.
