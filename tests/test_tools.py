"""Unit tests for the Step 2 tools. HTTP is mocked with respx: no network needed."""

import datetime as dt
import json

import httpx
import pytest
import respx

from tools.currency import FRANKFURTER_URL, convert_currency, convert_currency_impl
from tools.schemas import CurrencyConversionInput
from tools.weather import (
    FORECAST_URL,
    GEOCODING_URL,
    get_weather_forecast,
    get_weather_forecast_impl,
)

TODAY = dt.date(2026, 10, 26)

GEO = {
    "results": [
        {"name": "Paris", "country": "United States", "country_code": "US",
         "latitude": 33.6, "longitude": -95.5},
        {"name": "Paris", "country": "France", "country_code": "FR",
         "latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"},
    ]
}
FORECAST = {
    "daily": {
        "time": ["2026-10-27", "2026-10-28"],
        "weather_code": [3, 61],
        "temperature_2m_max": [15.1, 13.0],
        "temperature_2m_min": [8.0, 7.5],
        "precipitation_probability_max": [10, 80],
        "precipitation_sum": [0.0, 4.2],
        "wind_speed_10m_max": [12.0, 20.5],
    }
}


def rates(base, target, rate):
    return {"amount": 1.0, "base": base, "date": "2026-10-23", "rates": {target: rate}}


# --------------------------------------------------------------------------- weather


@respx.mock
def test_weather_happy_path_uses_country_hint():
    respx.get(GEOCODING_URL).mock(return_value=httpx.Response(200, json=GEO))
    forecast = respx.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=FORECAST))

    result = get_weather_forecast_impl(
        "Paris, France", dt.date(2026, 10, 27), dt.date(2026, 10, 28), today=TODAY
    )

    assert result.status == "ok"
    assert result.location.country_code == "FR"
    assert forecast.calls.last.request.url.params["latitude"] == "48.85"
    assert [d.summary for d in result.days] == ["Overcast", "Slight rain"]
    assert result.days[1].precipitation_probability_max_pct == 80


def test_weather_out_of_range_is_a_structured_error():
    result = get_weather_forecast_impl("Paris", dt.date(2027, 3, 15), today=TODAY)
    assert result.status == "error"
    assert result.error.code == "out_of_forecast_range"


def test_weather_rejects_past_and_inverted_ranges():
    past = get_weather_forecast_impl("Rome", dt.date(2026, 1, 1), today=TODAY)
    inverted = get_weather_forecast_impl(
        "Rome", dt.date(2026, 10, 30), dt.date(2026, 10, 28), today=TODAY
    )
    assert past.error.code == "date_in_past"
    assert inverted.error.code == "invalid_date_range"


@respx.mock
def test_weather_unknown_location():
    respx.get(GEOCODING_URL).mock(return_value=httpx.Response(200, json={}))
    assert get_weather_forecast_impl("Atlantis", today=TODAY).error.code == "location_not_found"


@respx.mock
def test_weather_upstream_down_is_retried_then_reported(monkeypatch):
    monkeypatch.setattr("tools.http.time.sleep", lambda _s: None)
    respx.get(GEOCODING_URL).mock(return_value=httpx.Response(503))
    result = get_weather_forecast_impl("Rome", today=TODAY)
    assert result.error.code == "upstream_unavailable"
    assert respx.calls.call_count == 3  # 1 try + 2 retries


# --------------------------------------------------------------------------- currency


@respx.mock
def test_currency_conversion():
    respx.get(f"{FRANKFURTER_URL}/latest").mock(
        return_value=httpx.Response(200, json=rates("USD", "JPY", 150.5))
    )
    result = convert_currency_impl(250, "USD", "JPY")
    assert result.status == "ok"
    assert result.converted_amount == pytest.approx(37625.0)
    assert result.rate_date == dt.date(2026, 10, 23)


@respx.mock
def test_currency_unsupported_names_only_the_missing_code():
    respx.get(f"{FRANKFURTER_URL}/latest").mock(return_value=httpx.Response(404))
    respx.get(f"{FRANKFURTER_URL}/currencies").mock(
        return_value=httpx.Response(200, json={"USD": "United States Dollar", "EUR": "Euro"})
    )
    result = convert_currency_impl(100, "USD", "ARS")
    assert result.status == "error"
    assert result.error.code == "unsupported_currency"
    assert result.error.message.startswith("ARS is not covered")
    assert "USD is not" not in result.error.message


def test_currency_same_code_needs_no_api_call():
    result = convert_currency_impl(10, "EUR", "EUR")
    assert result.rate == 1.0 and result.converted_amount == 10


def test_currency_input_validation():
    assert CurrencyConversionInput(amount=1, from_currency=" usd", to_currency="eur").from_currency == "USD"
    with pytest.raises(ValueError):
        CurrencyConversionInput(amount=1, from_currency="dollars", to_currency="EUR")
    with pytest.raises(ValueError):
        CurrencyConversionInput(amount=-5, from_currency="USD", to_currency="EUR")


# --------------------------------------------------------------------------- LangChain wrappers


@respx.mock
def test_tool_returns_json_content_and_structured_artifact():
    respx.get(f"{FRANKFURTER_URL}/latest").mock(
        return_value=httpx.Response(200, json=rates("GBP", "EUR", 1.2))
    )
    message = convert_currency.invoke(
        {
            "type": "tool_call",
            "id": "call-1",
            "name": "convert_currency",
            "args": {"amount": 80, "from_currency": "GBP", "to_currency": "EUR"},
        }
    )
    assert json.loads(message.content)["converted_amount"] == 96.0  # what the LLM reads
    assert message.artifact["status"] == "ok"  # what code reads


def test_tool_schema_exposed_to_the_llm():
    schema = get_weather_forecast.tool_call_schema.model_json_schema()
    assert {"city", "start_date", "end_date"} <= set(schema["properties"])
    assert schema["required"] == ["city"]
