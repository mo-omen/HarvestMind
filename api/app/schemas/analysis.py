from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.malaysia import normalize_malaysia_location


DecisionType = Literal["persevere", "pivot_partially", "harvest_early"]
RiskLevel = Literal["low", "medium", "high"]
PriceDirection = Literal["rising", "stable", "falling", "unknown"]
PriceOutlook = Literal["increase", "stable", "decrease"]


class DecisionAnalysisRequest(BaseModel):
    farmer_id: str | None = None
    location: str
    crop: str
    candidate_crops: list[str] = Field(default_factory=list)
    expected_harvest_days: int = Field(ge=1, le=365)
    farm_size_hectares: float | None = Field(default=None, gt=0)
    labor_flexibility_pct: int = Field(default=25, ge=0, le=100)
    price_trend_hint: Literal["rising", "stable", "falling"] = "stable"
    weather_risk_level: RiskLevel = "medium"
    news_signals: list[str] = Field(default_factory=list)

    @field_validator("location")
    @classmethod
    def validate_location(cls, value: str) -> str:
        return normalize_malaysia_location(value)


class PriceObservation(BaseModel):
    observed_at: date
    price: float
    currency: str
    unit: str
    source: str
    market: str | None = None


class PriceSnapshot(BaseModel):
    crop: str
    region: str
    market: str | None = None
    source: str
    as_of: date
    current_price: PriceObservation | None = None
    history: list[PriceObservation] = Field(default_factory=list)
    direction: PriceDirection = "unknown"
    direction_basis: str
    notes: list[str] = Field(default_factory=list)


class WeatherCurrent(BaseModel):
    observed_at: datetime
    temperature_c: float | None = None
    apparent_temperature_c: float | None = None
    relative_humidity_pct: int | None = None
    is_day: bool | None = None
    precipitation_mm: float | None = None
    weather_code: int | None = None
    cloud_cover_pct: int | None = None
    pressure_msl_hpa: float | None = None
    surface_pressure_hpa: float | None = None
    wind_speed_10m_kph: float | None = None
    wind_direction_10m_deg: int | None = None
    wind_gusts_10m_kph: float | None = None


class WeatherForecastDay(BaseModel):
    date: date
    weather_code: int | None = None
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    precipitation_sum_mm: float | None = None
    precipitation_probability_max_pct: int | None = None
    wind_speed_10m_max_kph: float | None = None
    wind_gusts_10m_max_kph: float | None = None


class WeatherLocation(BaseModel):
    query: str
    name: str
    latitude: float
    longitude: float
    timezone: str
    country: str | None = None
    country_code: str | None = None
    admin1: str | None = None
    admin2: str | None = None
    admin3: str | None = None
    admin4: str | None = None


class WeatherSnapshot(BaseModel):
    source: str
    fetched_at: datetime
    resolved_location: WeatherLocation
    current: WeatherCurrent
    forecast: list[WeatherForecastDay] = Field(default_factory=list)
    units: dict[str, dict[str, str]] = Field(default_factory=dict)


class NewsSignal(BaseModel):
    title: str
    url: str
    source: str
    domain: str | None = None
    summary: str
    published_at: datetime | None = None
    language: str | None = None
    source_country: str | None = None
    crop: str
    region: str
    event_tags: list[str] = Field(default_factory=list)
    tone: float | None = None


class ScenarioComparison(BaseModel):
    crop: str
    score: float
    recommendation_bias: PriceOutlook
    rationale: str
    recommended_labor_shift_pct: int = Field(ge=0, le=100)


class EvidencePacket(BaseModel):
    price_signal: str
    weather_signal: str
    news_signal: str
    seasonal_weather_context: str | None = None
    price_snapshot: PriceSnapshot
    weather_snapshot: WeatherSnapshot | None = None
    news_signals: list[NewsSignal] = Field(default_factory=list)
    hedge_crop: str | None = None
    scenario_comparison: list[ScenarioComparison] = Field(default_factory=list)


class DecisionAnalysisResponse(BaseModel):
    decision: DecisionType
    price_outlook: PriceOutlook
    revenue_risk: RiskLevel
    confidence: float = Field(ge=0, le=1)
    summary: str
    reasons: list[str]
    actions: list[str]
    risks: list[str]
    evidence: EvidencePacket
    next_review_days: int = Field(ge=1, le=30)
