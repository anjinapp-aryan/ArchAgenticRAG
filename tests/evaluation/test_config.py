from __future__ import annotations

import pytest
import yaml

from archagenticrag.evaluation.config import ConfigError, EvalConfig, load_config

from .conftest import BASELINE_CONFIG


def test_baseline_config_loads():
    config = load_config(BASELINE_CONFIG)
    assert config.run_name == "baseline-basic-rag"
    assert config.system.reranker is None
    assert config.system.retrieval["top_k"] == 4
    assert {"faithfulness", "answer_relevancy", "context_precision", "context_recall"} <= set(config.metrics)
    assert config.pricing == []  # no unverified prices


def test_fingerprint_is_stable_and_sensitive(baseline_config_dict):
    a = EvalConfig.model_validate(baseline_config_dict)
    b = EvalConfig.model_validate(baseline_config_dict)
    assert a.fingerprint() == b.fingerprint()
    baseline_config_dict["system"]["retrieval"]["top_k"] = 8
    assert EvalConfig.model_validate(baseline_config_dict).fingerprint() != a.fingerprint()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda c: c["metrics"].append("bleu"), "metrics"),
        (lambda c: c["judge"]["llm"].update(provider="acme"), "unknown provider"),
        (lambda c: c.update(langfuse={"enabled": True}), "dataset_name"),
        (lambda c: c.update(config_version=2), "config_version"),
        (lambda c: c.update(run_name="Has Spaces"), "run_name"),
        (lambda c: c["target"].update(factory="no_colon_here"), "factory"),
        (lambda c: c.update(pricing=[{"model": "m", "input_usd_per_mtok": 1, "output_usd_per_mtok": 1}]), "source_url"),
        (lambda c: c.update(surprise=True), "surprise"),
    ],
)
def test_invalid_configs_are_rejected(tmp_path, baseline_config_dict, mutate, message):
    mutate(baseline_config_dict)
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(baseline_config_dict), encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_missing_config_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")
