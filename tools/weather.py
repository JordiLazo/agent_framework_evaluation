"""Weather forecast tool backed by Open-Meteo (free, no API key)."""

from __future__ import annotations

import datetime as dt

import httpx
from langchain_core.tools import tool

from tools.http import UpstreamError, get_json
from tools.schemas import (
    DailyForecast,
    ResolvedLocation,
    ToolError,
    WeatherForecastInput,
    WeatherForecastResult,
)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_FORECAST_DAYS = 16  # Open-Meteo horizon, today included
DEFAULT_WINDOW_DAYS = 7

# WMO weather interpretation codes -> short description (https://open-meteo.com/en/docs)
WMO_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _error(code: str, message: str) -> WeatherForecastResult:
    return WeatherForecastResult(status="error", error=ToolError(code=code, message=message))


def geocode(city: str) -> ResolvedLocation | None:
    """Resolve 'City[, Country]' to coordinates, preferring the country hint when given."""
    name, _, country_hint = (part.strip() for part in city.partition(","))
    payload = get_json(GEOCODING_URL, {"name": name, "count": 10, "language": "en", "format": "json"})
    candidates = payload.get("results") or []
    if not candidates:
        return None
    if country_hint:
        hint = country_hint.lower()
        matching = [
            c
            for c in candidates
            if hint in {(c.get("country") or "").lower(), (c.get("country_code") or "").lower()}
        ]
        candidates = matching or candidates
    best = candidates[0]  # Open-Meteo already ranks by relevance/population
    return ResolvedLocation(
        name=best["name"],
        country=best.get("country"),
        country_code=best.get("country_code"),
        admin1=best.get("admin1"),
        latitude=best["latitude"],
        longitude=best["longitude"],
        timezone=best.get("timezone"),
    )


def get_weather_forecast_impl(
    city: str,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    *,
    today: dt.date | None = None,
) -> WeatherForecastResult:
    today = today or dt.date.today()
    start = start_date or today
    end = end_date or (start + dt.timedelta(days=DEFAULT_WINDOW_DAYS - 1))
    horizon = today + dt.timedelta(days=MAX_FORECAST_DAYS - 1)

    # Validate dates locally: cheaper and clearer than letting the upstream API reject them.
    if end < start:
        return _error("invalid_date_range", "end_date must be on or after start_date.")
    if start < today:
        return _error(
            "date_in_past",
            f"start_date {start} is in the past; this tool only returns forecasts from {today}.",
        )
    if start > horizon:
        return _error(
            "out_of_forecast_range",
            f"Forecasts are only available until {horizon} ({MAX_FORECAST_DAYS} days ahead). "
            "For later trips, describe typical seasonal weather instead (e.g. via web search).",
        )
    end = min(end, horizon)

    try:
        location = geocode(city)
        if location is None:
            return _error(
                "location_not_found",
                f"Could not find a place called '{city}'. Ask the user to clarify the city/country.",
            )
        payload = get_json(
            FORECAST_URL,
            {
                "latitude": location.latitude,
                "longitude": location.longitude,
                "daily": ",".join(
                    [
                        "weather_code",
                        "temperature_2m_max",
                        "temperature_2m_min",
                        "precipitation_probability_max",
                        "precipitation_sum",
                        "wind_speed_10m_max",
                    ]
                ),
                "timezone": "auto",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )
    except (UpstreamError, httpx.HTTPError) as exc:
        return _error("upstream_unavailable", f"Weather service unavailable: {exc}")

    daily = payload.get("daily") or {}

    def col(key: str, i: int):
        values = daily.get(key) or []
        return values[i] if i < len(values) else None

    days = [
        DailyForecast(
            date=dt.date.fromisoformat(day),
            weather_code=col("weather_code", i),
            summary=WMO_CODES.get(col("weather_code", i), "Unknown"),
            temperature_max_c=col("temperature_2m_max", i),
            temperature_min_c=col("temperature_2m_min", i),
            precipitation_probability_max_pct=col("precipitation_probability_max", i),
            precipitation_sum_mm=col("precipitation_sum", i),
            wind_speed_max_kmh=col("wind_speed_10m_max", i),
        )
        for i, day in enumerate(daily.get("time") or [])
    ]
    return WeatherForecastResult(status="ok", location=location, days=days)


@tool(
    "get_weather_forecast",
    args_schema=WeatherForecastInput,
    response_format="content_and_artifact",
)
def get_weather_forecast(
    city: str, start_date: dt.date | None = None, end_date: dt.date | None = None
) -> tuple[str, dict]:
    """Get the daily weather forecast (temperatures, rain probability, wind) for a destination
    city for specific dates within the next 15 days. Use it for questions like 'what's the
    weather in Rome next weekend?', 'should I pack an umbrella for Lisbon?' or when planning
    outdoor activities. Returns structured JSON; temperatures are in Celsius."""
    result = get_weather_forecast_impl(city, start_date, end_date)
    return result.model_dump_json(exclude_none=True), result.model_dump(mode="json")
