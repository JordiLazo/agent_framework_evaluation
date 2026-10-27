# Step 4: Tracing experiments

## What the assessment asks

> Run at least 10 queries through the system. Ensure these queries appear as traces in Phoenix.
> Export the spans from Phoenix.

## Summary

- **22 queries in 13 conversations** (sessions) went through the real API with Claude Haiku 5.5:
  single questions, multi-turn follow-ups, multi-tool requests, tool errors, an out-of-scope
  request and scripted frustrated users.
- **All 22 appear in Phoenix as traces** in project `travel-agent`: 22 traces with 340 spans
  (22 AGENT, 42 LLM, 22 TOOL, 254 CHAIN). Multi-turn conversations are grouped in Phoenix's
  **Sessions** view.
- **The spans were exported** to `data/exports/spans_travel-agent_<timestamp>.jsonl` and `.csv`,
  either with a script (Phoenix Python client) or with the PX CLI.
- **Cost of the whole run:** 93,010 input + 10,091 output tokens ≈ **$0.014**.

---

## Changes made

All paths are in `se-interview/`.

| File | Change |
|---|---|
| `api.py` | `/chat` accepts an optional **`session_id`** (multi-turn memory) and **`metadata`** (attached to every span), and returns `session_id` and `trace_id`. `tool_calls` lists only the current turn's calls. |
| `agent.py` | `build_agent(..., checkpointer=...)`: the API passes LangGraph's `MemorySaver`, so each session keeps its messages (`thread_id = session_id`). |
| `observability.py` | New `turn_span()`: one root **`chat` AGENT span per user turn**, with `input.value` = user message, `output.value` = final answer, status OK/ERROR. It propagates `session.id` and `metadata` to every child span (`using_attributes`). |
| `evals/scenarios.py` | **New.** 13 scenarios / 22 turns, each turn with a reference frustration label (used in Step 5). |
| `evals/run_queries.py` | **New.** Sends every scenario through the API (one session per scenario, 4 in parallel), prints the answers and tools, and saves `data/runs/run_<run_id>.jsonl`. |
| `evals/export_spans.py` | **New.** Downloads the project's spans with the Phoenix client and writes JSONL + CSV. `--run-id` exports a single run. |
| `evals/phoenix_data.py` | **New.** Phoenix client helpers and span-to-table transformations, shared with Step 5. |
| `pyproject.toml` / `poetry.lock` | New `evals` dependency group: `arize-phoenix-client`, `arize-phoenix-evals`, `pandas`. Nothing existing changed version. |
| `.gitignore` | Ignores `data/` (generated runs, exports and eval results). |
| `tests/` | +8 tests: sessions, per-turn tool calls, root span and session propagation, run filtering. 30 tests total. |

### Why a root `chat` span?

Without it, each trace's top span is LangGraph's internal `LangGraph` chain, whose input/output
is the serialized graph state. The `chat` span gives every trace a clean, readable unit: user
message in, final answer out, plus session id and metadata. That makes the traces easy to read
in the UI, and Step 5 evaluates and builds its dataset on exactly these spans.

```
chat                         AGENT  input = "Ugh, seriously? ...", output = final answer
│                                   session.id = unsupported_currency-<run_id>
│                                   metadata = {run_id, scenario, turn_index, expected_user_frustration}
└─ LangGraph                 CHAIN
   ├─ llm_call               CHAIN
   │  └─ ChatAnthropic       LLM    claude-haiku-5-5, messages, 3 tool schemas, tool calls, tokens
   ├─ tool_node              CHAIN
   │  └─ duckduckgo_search   TOOL   arguments + result
   └─ llm_call               CHAIN
      └─ ChatAnthropic       LLM    final answer
```

---

## The queries

