from app.schemas.analysis import NewsSignal


NEGATIVE_TAGS = {"supply_shock", "weather_risk", "pest_disease", "logistics"}
POSITIVE_TAGS = {"policy_support", "demand_shift", "price_signal"}


def analyze_news_signal(news_signals: list[NewsSignal]) -> tuple[str, float]:
    if not news_signals:
        return ("Regional news coverage is limited, so event risk is inconclusive.", 0.0)

    negative_hits = 0
    positive_hits = 0
    average_tone = 0.0
    tone_count = 0

    for item in news_signals:
        tags = set(item.event_tags)
        if tags & NEGATIVE_TAGS:
            negative_hits += 1
        if tags & POSITIVE_TAGS:
            positive_hits += 1
        if item.tone is not None:
            average_tone += item.tone
            tone_count += 1

    tone = average_tone / tone_count if tone_count else 0.0

    if negative_hits > positive_hits or tone < -1.5:
        return ("Regional news is tilting toward operational or market downside risk.", -0.35)
    if positive_hits > negative_hits and tone > 0:
        return ("Regional news includes supportive demand or policy signals.", 0.2)
    return ("Regional news is mixed and does not point to a dominant directional signal.", -0.05)
