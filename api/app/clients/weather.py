from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Final

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.core.malaysia import MALAYSIA_CANONICAL, normalize_malaysia_location


GEOCODING_API_URL: Final[str] = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_API_URL: Final[str] = "https://api.open-meteo.com/v1/forecast"
DEFAULT_TIMEOUT_SECONDS: Final[float] = 15.0
DEFAULT_FORECAST_DAYS: Final[int] = 7

CURRENT_VARIABLES: Final[tuple[str, ...]] = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "is_day",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "pressure_msl",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
)

DAILY_VARIABLES: Final[tuple[str, ...]] = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
)


class WeatherClientError(RuntimeError):
    """Raised when Open-Meteo cannot resolve a location or return usable weather data."""

    def __init__(
        self,
        message: str,
        *,
        location_query: str | None = None,
        stage: str | None = None,
    ) -> None:
        super().__init__(message)
        self.location_query = location_query
        self.stage = stage


class WeatherLocationNotFoundError(WeatherClientError):
    """Raised when Open-Meteo geocoding does not return a matching location."""


class ResolvedLocation(BaseModel):
    model_config = ConfigDict(frozen=True)

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


class CurrentWeather(BaseModel):
    model_config = ConfigDict(frozen=True)

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


class DailyForecast(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    weather_code: int | None = None
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    precipitation_sum_mm: float | None = None
    precipitation_probability_max_pct: int | None = None
    wind_speed_10m_max_kph: float | None = None
    wind_gusts_10m_max_kph: float | None = None


class WeatherUnits(BaseModel):
    model_config = ConfigDict(frozen=True)

    current: dict[str, str] = Field(default_factory=dict)
    daily: dict[str, str] = Field(default_factory=dict)


class WeatherReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str = "open-meteo"
    fetched_at: datetime
    resolved_location: ResolvedLocation
    current: CurrentWeather
    forecast: list[DailyForecast]
    units: WeatherUnits = Field(default_factory=WeatherUnits)


class OpenMeteoWeatherClient:
    """Open-Meteo weather client with sync and async entry points."""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        geocoding_results: int = 1,
        language: str = "en",
    ) -> None:
        self._timeout = timeout
        self._geocoding_results = geocoding_results
        self._language = language

    async def get_weather(self, location: str) -> WeatherReport:
        query = _normalize_location_query(location)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resolved = await self._resolve_location_async(client, query)
            forecast_payload = await self._fetch_forecast_async(client, resolved)
        return _build_weather_report(query, resolved, forecast_payload)

    def get_weather_sync(self, location: str) -> WeatherReport:
        query = _normalize_location_query(location)
        with httpx.Client(timeout=self._timeout) as client:
            resolved = self._resolve_location_sync(client, query)
            forecast_payload = self._fetch_forecast_sync(client, resolved)
        return _build_weather_report(query, resolved, forecast_payload)

    async def _resolve_location_async(
        self,
        client: httpx.AsyncClient,
        location_query: str,
    ) -> ResolvedLocation:
        payload = await self._get_json_async(
            client,
            GEOCODING_API_URL,
            params={
                "name": location_query,
                "count": self._geocoding_results,
                "language": self._language,
                "format": "json",
            },
            location_query=location_query,
            stage="geocoding",
        )
        return _parse_resolved_location(payload, location_query)

    def _resolve_location_sync(
        self,
        client: httpx.Client,
        location_query: str,
    ) -> ResolvedLocation:
        payload = self._get_json_sync(
            client,
            GEOCODING_API_URL,
            params={
                "name": location_query,
                "count": self._geocoding_results,
                "language": self._language,
                "format": "json",
            },
            location_query=location_query,
            stage="geocoding",
        )
        return _parse_resolved_location(payload, location_query)

    async def _fetch_forecast_async(
        self,
        client: httpx.AsyncClient,
        location: ResolvedLocation,
    ) -> dict[str, Any]:
        return await self._get_json_async(
            client,
            FORECAST_API_URL,
            params=_forecast_params(location),
            location_query=location.query,
            stage="forecast",
        )

    def _fetch_forecast_sync(
        self,
        client: httpx.Client,
        location: ResolvedLocation,
    ) -> dict[str, Any]:
        return self._get_json_sync(
            client,
            FORECAST_API_URL,
            params=_forecast_params(location),
            location_query=location.query,
            stage="forecast",
        )

    async def _get_json_async(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, Any],
        location_query: str,
        stage: str,
    ) -> dict[str, Any]:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _http_error(exc, location_query=location_query, stage=stage) from exc
        except httpx.HTTPError as exc:
            raise WeatherClientError(
                f"Open-Meteo {stage} request failed for '{location_query}': {exc}",
                location_query=location_query,
                stage=stage,
            ) from exc
        return _decode_json_payload(response, location_query=location_query, stage=stage)

    def _get_json_sync(
        self,
        client: httpx.Client,
        url: str,
        *,
        params: dict[str, Any],
        location_query: str,
        stage: str,
    ) -> dict[str, Any]:
        try:
            response = client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _http_error(exc, location_query=location_query, stage=stage) from exc
        except httpx.HTTPError as exc:
            raise WeatherClientError(
                f"Open-Meteo {stage} request failed for '{location_query}': {exc}",
                location_query=location_query,
                stage=stage,
            ) from exc
        return _decode_json_payload(response, location_query=location_query, stage=stage)


