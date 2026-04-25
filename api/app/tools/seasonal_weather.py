from app.schemas.analysis import RiskLevel, WeatherSnapshot


def analyze_seasonal_context(
    weather_snapshot: WeatherSnapshot | None,
    *,
    expected_harvest_days: int,
) -> tuple[str, float, RiskLevel]:
    if weather_snapshot is None:
        return (
            "Seasonal weather context is unavailable because live forecast retrieval failed.",
            -0.05,
            "medium",
        )

    forecast_days = len(weather_snapshot.forecast)
    cumulative_rain = sum(day.precipitation_sum_mm or 0 for day in weather_snapshot.forecast)
    hottest_day = max(
        (day.temperature_max_c for day in weather_snapshot.forecast if day.temperature_max_c is not None),
        default=None,
    )

    if expected_harvest_days > forecast_days and cumulative_rain >= 35:
        return (
            "The harvest window extends beyond the live forecast horizon with a wet near-term pattern, so seasonal timing risk is elevated.",
            -0.15,
            "high",
        )
    if hottest_day is not None and hottest_day >= 34:
        return (
            "Near-term heat suggests added seasonal crop stress as the harvest window approaches.",
            -0.1,
            "medium",
        )
    return (
        "Seasonal timing looks manageable relative to the current harvest window.",
        0.05,
        "low",
    )