| # | Session (scenario) | Turns | What it exercises |
|---|---|---|---|
| 1 | `weather_weekend` | 1 | Weather with a relative date ("this weekend") |
| 2 | `currency_simple` | 1 | Currency conversion |
| 3 | `attractions_porto` | 1 | Web search |
| 4 | `flights_then_weather` | 2 | Search, then a follow-up needing another tool and memory ("that day") |
| 5 | `tokyo_multi_tool` | 1 | Two tools in one request (weather + currency) |
| 6 | `hotels_barcelona` | 1 | Web search |
| 7 | `frustrated_units` | 2 | User re-asserts "Fahrenheit" with annoyance |
| 8 | `frustrated_far_future` | 2 | Date beyond the forecast horizon, then an annoyed user |
| 9 | `frustrated_cheap_hotel` | 3 | Escalating frustration ("second time I'm asking", "forget it") |
| 10 | `unsupported_currency` | 2 | ARS not covered by the ECB → tool error → impatient user |
| 11 | `paris_then_thanks` | 2 | Satisfied follow-up |
| 12 | `off_topic_then_kyoto` | 2 | Out-of-scope request, calm topic switch |
| 13 | `currency_refinement` | 2 | Neutral refinement ("and 120 pounds?") |
| | **Total** | **22** | 5 turns are scripted as frustrated, 17 as not frustrated |

---

## How to run it

Phoenix (`:6006`) and the API (`:8000`) must be running with `PHOENIX_TRACING_ENABLED=true`
(see `step3.md`). Run everything from `se-interview/`.

### 1. Send the queries

```bash
poetry run python -m evals.run_queries
```

Real output (shortened):

```
run_id=20261026-202215-bac6: 13 sessions, 22 turns -> http://localhost:8000

[weather_weekend #0] ok | tools: get_weather_forecast[ok]
   user : What's the weather going to be like in Lisbon this weekend?
   agent: '**Lisbon this weekend looks dry and warm.** Expect little to no rain on both days. ...'
[tokyo_multi_tool #0] ok | tools: get_weather_forecast[ok], convert_currency[ok]
   user : I'm flying to Tokyo next week with a budget of 1500 EUR. What's the weather going to be like and how
   agent: 'Assuming "next week" means **2–8 November**, Tokyo will be cool ... Your €1,500 is about **¥264,225'
[frustrated_cheap_hotel #1] ok | tools: duckduckgo_search[success]
   user : No, I said CHEAP. Under 100 pounds a night. This is the second time I'm asking.
   agent: "You're right, and I'm sorry I missed that. My searches still haven't turned up specific London hotels ..."
[unsupported_currency #0] ok | tools: convert_currency[error]
   user : How much is 100 US dollars in Argentine pesos?
   agent: "I couldn't get a conversion. The ECB reference-rate tool I use doesn't cover ..."
...
22 turns, 0 failed. Results: data/runs/run_20261026-202215-bac6.jsonl
Phoenix: filter traces with  metadata['run_id'] == '20261026-202215-bac6'
```

Options: `--only weather_weekend currency_simple` runs a subset, and `--base-url` targets another
host.

### 2. See the traces in Phoenix

Open http://localhost:6006 → project **travel-agent**.

- **Traces tab:** 22 `chat` traces. Click one to see the tree, prompts, tool arguments and
  results, tokens and latency.
- **Sessions tab:** 13 sessions. Multi-turn conversations appear as a chat history.
- **Filter box** (these expressions were checked against the server):

  | Filter | Result |
  |---|---|
  | `metadata['run_id'] == '20261026-202215-bac6' and span_kind == 'AGENT'` | the 22 turns of this run |
  | `metadata['scenario'] == 'frustrated_cheap_hotel'` | one conversation |
  | `span_kind == 'TOOL'` | every tool call |
  | `span_kind == 'LLM'` | every Claude call |

From the terminal with the PX CLI:

```bash
px span list --endpoint http://localhost:6006 --project travel-agent --span-kind LLM -n 3
```

