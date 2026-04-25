import asyncio
from datetime import date, timedelta

from app.clients.glm import GLMClientError, GLMDecisionClient
from app.clients.news import CompositeNewsClient, FirecrawlNewsClient, GDELTNewsClient, NewsClientError, NewsSearchRequest, NewsSearchResponse
from app.clients.prices import (
    CompositePriceClient,
    FAOSTATPriceClientStub,
    FirecrawlPriceClient,
    LocalFallbackPriceClient,
    NormalizedPriceData,
    PriceObservation as ClientPriceObservation,
    PriceRequest,
)
from app.clients.weather import OpenMeteoWeatherClient, WeatherClientError, WeatherReport
from app.schemas.analysis import (
    DecisionAnalysisRequest,
    DecisionAnalysisResponse,
    EvidencePacket,
    NewsSignal,
    PriceObservation,
    PriceOutlook,
    PriceSnapshot,
    RiskLevel,
    ScenarioComparison,
    WeatherCurrent,
    WeatherForecastDay,
    WeatherLocation,
    WeatherSnapshot,
)
from app.tools.news_signal import analyze_news_signal
from app.tools.price_analysis import analyze_price_signal
from app.tools.scenario_compare import build_scenario_comparison, select_hedge_crop
from app.tools.seasonal_weather import analyze_seasonal_context
from app.tools.weather_risk import analyze_weather_signal


