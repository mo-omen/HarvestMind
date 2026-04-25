from app.schemas.analysis import PriceOutlook, PriceSnapshot, RiskLevel


def analyze_price_signal(
    price_snapshot: PriceSnapshot,
    *,
    fallback_direction: str = "stable",
) -> tuple[str, float, PriceOutlook, RiskLevel]:
    direction = price_snapshot.direction
    if direction == "unknown":
        direction = fallback_direction

    current_price = price_snapshot.current_price
    current_fragment = ""
    if current_price is not None:
        current_fragment = (
            f" Current price is {current_price.price:.2f} "
            f"{current_price.currency}/{current_price.unit}."
        )

    if direction == "falling":
        return (
            "Price history points to softening market conditions into the harvest window."
            f"{current_fragment}",
            -0.45,
            "decrease",
            "high",
        )
    if direction == "rising":
        return (
            "Price history points to a supportive market trend into the harvest window."
            f"{current_fragment}",
            0.35,
            "increase",
            "low",
        )
    return (
        "Price history is broadly stable with limited directional edge."
        f"{current_fragment}",
        0.0,
        "stable",
        "medium",
    )