```
┌────────┬───────────────┬──────┬──────────┬──────────────────┬──────────────────────────────────┬─────────────────────────┐
│ status │ name          │ kind │ duration │ span_id          │ trace_id                         │ time                    │
├────────┼───────────────┼──────┼──────────┼──────────────────┼──────────────────────────────────┼─────────────────────────┤
│ ✓ OK   │ ChatAnthropic │ LLM  │ 2783ms   │ 1b542b1528ac79a3 │ ab1c8ff1c239e8c4575a5de5be3b2b01 │ 2026-10-26 19:22:47 UTC │
│ ✓ OK   │ ChatAnthropic │ LLM  │ 2940ms   │ 522a16e5b57cd0bd │ eeefdba5b4b3139791e3e7d12eb980e8 │ 2026-10-26 19:22:44 UTC │
│ ✓ OK   │ ChatAnthropic │ LLM  │ 2647ms   │ 9d206eff8b38467c │ eeefdba5b4b3139791e3e7d12eb980e8 │ 2026-10-26 19:22:40 UTC │
└────────┴───────────────┴──────┴──────────┴──────────────────┴──────────────────────────────────┴─────────────────────────┘
```

### 3. Export the spans

**Option A: Python script** (Phoenix client → JSONL + CSV)

```bash
poetry run python -m evals.export_spans --run-id 20261026-202215-bac6
```

```
Project 'travel-agent': exported 340 spans from 22 traces
spans per kind
CHAIN    254
LLM       42
AGENT     22
TOOL      22

-> data/exports/spans_travel-agent_20261026-202310.jsonl
-> data/exports/spans_travel-agent_20261026-202310.csv
```

Without `--run-id`, it exports every span in the project.

**Option B: PX CLI** (JSON)

```bash
mkdir -p data/exports
px span list data/exports/spans_px.json --endpoint http://localhost:6006 \
  --project travel-agent --format json -n 5000
```

Each exported row is one span, with columns such as `name`, `span_kind`, `parent_id`,
`start_time`, `end_time`, `status_code`, `context.trace_id`, `context.span_id`,
`attributes.input.value`, `attributes.output.value`, `attributes.session.id`,
`attributes.metadata`, `attributes.llm.model_name`, `attributes.llm.token_count.prompt` /
`.completion`, `attributes.llm.input_messages`, `attributes.llm.output_messages`,
`attributes.tool.name`.

---

## What the traces showed (from the exported spans)

| Metric | Value |
|---|---|
| Turns / sessions / traces | 22 / 13 / 22 (0 failed) |
| Spans | 340 (22 AGENT, 42 LLM, 22 TOOL, 254 CHAIN) |
| Model | `claude-haiku-5-5` on all 42 LLM spans |
| Tokens / cost | 93,010 input + 10,091 output ≈ **$0.014** |
| Turn latency | mean 5.0 s, median 4.0 s, max 11.8 s |
| LLM call latency | mean 2.0 s |
| Tool latency | `convert_currency` 0.11 s, `get_weather_forecast` 0.46 s, `duckduckgo_search` 1.96 s |
| Tool calls | 11 web search, 6 weather, 5 currency (4 ok, 1 `unsupported_currency`) |

Observations:

- **Tool routing is right.** Weather questions → `get_weather_forecast`, money →
  `convert_currency`, hotels/flights/attractions → `duckduckgo_search`. Tokyo used both new
  tools in **parallel**. "This weekend" and "next Friday" became concrete dates.
- **Memory works.** "And what will the weather be like in Rome that day?" reused the date from
  the previous turn. "And what about 120 pounds?" reused GBP→EUR.
- **Web search is the weak spot.** Its results for hotels and flights were mostly booking ads,
  and Claude said so instead of inventing prices. It's honest, but it is exactly what led to
  the frustrated hotel conversation (see Step 5).
- **Debugging insight: an ambiguous tool error.** The TOOL span for ARS showed
  `'USD' or 'ARS' is not covered`, and Claude repeated it as "doesn't cover US dollars". That's
  wrong, because USD is covered. Fixed in `tools/currency.py`: the error now names only the
  missing code (`ARS is not covered ... The other currency is supported.`). After the fix,
  rerunning the scenario gave a correct explanation, and the follow-up got a rough rate from
  web search (~1,500 ARS per USD).
- **Latency comes mostly from LLM calls** (about 2 s each, two or three per turn), not from the
  tools.
