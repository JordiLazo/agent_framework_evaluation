# Final guide: run and test the whole app

This guide runs the complete solution end to end: the Claude travel agent, Phoenix tracing,
the test traffic, the span export and the user-frustration evaluation. Every command comes with
its expected output; the outputs shown are from a real run on 2026-10-26.

**Assumption:** all dependencies are already installed (see `step1.md`), and you are on macOS
with Terminal.

---

## 0. Overview

You will use **3 Terminal tabs** (`⌘ + T` opens a new one):

| Tab | Runs | Address |
|---|---|---|
| 1 | Phoenix (traces UI + collector) | http://localhost:6006 |
| 2 | Travel agent API (FastAPI + LangGraph + Claude) | http://localhost:8000 |
| 3 | Your commands: requests, tests, traffic, export, evaluation | — |

```
 you / scripts ──HTTP──► API :8000 ──► LangGraph agent ──► Claude Haiku 5.5 (Anthropic API)
                                         │                 tools: web search · weather · currency
                                         └── spans (OTLP) ──► Phoenix :6006 ◄── evals (annotations, dataset)
```

Project folder for every command in tabs 2 and 3:

```bash
cd ~/git/agent_framework_evaluation/se-interview
```

---

## 1. Check the configuration

```bash
grep -v '^#' .env | grep . | sed -E 's/(KEY=.{10}).*/\1…/'
```

Expected output:

```
ANTHROPIC_API_KEY=sk-ant-api…
PHOENIX_TRACING_ENABLED=true
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006
PHOENIX_PROJECT_NAME=travel-agent
```

`PHOENIX_TRACING_ENABLED` must be `true` for Steps 3–5.

---

## 2. Tab 1: start Phoenix

```bash
~/.phoenix-venv/bin/phoenix serve
```

Expected output (end of the startup banner):

```
  Web UI              http://localhost:6006
  REST API            http://localhost:6006/v1
  ▶ OTLP over gRPC    http://localhost:4317
  ▶ OTLP over HTTP    http://localhost:6006/v1/traces
🚀 Phoenix is up and running — open http://localhost:6006 to get started.
```

Open the UI in your browser:

```bash
open http://localhost:6006
```

---

## 3. Tab 2: start the API

```bash
cd ~/git/agent_framework_evaluation/se-interview
poetry run uvicorn api:app --port 8000
```

Expected output:

```
INFO:     Started server process [73133]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Leave tabs 1 and 2 running. Everything below happens in **tab 3**.

---

## 4. Tab 3: run the unit tests (offline)

```bash
cd ~/git/agent_framework_evaluation/se-interview
poetry run pytest
```

Expected output:

```
..............................                                           [100%]
30 passed in 0.96s
```

These tests cover the tools (mocked HTTP), graph wiring, sessions, the API, tracing (in-memory
exporter) and the evaluation helpers. They use no API key and don't touch Phoenix.

---

## 5. Try the agent by hand

### 5.1 Health check

```bash
curl http://localhost:8000/health
```

```json
{"status":"ok"}
```

### 5.2 A question that needs two tools (weather + currency)

```bash
curl -s -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"What is the weather in Lisbon this weekend, and how much is 300 USD in EUR?"}' \
  | python3 -m json.tool
```

```json
{
    "response": "**Lisbon this weekend (Sat 31 Oct – Sun 1 Nov):**\n- **Saturday:** Overcast, 16–26 °C, about 3% chance of rain, light wind.\n- **Sunday:** Partly cloudy, 15–26 °C, about 13% chance of rain, light wind.\n\nDry and warm both days ...\n\n**Currency:** 300 USD ≈ **268.14 EUR** (ECB reference rate, 26 Oct 2026).",
    "session_id": "582b3068-d82c-4c83-ae93-b9e55fe2c8b6",
    "trace_id": "3b1d83452b54eaf9c2c8ad6ece56df4f",
    "tool_calls": [
        {"name": "get_weather_forecast",
         "args": {"city": "Lisbon, Portugal", "start_date": "2026-10-31", "end_date": "2026-11-01"},
         "status": "ok"},
        {"name": "convert_currency",
         "args": {"amount": 300, "from_currency": "USD", "to_currency": "EUR"},
         "status": "ok"}
    ]
}
```

What to notice:

- "this weekend" was turned into real dates;
- both tools were called in one step;
- `tool_calls` shows the structured arguments and each tool's `status`;
- `trace_id` identifies this request in Phoenix.

### 5.3 Continue the same conversation (multi-turn memory)

Reuse the `session_id` from the previous response:

```bash
curl -s -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"And what about Porto on the same days?","session_id":"582b3068-d82c-4c83-ae93-b9e55fe2c8b6"}' \
  | python3 -m json.tool
