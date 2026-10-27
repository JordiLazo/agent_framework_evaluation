# Step 2: LangGraph agent extension

> **Update:** the agent now runs on **Claude (`claude-haiku-5-5`)** instead of GPT-4o. See
> `step1.md` for the switch. The tools below are unchanged and model-agnostic.

## What the assessment asks

> Extend the LangGraph agent with at least one additional tool. Your extension should:
> - integrate into the agent workflow
> - be invoked by the agent when relevant
> - return structured output
>
> Document your design decisions.

## Summary

I added **two** tools to the starter agent in `se-interview/` and made the agent behave as a
travel assistant:

| Tool | What it does | Backend (free, no API key) |
|---|---|---|
| `get_weather_forecast` | Daily forecast for a city and date range: min/max °C, rain probability and amount, wind, condition | [Open-Meteo](https://open-meteo.com) geocoding + forecast API |
| `convert_currency` | Converts an amount between currencies using official ECB reference rates (latest or historical) | [Frankfurter](https://frankfurter.dev) |

How each requirement is met:

| Requirement | How it is met |
|---|---|
| Integrate into the agent workflow | Both tools are registered in the same `tools` list as the starter's DuckDuckGo search. They are bound to the LLM (now Claude, see `step1.md`) with `bind_tools` and executed by the existing `tool_node` in the `llm_call ⇄ tool_node` loop. The graph topology is unchanged. |
| Invoked by the agent when relevant | The LLM decides when to call them, based on each tool's name, docstring (with example questions) and typed argument schema. A new system prompt adds routing rules (which tool for what) and today's date, so "this weekend" can be turned into concrete dates. |
| Return structured output | Each tool returns a Pydantic-validated JSON document with a fixed envelope: `{"status": "ok"\|"error", "error": {code, message}, "source", ...data}`. The LLM reads it as JSON text, and code reads the same data as a dict (`ToolMessage.artifact`). The API also exposes which tools were called, with their status. |

Verification:
- 17 offline unit tests pass (`poetry run pytest`).
- I ran both tools against the live public APIs through the real graph.
- The API boots and `/health` responds.

---

## Files changed

All paths are relative to `se-interview/`.

| File | Change | Lines |
|---|---|---|
| `tools/__init__.py` | **new**: exports the two tools | 6 |
| `tools/schemas.py` | **new**: Pydantic input/output models (`WeatherForecastInput/Result`, `CurrencyConversionInput/Result`, `ToolError`) | 114 |
| `tools/http.py` | **new**: shared `get_json()` with timeout, retries with exponential backoff, and error classification | 59 |
| `tools/weather.py` | **new**: geocoding, date validation, forecast call, WMO code → text, the `@tool` wrapper | 181 |
| `tools/currency.py` | **new**: rate lookup, error mapping, the `@tool` wrapper | 77 |
| `agent.py` | **modified**: registers the tools, adds the travel system prompt with today's date, makes tool execution safer, lets tests inject the model | +79 / −30 |
| `api.py` | **modified**: `ChatResponse.tool_calls` (additive) and a recursion limit | +44 / −6 |
| `pyproject.toml` | **modified**: explicit `httpx` and `pydantic`; dev group with `pytest` and `respx`; pytest config; version 0.2.0 | +13 / −2 |
| `poetry.lock` | **regenerated**: only the 5 new dev packages were added (pytest, respx, pluggy, iniconfig, pygments). **No existing dependency changed version.** | — |
| `README.md` | **modified**: documents the tools, the new response field, tests, layout and setup | — |
| `.gitignore` | **modified**: adds `.pytest_cache/` | +1 |
| `tests/conftest.py` | **new**: import path and a dummy key for tests | 9 |
| `tests/test_tools.py` | **new**: 11 tests for the tools (HTTP mocked with `respx`) | 153 |
| `tests/test_agent.py` | **new**: 6 tests for the graph wiring and the API (scripted fake LLM) | 83 |

> `.env.example` shows as deleted in `git status` because it was renamed to `.env` on this
> machine. I didn't put it back. The README setup now creates `.env` directly with `echo`.

---

## Detailed modifications

### 1. New tool: `get_weather_forecast` (`tools/weather.py`)

**Input** (`WeatherForecastInput`, which is the JSON schema the LLM sees):

| Field | Type | Notes |
|---|---|---|
| `city` | `str` (required) | `"City"` or `"City, Country"`. The country part narrows the search, e.g. `"Paris, France"` rather than Paris, Texas. |
| `start_date` | `date` (optional) | Defaults to today |
| `end_date` | `date` (optional) | Defaults to start + 6 days; capped at the 16-day forecast horizon |

**Flow:**
1. Validate the dates locally. This rejects past dates, inverted ranges and anything beyond the
   horizon without spending an HTTP call.
2. Geocode the city with the Open-Meteo geocoding API. If a country is given, prefer the result
   in that country (matching the name or ISO code).
3. Fetch the daily forecast for those coordinates in the destination's local time zone.
4. Turn WMO weather codes into readable summaries ("Slight rain", "Overcast", ...).

**Output** (`WeatherForecastResult`), as returned in a real run:

```json
{"status":"ok",
 "location":{"name":"Lisbon","country":"Portugal","country_code":"PT","latitude":38.72509,"longitude":-9.1498,"timezone":"Europe/Lisbon"},
 "days":[{"date":"2026-10-31","summary":"Overcast","weather_code":3,"temperature_max_c":26.4,"temperature_min_c":16.2,
          "precipitation_probability_max_pct":3.0,"precipitation_sum_mm":0.0,"wind_speed_max_kmh":7.5}, ...],
 "units":{"temperature":"celsius","precipitation":"mm","wind":"km/h"},
 "source":"open-meteo.com"}
```

**Error codes:** `invalid_date_range`, `date_in_past`, `out_of_forecast_range`,
`location_not_found`, `upstream_unavailable`.

### 2. New tool: `convert_currency` (`tools/currency.py`)

**Input** (`CurrencyConversionInput`): `amount` (> 0), `from_currency`, `to_currency` (ISO 4217
codes, upper-cased and checked: `" usd"` becomes `"USD"`, while `"dollars"` is rejected), and an
optional historical `date`.

**Flow:** if both currencies are the same, return immediately. Otherwise call
`GET /v1/{latest|YYYY-MM-DD}?base=FROM&symbols=TO`, then compute and round the converted
amount.

**Output** (`CurrencyConversionResult`), as returned in a real run:

```json
{"status":"ok","amount":300.0,"from_currency":"USD","to_currency":"EUR","rate":0.89381,
 "converted_amount":268.14,"rate_date":"2026-10-26",
 "source":"frankfurter (European Central Bank reference rates)"}
```

**Error codes:** `unsupported_currency` (HTTP 404/422, e.g. ARS, which the ECB doesn't
publish; confirmed against the live API), `upstream_error` and `upstream_unavailable`.

### 3. Shared HTTP helper (`tools/http.py`)

`get_json(url, params)` adds:
- a 10 s timeout, configurable with `HTTP_TIMEOUT_SECONDS`;
- up to 2 retries with exponential backoff (0.5 s, 1 s) on network errors and on HTTP 429 /
  5xx;
- no retry on other 4xx responses, which are raised as `httpx.HTTPStatusError` for the tool to
  map to a meaningful code;
- a descriptive `User-Agent`.

### 4. Agent changes (`agent.py`)

| Before (starter) | After |
|---|---|
| `tools = [search_tool]` | `tools = [search_tool, get_weather_forecast, convert_currency]` |
| Generic prompt: "helpful assistant that can search the web" | Travel-assistant prompt with **today's date and weekday**, a guide to which tool to use, and grounding rules ("never quote exchange rates from memory", "if a tool returns status error, explain and offer an alternative") |
| `tool.invoke(tool_call["args"])`, wrapped by hand in a `ToolMessage` | `tool.invoke(tool_call)`, where LangChain builds the `ToolMessage` and **keeps the structured `artifact`** |
| A tool exception or unknown tool name crashed the request (HTTP 500) | Becomes an error `ToolMessage` (`status="error"`) that the LLM can recover from |
| Model created at import; `build_agent()` took no arguments | `build_agent(model=None, agent_tools=None)`: a default model (originally GPT-4o; now `claude-haiku-5-5`), but a fake model can be injected in tests |

The graph is unchanged: `START → llm_call ⇄ tool_node → END`, with the same node names and
routing function (`should_continue`).

### 5. API changes (`api.py`)

- `ChatResponse` gains `tool_calls: [{name, args, status}]`. The field is additive, so existing
  clients that read only `response` keep working. It shows which tools the agent chose and
  whether each succeeded.
- `agent.invoke(..., {"recursion_limit": 12})` caps the tool loop at about 5 rounds of tool
  calls.

### 6. Dependencies and tests

- `httpx` and `pydantic` are now explicit dependencies. They were already installed
  transitively, but the new code imports them directly.
- A dev group adds `pytest` and `respx`. `poetry lock` kept every existing pin.
- There are 17 tests in total, all offline:
  - **Tools (11):** the weather happy path with a country hint, out-of-range / past / inverted
    dates, an unknown city, retries followed by a reported upstream failure, the conversion
    maths, unsupported currency, same-currency short-circuit, input validation, JSON content
    plus structured artifact, and the schema exposed to the LLM.
  - **Agent / API (6):** tools are registered, the prompt includes the date, a tool call is
    executed and fed back, a tool exception is handled, an unknown tool is reported, and
    `/chat` returns `tool_calls`.

---

## Design decisions

1. **Weather and currency, because they fill the starter's real gaps.** Web search returns
   unstructured snippets and makes the model do arithmetic and date reasoning in its head.
   Forecasts and exchange rates are exactly the travel questions where a model invents numbers
   unless it is grounded in data. Both tools also return naturally structured data.
2. **Free, keyless, reliable APIs.** Open-Meteo and Frankfurter (ECB) need no sign-up, so
   reviewers can run the project with only the LLM key the app already requires. I
   didn't add flight or hotel tools: there's no free, keyless API for them, and fake data would
   be misleading. The existing web search covers those.
3. **Pydantic schemas on both sides.**
   - **Inputs:** `args_schema` gives the LLM a precise JSON schema (types, required fields,
     descriptions with examples), and invalid arguments are rejected before any HTTP call.
   - **Outputs:** a typed result model makes the structure explicit, documented and tested.
4. **`response_format="content_and_artifact"`.** The tool returns the JSON string for the LLM
   and the same data as a dict for code (`ToolMessage.artifact`). The API reads the artifact to
   report each tool's status without parsing text, and later evaluation steps can do the same.
5. **Errors as data, with stable codes.** A failure is a valid result
   (`status: "error"` + `code` + `message` with a recovery hint) rather than an exception. The
   LLM can then explain the problem ("forecasts only go 16 days ahead; here is typical March
   weather instead") instead of failing the request. The codes are stable, so failures can be
   counted by type.
6. **Validate locally before calling out.** Date-range checks and currency-code normalisation
   happen in Python. That's cheaper, faster and gives clearer messages than an upstream 400.
7. **Resilience in one place.** Every outbound call goes through `get_json()`, which has a
   timeout, retries only on retryable failures, and backs off. A slow or flaky API can't hang
   the agent.
8. **Tool descriptions drive routing.** Docstrings say when to use the tool, with example
   questions. The system prompt adds a short routing guide and today's date. That is what makes
   the model call the tools "when relevant" and resolve relative dates correctly.
9. **Make the existing loop safe instead of replacing it.** I kept the starter's hand-written
   `tool_node` and graph so the change is easy to review. I changed only what the new tools
   need: preserving the artifact, error handling and unknown-tool handling.
10. **Backwards-compatible API.** `response` is unchanged, and `tool_calls` is purely additive.
11. **No dependency drift.** I didn't upgrade LangGraph or LangChain. The lock file
    only gained test tooling, so Step 1 behaviour is unchanged.
12. **Deterministic tests without network or keys.** `respx` mocks HTTP, and a scripted
    `GenericFakeChatModel` stands in for the LLM, so the graph wiring is tested reliably and for
    free.

---

## How to verify

Run from `se-interview/`. Setup is in `execution_steps.md`.

```bash
poetry install                      # adds pytest/respx (dev group)
poetry run pytest                   # 17 passed, offline
poetry run uvicorn api:app --reload # needs ANTHROPIC_API_KEY in .env
```

Then, in a second terminal, ask questions that should trigger each tool:

```bash
# weather + currency in one request (expect 2 tool calls, possibly in parallel)
curl -s -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"What is the weather in Lisbon this weekend, and how much is 300 USD in EUR?"}'

# tool error handled gracefully (beyond the 16-day horizon -> out_of_forecast_range)
curl -s -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"What will the weather be in Paris on 15 March 2027?"}'

# currency not covered by ECB (-> unsupported_currency)
curl -s -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"How much is 100 US dollars in Argentine pesos?"}'

# should NOT call the new tools (web search or no tool)
curl -s -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"What are the top attractions in Porto?"}'
```

Check the `tool_calls` field of each response to see which tools the agent chose.

## Verification status

| Check | Result |
|---|---|
| Unit tests (`poetry run pytest`) | ✅ 17 passed |
| Tools against the live Open-Meteo / Frankfurter APIs, run through the real graph | ✅ Lisbon forecast and USD→EUR conversion returned `ok`; ARS → `unsupported_currency`; Paris in 2027 → `out_of_forecast_range` |
| API boots, `/health`, new `ChatResponse` schema | ✅ |
| The LLM (Claude) actually choosing the tools for real questions | ⏳ **Not run yet**: needs a valid `ANTHROPIC_API_KEY` in `se-interview/.env` (it currently holds the placeholder). Use the `curl` commands above to verify. |
