"""Token estimates, prices and cost accounting. Nothing here invents a price.

* Prices come only from the `model_price` table the author fills in (with source and date).
* Local providers (built-in test model, Ollama) have no API charge; that is reported as such.
* Estimates are labelled as estimates: ~4 characters per token is a rough rule of thumb.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pbs_core.providers.base import Usage
from pbs_core.providers.egress import provider_is_local
from pbs_core.storage.ai_models import ModelPrice, ProviderConfig

MAX_CONTEXT_CHARS = 48_000  # project-local content limit per request (~12k tokens)
CHARS_PER_TOKEN = 4
ESTIMATE_BASIS = "Estimate: about 4 characters per token. Providers count differently."


@dataclass
class Cost:
    amount: str | None  # decimal string, None = unknown
    currency: str | None
    basis: str


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


def clip_context(text: str, sel_start: int | None, sel_end: int | None, limit: int = MAX_CONTEXT_CHARS) -> str:
    """Keep requests inside the per-request limit, centred on the selection (or the chapter end)."""
    if len(text) <= limit:
        return text
    if sel_start is not None and sel_end is not None:
        pad = max(0, (limit - (sel_end - sel_start)) // 2)
        lo, hi = max(0, sel_start - pad), min(len(text), sel_end + pad)
    else:
        lo, hi = len(text) - limit, len(text)
    return (
        ("[… earlier text omitted …]\n" if lo > 0 else "")
        + text[lo:hi]
        + ("\n[… later text omitted …]" if hi < len(text) else "")
    )


def price_for(s: Session, provider: ProviderConfig, model: str) -> ModelPrice | None:
    return s.scalars(
        select(ModelPrice).where(ModelPrice.provider_config_id == provider.id, ModelPrice.model_name == model)
    ).one_or_none()


def _dec(value: str) -> Decimal | None:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return None


def cost_of(s: Session, provider: ProviderConfig, model: str, usage: Usage) -> Cost:
    if provider_is_local(provider.kind, provider.base_url):
        return Cost("0", None, "Local model: no API charge.")
    price = price_for(s, provider, model)
    if price is None:
        return Cost(None, None, "Unknown: no price entered for this model.")
    if usage.input_tokens is None or usage.output_tokens is None:
        return Cost(None, price.currency, "Unknown: the provider did not report token usage.")
    pin, pout = _dec(price.input_per_mtok), _dec(price.output_per_mtok)
    if pin is None or pout is None:
        return Cost(None, price.currency, "Unknown: the stored price is not a number.")
    amount = (Decimal(usage.input_tokens) * pin + Decimal(usage.output_tokens) * pout) / Decimal(1_000_000)
    src = (
        f" (price from {price.source_url}, as of {price.as_of})"
        if price.source_url
        else f" (price as of {price.as_of})"
    )
    basis = ("Reported usage" if usage.reported else "Estimated usage") + " × your entered price" + src
    return Cost(str(amount.quantize(Decimal("0.000001"))), price.currency, basis)


def estimate(
    s: Session, provider: ProviderConfig, model: str, prompt_chars: int, max_output_tokens: int
) -> dict[str, object]:
    input_tokens = math.ceil(prompt_chars / CHARS_PER_TOKEN)
    out: dict[str, Any] = {
        "input_tokens": input_tokens,
        "max_output_tokens": max_output_tokens,
        "is_estimate": True,
        "basis": ESTIMATE_BASIS,
        "cost_upper_bound": None,
        "currency": None,
        "cost_note": "",
    }
    if provider_is_local(provider.kind, provider.base_url):
        out["cost_upper_bound"] = "0"
        out["cost_note"] = "Local model: no API charge."
        return out
    price = price_for(s, provider, model)
    if price is None:
        out["cost_note"] = "Price unknown: add the model's price in AI settings to see an estimate."
        return out
    pin, pout = _dec(price.input_per_mtok), _dec(price.output_per_mtok)
    if pin is None or pout is None:
        out["cost_note"] = "Price unknown: the stored price is not a number."
        return out
    upper = (Decimal(input_tokens) * pin + Decimal(max_output_tokens) * pout) / Decimal(1_000_000)
    out["cost_upper_bound"] = str(upper.quantize(Decimal("0.0001")))
    out["currency"] = price.currency
    out["cost_note"] = f"Upper bound if the full output limit is used, from your entered price (as of {price.as_of})."
    return out
