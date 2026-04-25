from app.schemas.analysis import RiskLevel, WeatherSnapshot


def analyze_weather_signal(
    weather_snapshot: WeatherSnapshot | None,
    *,
    fallback_risk: RiskLevel = "medium",
) -> tuple[str, float, RiskLevel]:
    if weather_snapshot is None:
        if fallback_risk == "high":
            return ("Live weather data was unavailable; keep a defensive posture.", -0.2, "high")
        if fallback_risk == "low":
            return ("Live weather data was unavailable; existing field conditions appear manageable.", 0.1, "low")
        return ("Live weather data was unavailable; treat the weather outlook as uncertain.", -0.05, "medium")

    total_precipitation = sum(day.precipitation_sum_mm or 0 for day in weather_snapshot.forecast)
    peak_precip_probability = max(
        (day.precipitation_probability_max_pct or 0 for day in weather_snapshot.forecast),
        default=0,
    )
    peak_wind_gust = max(
        (day.wind_gusts_10m_max_kph or 0 for day in weather_snapshot.forecast),
        default=0.0,
    )

    if total_precipitation >= 40 or peak_precip_probability >= 75 or peak_wind_gust >= 55:
        return (
            "The 7-day forecast shows elevated disruption risk from precipitation or wind.",
            -0.35,
            "high",
        )
    if total_precipitation <= 10 and peak_precip_probability <= 35 and peak_wind_gust <= 30:
        return (
            "The 7-day forecast looks relatively steady for current operations.",
            0.2,
            "low",
        )
    return (
        "The 7-day forecast is workable but has enough uncertainty to warrant monitoring.",
        -0.05,
        "medium",
    )
