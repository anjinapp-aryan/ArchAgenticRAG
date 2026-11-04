"""Multi-provider fallback inside the evaluator: manifest, per-item records, judge pool, resume.
Mocked providers only: no network, no quota."""

from __future__ import annotations

import copy
import json

import httpx
import yaml
from langchain_core.runnables import RunnableLambda

from archagenticrag.evaluation.config import load_config
from archagenticrag.evaluation.metrics import MetricOutcome
from archagenticrag.evaluation.persistence import read_run
from archagenticrag.evaluation.resume import is_daily_quota_error, resume_evaluation
from archagenticrag.provider_fallback import EXHAUSTED
from archagenticrag.providers import async_client, chat_model

from ..test_provider_fallback import KEYS, Providers, err
from .conftest import BASELINE_CONFIG
from .test_runner import FakeScorer, _run

GEN_STRATEGY = {"mode": "fallback", "fallbacks": [{"provider": "cerebras", "model": "llama-3.3-70b"}], "retry_backoff_s": 0}
JUDGE_STRATEGY = {"mode": "fallback", "fallbacks": [{"provider": "gemini", "model": "gemini-2.5-flash"}], "retry_backoff_s": 0}


def _env(monkeypatch):
    for name, value in KEYS.items():
        monkeypatch.setenv(name, value)


def _fallback_config(config_path):
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["system"]["provider_strategy"] = GEN_STRATEGY
    config["judge"]["provider_strategy"] = JUDGE_STRATEGY
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")


def _target(providers):
    llm = chat_model("groq", "openai/gpt-oss-120b", 0, strategy=GEN_STRATEGY, inner_transport=httpx.MockTransport(providers))

    def run(inputs: dict) -> dict:
        return {"answer": llm.invoke(inputs["question"]).content, "documents": ["The answer to life is 42."]}

    return RunnableLambda(run)


class JudgeThroughFallback(FakeScorer):
    """Fake metric values, but one real judge request per item through the fallback client."""

    def __init__(self, providers):
        super().__init__()
        self.client = async_client("groq", model="qwen/qwen3.8-27b", strategy=JUDGE_STRATEGY, role="judge", inner_transport=httpx.MockTransport(providers))

    async def score(self, item, answer, contexts, only=None, stop=None):
        outcomes = [o for o in await super().score(item, answer, contexts) if only is None or o.name in only]
        try:
            await self.client.chat.completions.create(model="qwen/qwen3.8-27b", messages=[{"role": "user", "content": "judge"}])
        except Exception as exc:  # what RagasScorer does: a failed judge call becomes a metric error
            return [MetricOutcome(o.name, None, error=f"{type(exc).__name__}: {exc}") for o in outcomes]
        return outcomes


def test_baseline_fingerprint_is_unchanged_and_a_fallback_config_is_a_different_run():
    baseline = load_config(BASELINE_CONFIG)
    assert baseline.fingerprint() == "63bf3b5f990cc9e5"
    assert baseline.system.provider_strategy is None and baseline.judge.provider_strategy is None
    data = copy.deepcopy(yaml.safe_load(BASELINE_CONFIG.read_text(encoding="utf-8")))
    data["system"]["provider_strategy"] = GEN_STRATEGY
    from archagenticrag.evaluation.config import EvalConfig

    assert EvalConfig.model_validate(data).fingerprint() != "63bf3b5f990cc9e5"


def test_run_records_strategy_actual_providers_and_health(mini_repo, monkeypatch):
    _env(monkeypatch)
    root, config_path = mini_repo()
    _fallback_config(config_path)
    gen = Providers({"groq": [(429, err("TPM"), {})]})  # the generator's primary is rate limited throughout
    judge = Providers({})
    run = read_run(_run(root, config_path, target=_target(gen), scorer=JudgeThroughFallback(judge)))

    strategy = run["manifest"]["provider_strategy"]
    assert [r["provider"] for r in strategy["generator"]["configured_order"]] == ["groq", "cerebras"]
    assert [r["provider"] for r in strategy["judge"]["participating"]] == ["groq", "gemini"]
    for item in run["items"]:
        (call,) = item["provider_calls"]
        assert (call["primary_provider"], call["actual_provider"], call["fallback_reason"]) == ("groq", "cerebras", "RATE_LIMIT")
        assert item["answer"] == "from cerebras"
    assert all(i["judge_provider_calls"][0]["actual_provider"] == "groq" for i in run["items"])
    health = run["summary"]["provider_health"]
    assert health["generator"]["cerebras"]["served_as_fallback"] == 3 and health["generator"]["groq"]["rate_limits"] == 6
    assert health["judge"]["groq"]["successful_requests"] == 3
    dumped = json.dumps(run)
    assert not any(secret in dumped for secret in KEYS.values())


async def test_exhausted_judge_is_resumable_and_successes_are_not_repeated(mini_repo, monkeypatch):
    _env(monkeypatch)
    root, config_path = mini_repo()
    _fallback_config(config_path)
    everything_down = Providers({"groq": [(429, err("busy"), {})], "gemini": [(503, err("down"), {})]})
    run_dir = _run(root, config_path, target=_target(Providers({})), scorer=JudgeThroughFallback(everything_down))
    items = {r["id"]: r for r in read_run(run_dir)["items"]}
    q1 = items["Q1"]
    assert all(m["value"] is None for m in q1["metrics"].values())
    assert EXHAUSTED in q1["metrics"]["faithfulness"]["error"] and is_daily_quota_error(q1["metrics"]["faithfulness"]["error"])
    assert q1["judge_provider_calls"][0]["outcome"] == EXHAUSTED
    assert q1["triage"]["label"] != "RETRIEVAL_FAILURE"  # a provider outage is not a retrieval result
    answers = {k: v["answer"] for k, v in items.items()}

    healthy = JudgeThroughFallback(Providers({}))
    session = await resume_evaluation(run_dir, repo_root=root, target=_target(Providers({})), scorer=healthy)
    after = {r["id"]: r for r in read_run(run_dir)["items"]}
    assert session["still_pending_items"] == 0 and session["rerun_items"] == []  # answers kept, only judging redone
    assert {k: v["answer"] for k, v in after.items()} == answers
    assert after["Q1"]["metrics"]["faithfulness"]["value"] == 1.0
    assert [c["outcome"] for c in after["Q1"]["judge_provider_calls"]] == [EXHAUSTED, "success"]  # history kept

    again = JudgeThroughFallback(Providers({}))
    session = await resume_evaluation(run_dir, repo_root=root, target=_target(Providers({})), scorer=again)
    assert session["pending_items"] == 0 and again.seen == []  # nothing successful is judged twice
