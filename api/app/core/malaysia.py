from __future__ import annotations

import re


MALAYSIA_CANONICAL = "Malaysia"

_REGION_ALIASES: dict[str, tuple[str, ...]] = {
    "Johor": ("johor", "johor bahru", "jb", "muar", "batu pahat", "kluang", "segamat"),
    "Kedah": ("kedah", "alor setar", "sungai petani", "kulim", "langkawi"),
    "Kelantan": ("kelantan", "kota bharu", "tanah merah", "pasir mas"),
    "Melaka": ("melaka", "malacca", "ayer keroh", "jasin", "alor gajah"),
    "Negeri Sembilan": ("negeri sembilan", "seremban", "port dickson", "nilai"),
    "Pahang": ("pahang", "kuantan", "temerloh", "bentong", "cameron highlands"),
    "Perak": ("perak", "ipoh", "taiping", "teluk intan", "sitiawan"),
    "Perlis": ("perlis", "kangar", "padang besar", "arau"),
    "Penang": ("penang", "pulau pinang", "george town", "butterworth", "seberang perai"),
    "Sabah": ("sabah", "kota kinabalu", "sandakan", "tawau", "lahad datu", "kundasang"),
    "Sarawak": ("sarawak", "kuching", "sibu", "miri", "bintulu"),
    "Selangor": ("selangor", "shah alam", "klang", "kajang", "subang jaya", "sabak bernam"),
    "Terengganu": ("terengganu", "kuala terengganu", "besut", "kemaman", "dungun"),
    "Kuala Lumpur": ("kuala lumpur", "kl"),
    "Putrajaya": ("putrajaya",),
    "Labuan": ("labuan",),
}

_COUNTRY_ALIASES = ("malaysia", "malaysian")
_NORMALIZE_SPACES = re.compile(r"\s+")


def normalize_malaysia_location(value: str) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        raise ValueError("location must not be empty")
    if not is_malaysia_relevant_location(cleaned):
        raise ValueError(
            "Provide a Malaysian location such as a district, town, or state in Malaysia."
        )
    if _mentions_malaysia(cleaned):
        return cleaned
    return f"{cleaned}, {MALAYSIA_CANONICAL}"


def is_malaysia_relevant_location(value: str) -> bool:
    lowered = _normalize_for_match(value)
    if any(alias == lowered or f" {alias} " in f" {lowered} " for alias in _COUNTRY_ALIASES):
        return True
    return any(
        alias == lowered or f" {alias} " in f" {lowered} "
        for aliases in _REGION_ALIASES.values()
        for alias in aliases
    )


def malaysia_region_terms(value: str) -> list[str]:
    normalized = normalize_malaysia_location(value)
    region_name = identify_malaysia_region(normalized)
    terms: list[str] = [normalized]
    if region_name:
        terms.append(region_name)
        terms.extend(_REGION_ALIASES[region_name])
    terms.extend((MALAYSIA_CANONICAL, "Malaysian"))
    return _dedupe_terms(terms)


def identify_malaysia_region(value: str) -> str | None:
    lowered = _normalize_for_match(value)
    for canonical, aliases in _REGION_ALIASES.items():
        for alias in aliases:
            if alias == lowered or f" {alias} " in f" {lowered} ":
                return canonical
    return None


def malaysia_location_hint() -> str:
    return "Use a Malaysian district, town, or state, for example Muar, Johor or Kota Bharu, Kelantan."


def _mentions_malaysia(value: str) -> bool:
    lowered = _normalize_for_match(value)
    return any(alias == lowered or f" {alias} " in f" {lowered} " for alias in _COUNTRY_ALIASES[:2])


def _normalize_for_match(value: str) -> str:
    lowered = _clean_text(value).casefold().replace(",", " ")
    return _NORMALIZE_SPACES.sub(" ", lowered)


def _clean_text(value: str) -> str:
    cleaned = _NORMALIZE_SPACES.sub(" ", value).strip(" \t\r\n,.;:")
    return cleaned


def _dedupe_terms(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result