```

```json
{
    "response": "**Porto this weekend (Sat 31 Oct – Sun 1 Nov):**\n- **Saturday:** Overcast, 13–24 °C, no rain expected ...\n\nBoth days are dry, but Porto is a few degrees cooler than Lisbon ...",
    "session_id": "582b3068-d82c-4c83-ae93-b9e55fe2c8b6",
    "tool_calls": [
        {"name": "get_weather_forecast",
         "args": {"city": "Porto, Portugal", "start_date": "2026-10-31", "end_date": "2026-11-01"},
         "status": "ok"}
    ]
}
```

The agent remembered "the same days" and compared Porto with Lisbon.

### 5.4 A tool error handled gracefully

```bash
curl -s -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"How much is 100 US dollars in Argentine pesos?"}' | python3 -m json.tool
```

```json
{
    "response": "I couldn't get a rate for US dollars to Argentine pesos. My currency tool uses European Central Bank reference rates, and the ECB doesn't publish ARS ...",
    "tool_calls": [
        {"name": "convert_currency",
         "args": {"amount": 100, "from_currency": "USD", "to_currency": "ARS"},
         "status": "error"}
    ]
}
```

The tool returned a structured `unsupported_currency` error, and the agent explained it instead
of inventing a rate.

### 5.5 More things to try

```bash
# forecast beyond the 16-day horizon -> out_of_forecast_range
curl -s -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"What will the weather be in Paris on 15 March 2027?"}' | python3 -m json.tool

# web search only (no weather/currency tool expected)
curl -s -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"What are the top attractions in Porto?"}' | python3 -m json.tool
```

Or use the browser UI: `open http://localhost:8000/docs` → **POST /chat** → **Try it out**.

---

## 6. See the traces in Phoenix (Step 3)

Open http://localhost:6006 → project **travel-agent** → click a `chat` trace:

```
chat                         AGENT  user message → final answer, session.id
└─ LangGraph                 CHAIN
   ├─ llm_call → ChatAnthropic          LLM   claude-haiku-5-5, prompt, 3 tool schemas, tool calls, tokens
   ├─ tool_node → get_weather_forecast  TOOL  arguments + JSON result
   │            → convert_currency      TOOL
   └─ llm_call → ChatAnthropic          LLM   final answer
```

From the terminal with the PX CLI:

```bash
px span list --endpoint http://localhost:6006 --project travel-agent --span-kind LLM TOOL -n 5
```

```
Showing 5 span(s)
┌────────┬───────────────────┬──────┬──────────┬──────────────────┬──────────────────────────────────┬─────────────────────────┐
│ status │ name              │ kind │ duration │ span_id          │ trace_id                         │ time                    │
├────────┼───────────────────┼──────┼──────────┼──────────────────┼──────────────────────────────────┼─────────────────────────┤
│ ✓ OK   │ ChatAnthropic     │ LLM  │ 1950ms   │ c73011109746a41a │ ba2c2c25131097a7966e6b1385d91c82 │ 2026-10-26 19:25:08 UTC │
│ ✓ OK   │ duckduckgo_search │ TOOL │ 641ms    │ 463d0326c835bce0 │ ba2c2c25131097a7966e6b1385d91c82 │ 2026-10-26 19:25:08 UTC │
│ ✓ OK   │ ChatAnthropic     │ LLM  │ 2703ms   │ 4bdc7ccb69397808 │ ba2c2c25131097a7966e6b1385d91c82 │ 2026-10-26 19:25:05 UTC │
│ ✓ OK   │ ChatAnthropic     │ LLM  │ 2254ms   │ ac67db4f68e60a91 │ 9592d9499c2c51568f6a233403c0e75d │ 2026-10-26 19:25:03 UTC │
│ ✓ OK   │ convert_currency  │ TOOL │ 232ms    │ 114b7899d016bba0 │ 9592d9499c2c51568f6a233403c0e75d │ 2026-10-26 19:25:02 UTC │
└────────┴───────────────────┴──────┴──────────┴──────────────────┴──────────────────────────────────┴─────────────────────────┘
```

