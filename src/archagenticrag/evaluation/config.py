"""Versioned evaluation run configuration (YAML)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from archagenticrag.evaluation.providers import PROVIDERS

MetricName = Literal[
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "answer_correctness",
    "abstention",
    "clarification",
]


class TriageThresholds(BaseModel):
    """Score below which a metric counts as failed when classifying failures.

    Provisional values; recorded in every run so a later change is visible.
    """

    model_config = ConfigDict(extra="forbid")

    context_recall: float = Field(default=0.5, ge=0, le=1)
    faithfulness: float = Field(default=0.7, ge=0, le=1)
    answer_correctness: float = Field(default=0.5, ge=0, le=1)
    answer_relevancy: float = Field(default=0.5, ge=0, le=1)
    context_precision: float = Field(default=0.5, ge=0, le=1)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelRef(_Strict):
    provider: str
    model: str = Field(min_length=1)
    temperature: float | None = None

    @model_validator(mode="after")
    def _known_provider(self) -> ModelRef:
        if self.provider not in PROVIDERS and self.provider != "local":
            raise ValueError(f"unknown provider {self.provider!r}; known: {sorted(PROVIDERS)} or 'local'")
        return self


class DatasetRef(_Strict):
    path: Path
    corpus_dir: Path


class TargetRef(_Strict):
    """How to build and call the system under test.

    ``factory`` is "module:function". The function receives ``system=<SystemConfig dict>``
    plus ``kwargs`` and must return an object with ``invoke(dict, config=...) -> dict``
    (any compiled LangGraph graph satisfies this).
    """

    factory: str = Field(pattern=r"^[\w.]+:\w+$")
    kwargs: dict = Field(default_factory=dict)
    input_key: str = "question"
    answer_key: str = "answer"
    contexts_key: str = "documents"


class SystemConfig(_Strict):
    """Configuration of the system under test. It is passed to the target factory and
    recorded in every run manifest, so the config file is the single source of truth."""

    generator: ModelRef
    embedding: ModelRef
    reranker: ModelRef | None = None
    retrieval: dict = Field(default_factory=dict)  # e.g. {top_k: 4, search_type: similarity}
    chunking: dict = Field(default_factory=dict)  # e.g. {strategy: ..., chunk_size: ..., chunk_overlap: ...}


class JudgeConfig(_Strict):
    llm: ModelRef
    embedding: ModelRef  # needed by Ragas AnswerRelevancy


class Pricing(_Strict):
    """Per-model price. Only fill in from the provider's published price page."""

    model: str
    input_usd_per_mtok: float = Field(ge=0)
    output_usd_per_mtok: float = Field(ge=0)
    source_url: str
    verified_on: str


class LangfuseConfig(_Strict):
    enabled: bool = False
    dataset_name: str | None = None

    @model_validator(mode="after")
    def _needs_dataset_name(self) -> LangfuseConfig:
        if self.enabled and not self.dataset_name:
            raise ValueError("langfuse.dataset_name is required when langfuse.enabled is true")
        return self


class EvalConfig(_Strict):
    config_version: Literal[1]
    run_name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    dataset: DatasetRef
    target: TargetRef
    system: SystemConfig
    judge: JudgeConfig
    metrics: list[MetricName] = Field(min_length=1)
    triage: TriageThresholds = Field(default_factory=TriageThresholds)
    pricing: list[Pricing] = Field(default_factory=list)
    langfuse: LangfuseConfig = Field(default_factory=LangfuseConfig)
    max_concurrency: int = Field(default=4, ge=1, le=32)

    def fingerprint(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class ConfigError(ValueError):
    pass


def load_config(path: str | Path) -> EvalConfig:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    try:
        return EvalConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid config {path}:\n{exc}") from exc