async def fetch_weather(location: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> WeatherReport:
    return await OpenMeteoWeatherClient(timeout=timeout).get_weather(location)


def fetch_weather_sync(location: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> WeatherReport:
    return OpenMeteoWeatherClient(timeout=timeout).get_weather_sync(location)


def _forecast_params(location: ResolvedLocation) -> dict[str, Any]:
    return {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "timezone": location.timezone,
        "forecast_days": DEFAULT_FORECAST_DAYS,
        "current": ",".join(CURRENT_VARIABLES),
        "daily": ",".join(DAILY_VARIABLES),
    }


def _build_weather_report(
    location_query: str,
    resolved_location: ResolvedLocation,
    payload: dict[str, Any],
) -> WeatherReport:
    current_payload = _expect_mapping(payload.get("current"), location_query=location_query, stage="forecast")
    daily_payload = _expect_mapping(payload.get("daily"), location_query=location_query, stage="forecast")
    current = _parse_current_weather(current_payload, location_query=location_query)
    forecast = _parse_daily_forecast(daily_payload, location_query=location_query)

    return WeatherReport(
        fetched_at=datetime.now(UTC),
        resolved_location=resolved_location,
        current=current,
        forecast=forecast,
        units=WeatherUnits(
            current=_parse_units(payload.get("current_units")),
            daily=_parse_units(payload.get("daily_units")),
        ),
    )


def _parse_resolved_location(payload: dict[str, Any], location_query: str) -> ResolvedLocation:
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise WeatherLocationNotFoundError(
            f"Open-Meteo could not resolve location '{location_query}'.",
            location_query=location_query,
            stage="geocoding",
        )

    malaysian_result = next(
        (
            _expect_mapping(item, location_query=location_query, stage="geocoding")
            for item in results
            if isinstance(item, dict)
            and str(item.get("country_code") or "").strip().upper() == "MY"
        ),
        None,
    )
    if malaysian_result is None:
        raise WeatherLocationNotFoundError(
            f"Open-Meteo did not return a Malaysian match for '{location_query}'.",
            location_query=location_query,
            stage="geocoding",
        )

    top_result = malaysian_result
    name = _require_string(top_result, "name", location_query=location_query, stage="geocoding")
    latitude = _require_float(top_result, "latitude", location_query=location_query, stage="geocoding")
    longitude = _require_float(top_result, "longitude", location_query=location_query, stage="geocoding")
    timezone_name = _require_string(top_result, "timezone", location_query=location_query, stage="geocoding")

    return ResolvedLocation(
        query=location_query,
        name=name,
        latitude=latitude,
        longitude=longitude,
        timezone=timezone_name,
        country=_optional_string(top_result, "country"),
        country_code=_optional_string(top_result, "country_code"),
        admin1=_optional_string(top_result, "admin1"),
        admin2=_optional_string(top_result, "admin2"),
        admin3=_optional_string(top_result, "admin3"),
        admin4=_optional_string(top_result, "admin4"),
    )


def _parse_current_weather(payload: dict[str, Any], *, location_query: str) -> CurrentWeather:
    observed_at_raw = _require_string(payload, "time", location_query=location_query, stage="forecast")
    return CurrentWeather(
        observed_at=_parse_datetime(observed_at_raw, location_query=location_query, stage="forecast"),
        temperature_c=_optional_float(payload, "temperature_2m"),
        apparent_temperature_c=_optional_float(payload, "apparent_temperature"),
        relative_humidity_pct=_optional_int(payload, "relative_humidity_2m"),
        is_day=_optional_bool_from_int(payload, "is_day"),
        precipitation_mm=_optional_float(payload, "precipitation"),
        weather_code=_optional_int(payload, "weather_code"),
        cloud_cover_pct=_optional_int(payload, "cloud_cover"),
        pressure_msl_hpa=_optional_float(payload, "pressure_msl"),
        surface_pressure_hpa=_optional_float(payload, "surface_pressure"),
        wind_speed_10m_kph=_optional_float(payload, "wind_speed_10m"),
        wind_direction_10m_deg=_optional_int(payload, "wind_direction_10m"),
        wind_gusts_10m_kph=_optional_float(payload, "wind_gusts_10m"),
    )


def _parse_daily_forecast(payload: dict[str, Any], *, location_query: str) -> list[DailyForecast]:
    raw_dates = payload.get("time")
    if not isinstance(raw_dates, list) or not raw_dates:
        raise WeatherClientError(
            f"Open-Meteo forecast response did not include daily time values for '{location_query}'.",
            location_query=location_query,
            stage="forecast",
        )

    forecast: list[DailyForecast] = []
    for index, raw_date in enumerate(raw_dates[:DEFAULT_FORECAST_DAYS]):
        if not isinstance(raw_date, str) or not raw_date:
            raise WeatherClientError(
                f"Open-Meteo forecast returned an invalid daily date for '{location_query}'.",
                location_query=location_query,
                stage="forecast",
            )
        forecast.append(
            DailyForecast(
                date=_parse_date(raw_date, location_query=location_query, stage="forecast"),
                weather_code=_optional_series_int(payload, "weather_code", index),
                temperature_max_c=_optional_series_float(payload, "temperature_2m_max", index),
                temperature_min_c=_optional_series_float(payload, "temperature_2m_min", index),
                precipitation_sum_mm=_optional_series_float(payload, "precipitation_sum", index),
                precipitation_probability_max_pct=_optional_series_int(
                    payload,
                    "precipitation_probability_max",
                    index,
                ),
                wind_speed_10m_max_kph=_optional_series_float(payload, "wind_speed_10m_max", index),
                wind_gusts_10m_max_kph=_optional_series_float(payload, "wind_gusts_10m_max", index),
            )
        )
    return forecast


def _decode_json_payload(
    response: httpx.Response,
    *,
    location_query: str,
    stage: str,
) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise WeatherClientError(
            f"Open-Meteo {stage} response for '{location_query}' was not valid JSON.",
            location_query=location_query,
            stage=stage,
        ) from exc

    mapping = _expect_mapping(payload, location_query=location_query, stage=stage)
    if mapping.get("error") is True:
        reason = mapping.get("reason")
        message = reason if isinstance(reason, str) and reason else f"Open-Meteo {stage} request failed."
        raise WeatherClientError(message, location_query=location_query, stage=stage)
    return mapping


def _http_error(
    exc: httpx.HTTPStatusError,
    *,
    location_query: str,
    stage: str,
) -> WeatherClientError:
    reason = _extract_error_reason(exc.response)
    status_code = exc.response.status_code
    detail = reason or exc.response.text.strip() or "unexpected API error"
    return WeatherClientError(
        f"Open-Meteo {stage} request failed for '{location_query}' with HTTP {status_code}: {detail}",
        location_query=location_query,
        stage=stage,
    )


def _extract_error_reason(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict):
        reason = payload.get("reason")
        if isinstance(reason, str) and reason.strip():
            return reason.strip()
    return None


def _parse_units(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(unit) for key, unit in value.items() if isinstance(unit, str)}


def _normalize_location_query(location: str) -> str:
    try:
        return normalize_malaysia_location(location)
    except ValueError as exc:
        raise WeatherClientError(
            f"{exc} The supported geography for this app is {MALAYSIA_CANONICAL}.",
            stage="input",
        ) from exc


def _expect_mapping(value: Any, *, location_query: str, stage: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WeatherClientError(
            f"Open-Meteo {stage} response for '{location_query}' was not an object.",
            location_query=location_query,
            stage=stage,
        )
    return value


def _require_string(
    mapping: dict[str, Any],
    key: str,
    *,
    location_query: str,
    stage: str,
) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WeatherClientError(
            f"Open-Meteo {stage} response for '{location_query}' did not include '{key}'.",
            location_query=location_query,
            stage=stage,
        )
    return value


def _require_float(
    mapping: dict[str, Any],
    key: str,
    *,
    location_query: str,
    stage: str,
) -> float:
    value = _optional_float(mapping, key)
    if value is None:
        raise WeatherClientError(
            f"Open-Meteo {stage} response for '{location_query}' did not include '{key}'.",
            location_query=location_query,
            stage=stage,
        )
    return value


def _optional_string(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _optional_float(mapping: dict[str, Any], key: str) -> float | None:
    value = mapping.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _optional_int(mapping: dict[str, Any], key: str) -> int | None:
    value = mapping.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _optional_bool_from_int(mapping: dict[str, Any], key: str) -> bool | None:
    value = _optional_int(mapping, key)
    if value is None:
        return None
    return value == 1


def _optional_series_float(mapping: dict[str, Any], key: str, index: int) -> float | None:
    return _coerce_float(_optional_series_value(mapping, key, index))


def _optional_series_int(mapping: dict[str, Any], key: str, index: int) -> int | None:
    return _coerce_int(_optional_series_value(mapping, key, index))


def _optional_series_value(mapping: dict[str, Any], key: str, index: int) -> Any:
    series = mapping.get(key)
    if not isinstance(series, list) or index >= len(series):
        return None
    return series[index]


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _parse_datetime(value: str, *, location_query: str, stage: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WeatherClientError(
            f"Open-Meteo {stage} response contained an invalid datetime for '{location_query}': {value}",
            location_query=location_query,
            stage=stage,
        ) from exc


def _parse_date(value: str, *, location_query: str, stage: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise WeatherClientError(
            f"Open-Meteo {stage} response contained an invalid date for '{location_query}': {value}",
            location_query=location_query,
            stage=stage,
        ) from exc


__all__ = [
    "CurrentWeather",
    "DailyForecast",
    "OpenMeteoWeatherClient",
    "ResolvedLocation",
    "WeatherClientError",
    "WeatherLocationNotFoundError",
    "WeatherReport",
    "WeatherUnits",
    "fetch_weather",
    "fetch_weather_sync",
]
