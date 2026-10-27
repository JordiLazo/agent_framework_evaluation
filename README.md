# Travel Agent: LangGraph + Claude + Arize Phoenix

An AI **travel assistant** you can chat with over an HTTP API. It's fully **observable** and
**evaluated**:

- 🤖 **Agent:** a LangGraph agent powered by **Claude Haiku 5.5** (Anthropic). It answers
  travel questions by calling tools:
  - **web search** (DuckDuckGo) for flights, hotels and attractions;
  - **weather forecast** (Open-Meteo) for the next 15 days;
  - **currency conversion** (European Central Bank rates).
- 💬 **Conversations:** it remembers earlier messages in the same session.
- 🔭 **Observability:** every request is traced in **Arize Phoenix** (OpenTelemetry /
  OpenInference): each LLM call, each tool call, tokens and latency.
- 🧪 **Evaluation:** an LLM-as-a-judge detects **frustrated users**. Results are attached to the
  traces in Phoenix, and frustrated conversations are collected into a Phoenix dataset.

```
you ──HTTP──► API :8000 ──► LangGraph agent ──► Claude Haiku 5.5
                              │                 tools: web search · weather · currency
                              └──── traces ────► Phoenix :6006 ◄── evaluations + datasets
```

---

## ⚡ Quick start

