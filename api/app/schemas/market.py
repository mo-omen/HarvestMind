from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


MarketSignal = Literal["watch", "buy", "hold"]


class MarketSource(BaseModel):
    name: str
    url: str | None = None


class MarketSummaryItem(BaseModel):
    crop: str
    display_name: str
    emoji: str
    price_min_rm_per_kg: float
    price_max_rm_per_kg: float
    trend: Literal["rising", "stable", "falling", "unknown"]
    trend_score: int = Field(ge=0, le=100)
    change_30d_pct: float
    signal: MarketSignal
    confidence: float = Field(ge=0, le=1)
    source: str
    source_urls: list[str] = Field(default_factory=list)
    as_of: date
    updated_at: datetime | None = None
    notes: list[str] = Field(default_factory=list)


class MarketSummaryResponse(BaseModel):
    items: list[MarketSummaryItem]
    generated_at: datetime


class MarketSignalCard(BaseModel):
    label: str
    severity: Literal["risk", "opportunity", "watch"]
    title: str
    summary: str
    source_urls: list[str] = Field(default_factory=list)


class MarketSignalsResponse(BaseModel):
    cards: list[MarketSignalCard]
    generated_at: datetime
    source: str