class DecisionOrchestrator:
    def __init__(
        self,
        weather_client: OpenMeteoWeatherClient | None = None,
        news_client: CompositeNewsClient | None = None,
        glm_client: GLMDecisionClient | None = None,
    ) -> None:
        self.weather_client = weather_client or OpenMeteoWeatherClient()
        self.news_client = news_client or CompositeNewsClient(
            primary=GDELTNewsClient(),
            fallback=FirecrawlNewsClient()
        )
        self.glm_client = glm_client or GLMDecisionClient()

    async def run(self, payload: DecisionAnalysisRequest) -> DecisionAnalysisResponse:
        weather_result, news_result, price_data = await asyncio.gather(
            self._fetch_weather(payload.location),
            self._fetch_news(payload),
            self._fetch_prices(payload),
        )

        weather_snapshot = self._weather_snapshot_from_report(weather_result)
        news_signals = self._news_signals_from_response(news_result)
        price_snapshot = self._price_snapshot_from_data(price_data)

        price_message, price_score, price_outlook, price_risk = analyze_price_signal(
            price_snapshot,
            fallback_direction=payload.price_trend_hint,
        )
        weather_message, weather_score, weather_risk = analyze_weather_signal(
            weather_snapshot,
            fallback_risk=payload.weather_risk_level,
        )
        seasonal_message, seasonal_score, _seasonal_risk = analyze_seasonal_context(
            weather_snapshot,
            expected_harvest_days=payload.expected_harvest_days,
        )
        news_message, news_score = analyze_news_signal(news_signals)
        scenario_comparison = build_scenario_comparison(
            payload,
            price_outlook=price_outlook,
            market_score=price_score,
            weather_score=weather_score + seasonal_score,
        )

        if weather_result is None:
            weather_message = f"{weather_message} Weather lookup for {payload.location} was unavailable."
        if news_result is None:
            news_message = "Regional news lookup was unavailable, so event risk is treated conservatively."
        if not price_snapshot.history:
            price_message = (
                f"{price_message} Stub price data was used for {payload.crop} in {payload.location}."
            )

        hedge_crop = select_hedge_crop(payload, scenario_comparison)
        evidence = EvidencePacket(
            price_signal=price_message,
            weather_signal=weather_message,
            news_signal=news_message,
            seasonal_weather_context=seasonal_message,
            price_snapshot=price_snapshot,
            weather_snapshot=weather_snapshot,
            news_signals=news_signals,
            hedge_crop=hedge_crop,
            scenario_comparison=scenario_comparison,
        )

        glm_response = await self.glm_client.analyze(payload, evidence)
        return glm_response.model_copy(update={"evidence": evidence})

    def _fallback_recommendation(
        self,
        *,
        payload: DecisionAnalysisRequest,
        evidence: EvidencePacket,
        price_score: float,
        weather_score: float,
        news_score: float,
        price_outlook: PriceOutlook,
        price_risk: RiskLevel,
        weather_risk: RiskLevel,
    ) -> DecisionAnalysisResponse:
        total_score = price_score + weather_score + news_score
        revenue_risk = self._select_revenue_risk(
            price_risk=price_risk,
            weather_risk=weather_risk,
            total_score=total_score,
        )

        if total_score <= -0.5 and payload.expected_harvest_days <= 21:
            decision = "harvest_early"
            summary = (
                f"Advance harvest timing for {payload.crop} to protect revenue against a weaker operating window."
            )
            actions = [
                f"Bring forward harvest planning for {payload.crop}.",
                "Prioritize near-term buyers and shorter logistics routes.",
                "Re-check price and weather signals within 3 to 5 days.",
            ]
            next_review = 4
        elif total_score <= -0.2 and evidence.hedge_crop:
            decision = "pivot_partially"
            summary = (
                f"Keep core production in {payload.crop} but shift a controlled share toward {evidence.hedge_crop}."
            )
            actions = [
                f"Protect the current {payload.crop} plan on the most reliable acreage.",
                f"Shift up to {payload.labor_flexibility_pct}% of flexible labor toward {evidence.hedge_crop}.",
                "Refresh weather, price, and regional news signals weekly.",
            ]
            next_review = 7
        else:
            decision = "persevere"
            summary = (
                f"Stay with {payload.crop}, while monitoring the price window and near-term regional risks."
            )
            actions = [
                f"Continue with the planned {payload.crop} cycle.",
                "Monitor district news and forecast updates for fast-moving disruption signals.",
                "Review again before the next key field operation.",
            ]
            next_review = 10

        confidence = min(max(0.55 + abs(total_score) * 0.35, 0.55), 0.85)

        return DecisionAnalysisResponse(
            decision=decision,
            price_outlook=price_outlook,
            revenue_risk=revenue_risk,
            confidence=round(confidence, 2),
            summary=summary,
            reasons=[
                evidence.price_signal,
                evidence.weather_signal,
                evidence.news_signal,
                evidence.seasonal_weather_context or "Seasonal weather context was unavailable.",
            ],
            actions=actions,
            risks=[
                "GLM reasoning was unavailable, so a deterministic fallback policy was used.",
                "External source coverage may be sparse or uneven for some regions.",
                "News and weather conditions can shift quickly as new information arrives.",
            ],
            evidence=evidence,
            next_review_days=next_review,
        )

    async def _fetch_weather(self, location: str) -> WeatherReport | None:
        try:
            return await self.weather_client.get_weather(location)
        except WeatherClientError:
            return None

    async def _fetch_news(self, payload: DecisionAnalysisRequest) -> NewsSearchResponse | None:
        try:
            return await self.news_client.search(
                NewsSearchRequest(
                    crop=payload.crop,
                    region=payload.location,
                    country="Malaysia",
                    extra_terms=tuple(payload.news_signals),
                )
            )
        except NewsClientError:
            return None

    async def _fetch_prices(self, payload: DecisionAnalysisRequest) -> NormalizedPriceData:
        return await self._build_price_client(payload).fetch_prices(
            PriceRequest(
                crop=payload.crop,
                region=payload.location,
            )
        )

    def _build_price_client(self, payload: DecisionAnalysisRequest) -> CompositePriceClient:
        seeded_history = {
            (
                payload.crop.strip().casefold(),
                payload.location.strip().casefold(),
                None,
            ): self._generate_stub_price_history(
                payload.crop,
                payload.location,
                payload.price_trend_hint,
            ),
            (
                payload.crop.strip().casefold(),
                "*",
                None,
            ): self._generate_stub_price_history(
                payload.crop,
                payload.location,
                payload.price_trend_hint,
            ),
        }
        return CompositePriceClient(
            primary=FAOSTATPriceClientStub(),
            fallback=FirecrawlPriceClient(),
            secondary_fallback=LocalFallbackPriceClient(seeded_history=seeded_history),
        )

    def _generate_stub_price_history(
        self,
        crop: str,
        region: str,
        direction_hint: str,
    ) -> list[ClientPriceObservation]:
        base_price = 180 + (sum(ord(char) for char in f"{crop}:{region}") % 90)
        multipliers = {
            "falling": [1.12, 1.08, 1.04, 1.0, 0.96, 0.93],
            "rising": [0.9, 0.94, 0.98, 1.02, 1.06, 1.1],
            "stable": [1.0, 1.01, 0.99, 1.0, 1.01, 1.0],
        }
        series = multipliers.get(direction_hint, multipliers["stable"])
        today = date.today()
        history: list[ClientPriceObservation] = []

        for index, multiplier in enumerate(series):
            history.append(
                ClientPriceObservation(
                    observed_at=today - timedelta(days=(len(series) - index - 1) * 30),
                    price=round(base_price * multiplier, 2),
                    currency="USD",
                    unit="tonne",
                    source="local_stub",
                    market=None,
                )
            )
        return history

    def _price_snapshot_from_data(self, data: NormalizedPriceData) -> PriceSnapshot:
        current_price = None
        if data.current_price is not None:
            current_price = PriceObservation(
                observed_at=data.current_price.observed_at,
                price=data.current_price.price,
                currency=data.current_price.currency,
                unit=data.current_price.unit,
                source=data.current_price.source,
                market=data.current_price.market,
            )

        return PriceSnapshot(
            crop=data.crop,
            region=data.region,
            market=data.market,
            source=data.source,
            as_of=data.as_of,
            current_price=current_price,
            history=[
                PriceObservation(
                    observed_at=point.observed_at,
                    price=point.price,
                    currency=point.currency,
                    unit=point.unit,
                    source=point.source,
                    market=point.market,
                )
                for point in data.history
            ],
            direction=data.direction,
            direction_basis=data.direction_basis,
            notes=data.notes,
        )

    def _weather_snapshot_from_report(self, report: WeatherReport | None) -> WeatherSnapshot | None:
        if report is None:
            return None

        return WeatherSnapshot(
            source=report.source,
            fetched_at=report.fetched_at,
            resolved_location=WeatherLocation(
                query=report.resolved_location.query,
                name=report.resolved_location.name,
                latitude=report.resolved_location.latitude,
                longitude=report.resolved_location.longitude,
                timezone=report.resolved_location.timezone,
                country=report.resolved_location.country,
                country_code=report.resolved_location.country_code,
                admin1=report.resolved_location.admin1,
                admin2=report.resolved_location.admin2,
                admin3=report.resolved_location.admin3,
                admin4=report.resolved_location.admin4,
            ),
            current=WeatherCurrent(
                observed_at=report.current.observed_at,
                temperature_c=report.current.temperature_c,
                apparent_temperature_c=report.current.apparent_temperature_c,
                relative_humidity_pct=report.current.relative_humidity_pct,
                is_day=report.current.is_day,
                precipitation_mm=report.current.precipitation_mm,
                weather_code=report.current.weather_code,
                cloud_cover_pct=report.current.cloud_cover_pct,
                pressure_msl_hpa=report.current.pressure_msl_hpa,
                surface_pressure_hpa=report.current.surface_pressure_hpa,
                wind_speed_10m_kph=report.current.wind_speed_10m_kph,
                wind_direction_10m_deg=report.current.wind_direction_10m_deg,
                wind_gusts_10m_kph=report.current.wind_gusts_10m_kph,
            ),
            forecast=[
                WeatherForecastDay(
                    date=day.date,
                    weather_code=day.weather_code,
                    temperature_max_c=day.temperature_max_c,
                    temperature_min_c=day.temperature_min_c,
                    precipitation_sum_mm=day.precipitation_sum_mm,
                    precipitation_probability_max_pct=day.precipitation_probability_max_pct,
                    wind_speed_10m_max_kph=day.wind_speed_10m_max_kph,
                    wind_gusts_10m_max_kph=day.wind_gusts_10m_max_kph,
                )
                for day in report.forecast
            ],
            units={
                "current": report.units.current,
                "daily": report.units.daily,
            },
        )

    def _news_signals_from_response(self, response: NewsSearchResponse | None) -> list[NewsSignal]:
        if response is None:
            return []

        return [
            NewsSignal(
                title=item.title,
                url=item.url,
                source=item.source,
                domain=item.domain,
                summary=item.summary,
                published_at=item.published_at,
                language=item.language,
                source_country=item.source_country,
                crop=item.crop,
                region=item.region,
                event_tags=list(item.event_tags),
                tone=item.tone,
            )
            for item in response.items
        ]

    def _select_revenue_risk(
        self,
        *,
        price_risk: RiskLevel,
        weather_risk: RiskLevel,
        total_score: float,
    ) -> RiskLevel:
        if "high" in {price_risk, weather_risk} or total_score <= -0.45:
            return "high"
        if "medium" in {price_risk, weather_risk} or total_score <= -0.1:
            return "medium"
        return "low"

    async def compare(self, payload: DecisionAnalysisRequest) -> list[ScenarioComparison]:
        weather_result = await self._fetch_weather(payload.location)
        weather_snapshot = self._weather_snapshot_from_report(weather_result)
        price_data = await self._fetch_prices(payload)
        price_snapshot = self._price_snapshot_from_data(price_data)
        _, price_score, price_outlook, _ = analyze_price_signal(
            price_snapshot,
            fallback_direction=payload.price_trend_hint,
        )
        _, weather_score, _ = analyze_weather_signal(
            weather_snapshot,
            fallback_risk=payload.weather_risk_level,
        )
        seasonal_message, seasonal_score, _ = analyze_seasonal_context(
            weather_snapshot,
            expected_harvest_days=payload.expected_harvest_days,
        )
        scenarios = build_scenario_comparison(
            payload,
            price_outlook=price_outlook,
            market_score=price_score,
            weather_score=weather_score + seasonal_score,
        )
        if seasonal_message and scenarios:
            scenarios[0] = scenarios[0].model_copy(
                update={
                    "rationale": f"{scenarios[0].rationale} {seasonal_message}",
                }
            )
        return scenarios
