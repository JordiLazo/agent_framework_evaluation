"""Pydantic contracts for the new tools' inputs and outputs.

Every new tool returns the same envelope::

    {"status": "ok" | "error", "error": {"code": ..., "message": ...} | null, "source": ..., ...}

Errors are returned as data instead of raised, for two reasons:
  * the LLM gets a machine-readable reason (e.g. ``out_of_forecast_range``) it can explain or
    recover from, rather than a stack trace;
  * downstream code (API clients, evaluators) can count successes and failures from
    ``status`` without parsing free text.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Status = Literal["ok", "error"]


class ToolError(BaseModel):
    code: str = Field(description="Stable machine-readable error code")
    message: str = Field(description="Human readable explanation and recovery hint")


# --------------------------------------------------------------------------- weather


class WeatherForecastInput(BaseModel):
    city: str = Field(
        min_length=2,
        description="City name, optionally followed by a comma and country, e.g. 'Paris, France' "
        "or 'Porto, PT'. Use the destination of the trip.",
    )
    start_date: dt.date | None = Field(
        default=None,
        description="First day of the forecast (YYYY-MM-DD). Defaults to today. "
        "Forecasts are only available up to 15 days ahead.",
    )
    end_date: dt.date | None = Field(
        default=None,
        description="Last day of the forecast (YYYY-MM-DD), inclusive. "
        "Defaults to start_date + 6 days.",
    )


class ResolvedLocation(BaseModel):
    name: str
    country: str | None = None
    country_code: str | None = None
    admin1: str | None = None
    latitude: float
    longitude: float
    timezone: str | None = None


class DailyForecast(BaseModel):
    date: dt.date
    summary: str = Field(description="Human readable condition derived from the WMO weather code")
    weather_code: int | None = None
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    precipitation_probability_max_pct: float | None = None
    precipitation_sum_mm: float | None = None
    wind_speed_max_kmh: float | None = None


class WeatherForecastResult(BaseModel):
    status: Status
    location: ResolvedLocation | None = None
    days: list[DailyForecast] = Field(default_factory=list)
    units: dict[str, str] = Field(
        default_factory=lambda: {"temperature": "celsius", "precipitation": "mm", "wind": "km/h"}
    )
    error: ToolError | None = None
    source: str = "open-meteo.com"


# --------------------------------------------------------------------------- currency


class CurrencyConversionInput(BaseModel):
    amount: float = Field(gt=0, description="Amount of money to convert, e.g. 150")
    from_currency: str = Field(description="ISO 4217 code of the source currency, e.g. 'USD'")
    to_currency: str = Field(description="ISO 4217 code of the target currency, e.g. 'EUR'")
    date: dt.date | None = Field(
        default=None,
        description="Optional historical date (YYYY-MM-DD). Omit for the latest reference rate.",
    )

    @field_validator("from_currency", "to_currency")
    @classmethod
    def _normalise_code(cls, value: str) -> str:
        code = value.strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError("currency must be a 3-letter ISO 4217 code such as USD, EUR, JPY")
        return code


class CurrencyConversionResult(BaseModel):
    status: Status
    amount: float | None = None
    from_currency: str | None = None
    to_currency: str | None = None
    rate: float | None = None
    converted_amount: float | None = None
    rate_date: dt.date | None = Field(
        default=None, description="Business day of the ECB reference rate actually used"
    )
    error: ToolError | None = None
    source: str = "frankfurter (European Central Bank reference rates)"
