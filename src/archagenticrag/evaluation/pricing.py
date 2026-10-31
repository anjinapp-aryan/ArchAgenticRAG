"""Optional price book (eval/pricing.yaml) for report-time cost.

Prices are never guessed: a model without a documented entry makes the cost ``None``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class PriceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str = Field(min_length=1)
    input_price_per_million: float = Field(ge=0)
    output_price_per_million: float = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    effective_date: date
    source_url: str = Field(pattern=r"^https://")


class PriceBook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pricing_version: Literal[1]
    prices: list[PriceEntry] = Field(default_factory=list)

    def price_for(self, model: str, on: date) -> PriceEntry | None:
        """The latest entry for ``model`` that took effect on or before ``on``."""
        candidates = [p for p in self.prices if p.model == model and p.effective_date <= on]
        return max(candidates, key=lambda p: p.effective_date, default=None)


def load_price_book(path: Path) -> PriceBook:
    if not path.exists():
        return PriceBook(pricing_version=1)
    return PriceBook.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def run_cost(tokens_by_model: dict[str, dict[str, int]], book: PriceBook, on: date) -> dict[str, Any]:
    """Per-model and total cost; total is ``None`` unless every model has a price in one currency."""
    by_model: dict[str, Any] = {}
    currencies: set[str] = set()
    for model, tokens in sorted(tokens_by_model.items()):
        price = book.price_for(model, on)
        if price is None:
            by_model[model] = None
            continue
        currencies.add(price.currency)
        by_model[model] = {
            "amount": tokens.get("input_tokens", 0) / 1e6 * price.input_price_per_million
            + tokens.get("output_tokens", 0) / 1e6 * price.output_price_per_million,
            "currency": price.currency,
            "source_url": price.source_url,
            "effective_date": price.effective_date.isoformat(),
        }
    complete = bool(by_model) and all(v is not None for v in by_model.values()) and len(currencies) == 1
    total = sum(v["amount"] for v in by_model.values()) if complete else None
    return {"total": total, "currency": currencies.pop() if complete else None, "by_model": by_model}