**You need:** macOS/Linux, Python 3.11–3.13,
[Poetry](https://python-poetry.org/docs/#installation), and an
[Anthropic API key](https://platform.claude.com/settings/keys).

### 1. Install (once)

```bash
git clone https://github.com/JordiLazo/agent_framework_evaluation.git
cd agent_framework_evaluation

poetry install                                   # the app + tests + evaluation tools

python3 -m venv ~/.phoenix-venv                  # Phoenix gets its own environment
~/.phoenix-venv/bin/pip install arize-phoenix
```

### 2. Configure (once)

```bash
cp .env.example .env
open -e .env        # set ANTHROPIC_API_KEY=sk-ant-...   (Linux: nano .env)
```

### 3. Run: two terminals

```bash
# Terminal 1: Phoenix (traces UI)
~/.phoenix-venv/bin/phoenix serve
```

```bash
# Terminal 2: the agent API
poetry run uvicorn api:app --port 8000
```

- Phoenix UI: **http://localhost:6006**
- API docs: **http://localhost:8000/docs**

### 4. Chat with it: a third terminal

```bash
curl -s -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"What is the weather in Lisbon this weekend, and how much is 300 USD in EUR?"}' \
  | python3 -m json.tool
```

```json
{
  "response": "Lisbon this weekend (Sat 31 Oct – Sun 1 Nov): overcast, 16–26 °C, dry ... 300 USD ≈ 268.14 EUR (ECB rate, 26 Oct 2026).",
  "session_id": "582b3068-d82c-4c83-ae93-b9e55fe2c8b6",
  "trace_id": "3b1d83452b54eaf9c2c8ad6ece56df4f",
  "tool_calls": [
    {"name": "get_weather_forecast", "args": {"city": "Lisbon, Portugal", "start_date": "2026-10-31", "end_date": "2026-11-01"}, "status": "ok"},
    {"name": "convert_currency", "args": {"amount": 300, "from_currency": "USD", "to_currency": "EUR"}, "status": "ok"}
  ]
}
```

To continue the conversation, send the `session_id` back:

```bash
curl -s -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"And what about Porto on the same days?","session_id":"<session_id from above>"}' \
  | python3 -m json.tool
```

Then open **http://localhost:6006** → project **travel-agent** to see the trace: the Claude
calls, the tool calls, tokens and latency.

### 5. Generate traffic, export it, evaluate it

```bash
poetry run python -m evals.run_queries                 # 13 conversations / 22 messages -> prints a RUN_ID
poetry run python -m evals.export_spans --run-id <RUN_ID>   # spans -> data/exports/*.jsonl + .csv
poetry run python -m evals.evaluate --run-id <RUN_ID>       # frustration eval -> Phoenix annotations + dataset
```

Example output of the evaluation:

```
Evaluating 22 turns from 13 sessions (project=travel-agent, judge=claude-haiku-5-5) ...
  "frustrated_turns": 5,
  "user_frustration_vs_reference": {"accuracy": 1.0, "precision": 1.0, "recall": 1.0, ...},
  "dataset": {"created": true, "name": "frustrated-interactions-...", "examples": 5}
```

In Phoenix:

- Filter frustrated messages with
  `annotations['user_frustration'].label == 'frustrated'`.
- The **Datasets** tab has the `frustrated-interactions-*` dataset.
- The **Sessions** tab shows each conversation.

### 6. Run the tests (offline, no key needed)

```bash
poetry run pytest          # 30 passed
```

The whole 22-message run costs about **$0.02** in Claude tokens (agent + judge).

---

## How it works

1. `POST /chat` receives a message, plus an optional `session_id` to continue a conversation.
2. The LangGraph agent sends the conversation and the 3 tool schemas to Claude.
3. Claude answers directly, or calls tools (several at once if needed). The tools return
   structured JSON, including clear errors such as `out_of_forecast_range` or
   `unsupported_currency`.
4. The loop repeats until Claude gives a final answer. The API returns the answer, the tools
   used, the `session_id` and the `trace_id`.
5. Every step is exported to Phoenix as one trace:

```
chat                          AGENT  user message → final answer (session, metadata)
└─ LangGraph                  CHAIN
   ├─ llm_call → ChatAnthropic        LLM   prompt, tool calls, tokens
   ├─ tool_node → get_weather_forecast TOOL  arguments → JSON result
   │             convert_currency      TOOL
   └─ llm_call → ChatAnthropic        LLM   final answer
```

**Evaluation** (`evals/evaluate.py`):

- `user_frustration`: a Claude judge scores each user message, using the earlier conversation
  as context.
- `user_friction`: Phoenix's built-in evaluator, as a second opinion.
- `tool_execution`: a code check marks every tool call as success or error.
- Results are written to Phoenix as span and session annotations, and the frustrated messages
  are saved as a dataset.

---

## Project structure

```
agent_framework_evaluation/
├── api.py                  FastAPI server: /chat, /health
├── agent.py                LangGraph agent: Claude model, system prompt, tool loop
├── observability.py        Phoenix tracing setup + one "chat" span per message
├── tools/
│   ├── weather.py          get_weather_forecast (Open-Meteo)
│   ├── currency.py         convert_currency (ECB rates via Frankfurter)
│   ├── schemas.py          Pydantic input/output models for the tools
│   └── http.py             HTTP helper with timeouts and retries
├── evals/
│   ├── scenarios.py        test conversations (13 sessions / 22 messages)
│   ├── run_queries.py      sends the scenarios through the API
│   ├── export_spans.py     exports spans from Phoenix (JSONL + CSV)
│   ├── evaluate.py         frustration eval -> Phoenix annotations + dataset
│   ├── prompts.py          judge prompt
│   └── phoenix_data.py     span helpers and metrics
├── tests/                  30 offline tests (fake LLM, mocked HTTP)
├── doc/                    detailed guides
├── data/                   generated runs, span exports and eval results (git-ignored)
├── .env.example            settings template (copy to .env)
├── pyproject.toml          dependencies (Poetry)
└── poetry.lock             pinned dependency versions
```

## Configuration (`.env`)

| Variable | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | none (required) | Your Claude API key |
| `ANTHROPIC_MODEL` | `claude-haiku-5-5` | Agent model (the cheapest Claude model) |
| `JUDGE_MODEL` | `claude-haiku-5-5` | Model used by the evaluators |
| `PHOENIX_TRACING_ENABLED` | `true` | Set to `false` to run without Phoenix |
| `PHOENIX_COLLECTOR_ENDPOINT` | `http://localhost:6006` | Phoenix address |
| `PHOENIX_PROJECT_NAME` | `travel-agent` | Phoenix project for the traces |

## Stop

Press `Ctrl + C` in each terminal. Phoenix keeps its traces, annotations and datasets in
`~/.phoenix/` for next time.
