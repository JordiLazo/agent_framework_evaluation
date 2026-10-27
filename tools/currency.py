"""Currency conversion tool backed by Frankfurter (ECB reference rates, free, no API key)."""

from __future__ import annotations

import datetime as dt

import httpx
from langchain_core.tools import tool

from tools.http import UpstreamError, get_json
from tools.schemas import CurrencyConversionInput, CurrencyConversionResult, ToolError

FRANKFURTER_URL = "https://api.frankfurter.dev/v1"


def _error(code: str, message: str) -> CurrencyConversionResult:
    return CurrencyConversionResult(status="error", error=ToolError(code=code, message=message))


def _unsupported_currency_error(from_currency: str, to_currency: str) -> CurrencyConversionResult:
    """Name exactly which code is unsupported.

    Found while debugging with Phoenix traces: the old message said "'USD' or 'ARS' is not
    covered", and the LLM repeated it to the user as "US dollars aren't supported", which is
    wrong. We now look up the supported list and report only the codes that are missing.
    """
    try:
        supported = set(get_json(f"{FRANKFURTER_URL}/currencies"))
    except (UpstreamError, httpx.HTTPError):
        supported = set()
    missing = [c for c in (from_currency, to_currency) if supported and c not in supported]
    which = " and ".join(missing) if missing else f"{from_currency} or {to_currency}"
    return _error(
        "unsupported_currency",
        f"{which} is not covered by ECB reference rates (about 30 major currencies are). "
        f"{'The other currency is supported. ' if len(missing) == 1 else ''}"
        "Tell the user, and suggest a bank or card provider for the exact rate.",
    )


def convert_currency_impl(
    amount: float, from_currency: str, to_currency: str, date: dt.date | None = None
) -> CurrencyConversionResult:
    if from_currency == to_currency:
        return CurrencyConversionResult(
            status="ok",
            amount=amount,
            from_currency=from_currency,
            to_currency=to_currency,
            rate=1.0,
            converted_amount=round(amount, 2),
            rate_date=date or dt.date.today(),
        )

    path = date.isoformat() if date else "latest"
    try:
        payload = get_json(
            f"{FRANKFURTER_URL}/{path}", {"base": from_currency, "symbols": to_currency}
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 422):
            return _unsupported_currency_error(from_currency, to_currency)
        return _error("upstream_error", f"Rates service returned HTTP {exc.response.status_code}")
    except (UpstreamError, httpx.HTTPError) as exc:
        return _error("upstream_unavailable", f"Rates service unavailable: {exc}")

    rate = (payload.get("rates") or {}).get(to_currency)
    if rate is None:
        return _error("unsupported_currency", f"No reference rate for {from_currency}->{to_currency}.")
    return CurrencyConversionResult(
        status="ok",
        amount=amount,
        from_currency=from_currency,
        to_currency=to_currency,
        rate=rate,
        converted_amount=round(amount * rate, 2),
        rate_date=dt.date.fromisoformat(payload["date"]),
    )


@tool(
    "convert_currency",
    args_schema=CurrencyConversionInput,
    response_format="content_and_artifact",
)
def convert_currency(
    amount: float, from_currency: str, to_currency: str, date: dt.date | None = None
) -> tuple[str, dict]:
    """Convert an amount of money between two currencies using official European Central Bank
    reference rates. Use it for travel budgeting questions such as 'how much is 200 EUR in
    JPY?' or to express hotel/flight prices in the user's home currency. Do NOT guess exchange
    rates from memory - always call this tool."""
    result = convert_currency_impl(amount, from_currency, to_currency, date)
    return result.model_dump_json(exclude_none=True), result.model_dump(mode="json")