---

## 7. Send the test traffic (Step 4)

```bash
poetry run python -m evals.run_queries
```

Expected output (shortened; takes about 30 seconds):

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
[currency_refinement #1] ok | tools: convert_currency[ok]
   user : And what about 120 pounds?
   agent: '120 GBP ≈ **143.16 EUR** ...'
...
22 turns, 0 failed. Results: data/runs/run_20261026-202215-bac6.jsonl
Phoenix: filter traces with  metadata['run_id'] == '20261026-202215-bac6'
```

**Copy your own `run_id`.** The next commands use it. Below it's written as `<RUN_ID>`.

In Phoenix you'll now see 22 new traces, and 13 conversations under the **Sessions** tab.

---

## 8. Export the spans (Step 4)

```bash
poetry run python -m evals.export_spans --run-id <RUN_ID>
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

Look at the first exported span:

```bash
head -c 400 data/exports/spans_travel-agent_*.jsonl; echo
```

```
{"name":"chat","span_kind":"AGENT","parent_id":null,"start_time":"2026-10-26T19:22:15.232Z", ...
 "attributes.output.value":"**Lisbon this weekend looks dry and warm.** ...
```

Same export with the PX CLI:

```bash
px span list data/exports/spans_px.json --endpoint http://localhost:6006 --project travel-agent --format json -n 5000
```

---

## 9. Run the user-frustration evaluation (Step 5)

```bash
poetry run python -m evals.evaluate --run-id <RUN_ID> --dataset-name frustrated-interactions
```

Expected output (takes about 20 seconds):

```
Evaluating 22 turns from 13 sessions (project=travel-agent, judge=claude-haiku-5-5) ...

=== Summary ===
{
  "turns": 22,
  "sessions": 13,
  "frustrated_turns": 5,
  "friction_turns": 5,
  "judge_errors": 0,
  "user_frustration_vs_reference": {
    "n": 22, "accuracy": 1.0, "precision": 1.0, "recall": 1.0, "f1": 1.0,
    "confusion": {"tp": 5, "fp": 0, "tn": 17, "fn": 0}
  },
  "tool_execution": {
    "convert_currency": {"success": 4, "tool_error": 1},
    "duckduckgo_search": {"success": 11, "tool_error": 0},
    "get_weather_forecast": {"success": 6, "tool_error": 0}
  },
  "dataset": {"created": true, "name": "frustrated-interactions", "examples": 5}
}

=== Turns judged frustrated ===
- [frustrated_units-... #1] I literally asked for Fahrenheit. Why do I keep getting Celsius?? ...
    judge: The user explicitly asked for Fahrenheit in the first message ... "I literally asked for Fahrenhe...
- [frustrated_far_future-... #1] That's useless. I don't care about your limitations, ...
- [frustrated_cheap_hotel-... #1] No, I said CHEAP. Under 100 pounds a night. This is the second time I'm asking.
- [frustrated_cheap_hotel-... #2] Forget it, you're not helping at all.
- [unsupported_currency-... #1] Ugh, seriously? I don't need an official rate, just give me a rough number like I asked.

Files: data/eval_results/20261026-202416/
```

If a dataset with that name already exists, use a new `--dataset-name`, or leave the option
out to get a timestamped name.

What the run did in Phoenix:

| Where | What |
|---|---|
| each `chat` span | annotations `user_frustration` (label, score, explanation) and `user_friction` |
| each TOOL span | annotation `tool_execution` (`success` / `tool_error` / `exception`) |
| each session | annotation `session_frustration` (e.g. "2 of 3 user turns judged frustrated") |
| Datasets tab | dataset `frustrated-interactions` with 5 examples linked to their spans |

---

## 10. Explore the evaluation results in Phoenix

Open http://localhost:6006 → **travel-agent**:

1. **Spans with annotations:** open a frustrated `chat` trace. The **Annotations** panel shows
   the judge's label and explanation.
2. **Filter the frustrated turns** by typing in the filter box:

   | Filter | Rows |
   |---|---|
   | `annotations['user_frustration'].label == 'frustrated'` | 5 |
   | `span_kind == 'TOOL' and annotations['tool_execution'].label == 'tool_error'` | 1 |
   | `metadata['scenario'] == 'frustrated_cheap_hotel'` | that conversation |

3. **Make a dataset from the UI** (optional): select the filtered spans → **Add to Dataset**.
4. **Datasets tab:** open `frustrated-interactions`. Each example has the input (conversation
   + user message), the output (the agent's answer) and metadata (session, scenario, judge
   explanation).
5. **Sessions tab:** see each conversation's `session_frustration`.

From the terminal:

```bash
px dataset list --endpoint http://localhost:6006
```

```
┌─────────────────────────┬──────────────┬──────────┬──────────────────────────────────────────────────────────────┐
│ name                    │ id           │ examples │ description                                                  │
├─────────────────────────┼──────────────┼──────────┼──────────────────────────────────────────────────────────────┤
│ frustrated-interactions │ RGF0YXNldDoy │ 5        │ User turns labelled 'frustrated' by the user_frustration ... │
└─────────────────────────┴──────────────┴──────────┴──────────────────────────────────────────────────────────────┘
```

Local result files:

```bash
ls data/eval_results/*/
python3 -m json.tool data/eval_results/*/summary.json | head -30
```

---

## 11. Suggested live-demo script (about 5 minutes)

1. **Tab 3:** run 5.2 (two tools in one question) and point at `tool_calls` and `trace_id`.
2. **Phoenix:** open that trace → `chat` → `ChatAnthropic` (prompt, tool schemas, tool calls,
   tokens) → TOOL spans (arguments, structured JSON result).
3. **Tab 3:** run 5.3 (same `session_id`). In Phoenix → **Sessions**, show the two turns
   together.
4. **Phoenix:** filter `annotations['user_frustration'].label == 'frustrated'`. Open
   `frustrated_cheap_hotel` #2 ("Forget it ...") → show the judge's explanation, then its TOOL
   span (web search returned ads, not prices) as the root cause.
5. **Phoenix → Datasets → `frustrated-interactions`:** this is the regression set for the next
   iteration.

---

## 12. Stop everything

- Tab 2 (API): `Ctrl + C`
- Tab 1 (Phoenix): `Ctrl + C`. Traces, annotations and datasets are kept in `~/.phoenix/` and
  will be there next time.

---

## Command cheat sheet

```bash
# tab 1
~/.phoenix-venv/bin/phoenix serve

# tab 2
cd ~/git/agent_framework_evaluation/se-interview
poetry run uvicorn api:app --port 8000

# tab 3
cd ~/git/agent_framework_evaluation/se-interview
poetry run pytest                                                   # 30 offline tests
curl localhost:8000/health                                          # {"status":"ok"}
curl -s -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"Weather in Lisbon this weekend and 300 USD in EUR?"}' | python3 -m json.tool
poetry run python -m evals.run_queries                              # Step 4: 22 turns -> prints <RUN_ID>
poetry run python -m evals.export_spans --run-id <RUN_ID>           # Step 4: export spans
poetry run python -m evals.evaluate --run-id <RUN_ID>               # Step 5: frustration eval + dataset
px span list --endpoint http://localhost:6006 --project travel-agent --span-kind LLM TOOL -n 10
px dataset list --endpoint http://localhost:6006
open http://localhost:6006                                          # Phoenix UI
open http://localhost:8000/docs                                     # API UI
```
