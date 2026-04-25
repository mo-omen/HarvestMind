from app.schemas.analysis import (
    DecisionAnalysisRequest,
    PriceOutlook,
    ScenarioComparison,
)


def build_scenario_comparison(
    payload: DecisionAnalysisRequest,
    *,
    price_outlook: PriceOutlook,
    market_score: float,
    weather_score: float,
) -> list[ScenarioComparison]:
    scenarios: list[ScenarioComparison] = [
        ScenarioComparison(
            crop=payload.crop,
            score=round(market_score + weather_score, 2),
            recommendation_bias=price_outlook,
            rationale=_current_crop_rationale(payload.crop, price_outlook),
            recommended_labor_shift_pct=0,
        )
    ]

    diversification_bonus = 0.18 if price_outlook == "decrease" else 0.08
    labor_shift_pct = min(max(payload.labor_flexibility_pct, 0), 100)

    for candidate in payload.candidate_crops:
        crop_bonus = _stable_crop_bonus(candidate)
        scenario_score = market_score * -0.35 + weather_score * 0.5 + diversification_bonus + crop_bonus
        scenarios.append(
            ScenarioComparison(
                crop=candidate,
                score=round(scenario_score, 2),
                recommendation_bias="increase" if scenario_score >= 0.15 else "stable",
                rationale=(
                    f"{candidate} offers diversification against {payload.crop} and can absorb flexible labor if market pressure persists."
                ),
                recommended_labor_shift_pct=min(labor_shift_pct, 40 if scenario_score >= 0.2 else 20),
            )
        )

    return sorted(scenarios, key=lambda item: item.score, reverse=True)


def select_hedge_crop(payload: DecisionAnalysisRequest, scenarios: list[ScenarioComparison]) -> str | None:
    for scenario in scenarios:
        if scenario.crop != payload.crop:
            return scenario.crop
    return None


def _current_crop_rationale(crop: str, price_outlook: PriceOutlook) -> str:
    if price_outlook == "decrease":
        return f"{crop} remains viable, but price pressure weakens the case for keeping all effort concentrated there."
    if price_outlook == "increase":
        return f"{crop} has the strongest current market support in the available evidence."
    return f"{crop} remains the baseline option while monitoring for a clearer market edge."


def _stable_crop_bonus(crop: str) -> float:
    normalized = crop.strip().casefold()
    if not normalized:
        return 0.0
    return (sum(ord(char) for char in normalized) % 7) / 100
