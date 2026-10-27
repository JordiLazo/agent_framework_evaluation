# Step 3: Phoenix observability

## What the assessment asks

> Install and run Arize Phoenix locally. You may run Phoenix using a local Python environment,
> Docker or Kubernetes. Instrument the LangGraph agent using Phoenix integrations. We highly
> recommend leveraging PX CLI + PX skills here. Your Phoenix instance should capture:
> - LLM calls
> - Tool usage

## Summary

- **Phoenix runs locally** in its own Python environment (`arize-phoenix` 20.26.1, UI and
  collector on `http://localhost:6006`). Docker is a one-line alternative.
- **The agent is instrumented** with Phoenix's LangChain integration: `phoenix.otel.register`
  plus OpenInference `LangChainInstrumentor`, in a new `observability.py` that the API calls at
  startup.
- **Every `/chat` request becomes one trace** containing the LangGraph run, each graph node,
  every **LLM call** (Claude: messages, tool schemas, tool calls, tokens) and every **tool
  call** (arguments plus the structured result).
- **PX CLI:** `px span list` lists LLM and TOOL spans from the terminal. **PX skills:**
  `px setup skills` lets a coding agent (e.g. Claude Code) query the traces.
- **Verified:** a run pushed to a real local Phoenix produced the expected tree, including the
  2 LLM spans and the `get_weather_forecast` / `convert_currency` TOOL spans, read back with the
  `px` CLI. 22 offline tests pass, including a tracing test.

---

## Key concepts (for the presentation)

| Term | Meaning here |
|---|---|
| **OpenTelemetry (OTel)** | Vendor-neutral standard for telemetry. It defines the API/SDK to create spans and the OTLP protocol to export them. Phoenix accepts OTLP at `/v1/traces`. |
| **OpenInference** | Arize's open conventions on top of OTel for AI apps. It defines span kinds (`LLM`, `TOOL`, `CHAIN`, `AGENT`, `RETRIEVER`, ...) and attribute names (`llm.input_messages`, `llm.token_count.total`, `tool.name`, `input.value`, ...), plus auto-instrumentors for frameworks such as LangChain. |
| **Span** | One unit of work with a start/end time, a status and attributes, e.g. one Claude call or one `convert_currency` execution. |
| **Trace** | The tree of spans for one request, linked by a shared `trace_id` and parent/child IDs. Here, one `/chat` call = one trace. |
| **Project** | A Phoenix grouping of traces, here `travel-agent` (set by `PHOENIX_PROJECT_NAME`). |

What one `/chat` request looks like in Phoenix:

```
LangGraph                       CHAIN   whole request: input = user message, output = final state
├─ llm_call                     CHAIN   graph node
│  └─ ChatAnthropic             LLM     model, messages, tool schemas, tool calls, token counts
│  └─ should_continue           CHAIN   routing decision
├─ tool_node                    CHAIN   graph node
│  ├─ get_weather_forecast      TOOL    arguments + structured JSON result
│  └─ convert_currency          TOOL    arguments + structured JSON result
└─ llm_call                     CHAIN
   └─ ChatAnthropic             LLM     final answer
```

LangGraph 0.2 also emits small internal spans (`__start__`, `ChannelWrite<...>`). They are
expected and can be filtered out in the UI.

---

## Changes made

All paths are in `se-interview/`.

| File | Change |
|---|---|
| `observability.py` | **New.** `setup_tracing()`: `phoenix.otel.register(project_name, endpoint=…/v1/traces, batch=True, auto_instrument=False)` + `LangChainInstrumentor().instrument(tracer_provider=…)`. Idempotent; reads `PHOENIX_*` env vars; `PHOENIX_TRACING_ENABLED=false` turns it off. `shutdown_tracing()` flushes buffered spans. |
| `api.py` | Calls `setup_tracing()` **before** `build_agent()`, and flushes spans on shutdown via a FastAPI `lifespan` handler. |
| `pyproject.toml` / `poetry.lock` | Adds `arize-phoenix-otel` (0.17.2) and `openinference-instrumentation-langchain` (0.1.80), which pull in the OpenTelemetry SDK and OTLP exporters. The Python range becomes `>=3.11,<3.14` because the Phoenix packages require it. LangGraph and LangChain versions are unchanged. |
| `.env.example` | Adds `PHOENIX_TRACING_ENABLED`, `PHOENIX_COLLECTOR_ENDPOINT`, `PHOENIX_PROJECT_NAME`. |
| `tests/test_observability.py` | **New.** Checks that tracing can be disabled, and that a graph run produces `CHAIN`, `LLM` and `TOOL` spans with the tool arguments, using an in-memory exporter. |
| `tests/conftest.py` | Tracing is off by default in tests, so tests never need a Phoenix server. |
| `README.md` | New "Run Phoenix" and "Observability" sections. |

The core of `observability.py`:

```python
tracer_provider = register(
    project_name="travel-agent",                      # PHOENIX_PROJECT_NAME
    endpoint="http://localhost:6006/v1/traces",       # PHOENIX_COLLECTOR_ENDPOINT + /v1/traces
    batch=True,                                       # export in the background
    auto_instrument=False,                            # explicit instrumentation below
)
LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
```

---

## How to run it (macOS)

This assumes Step 1 is done (`poetry install`, `ANTHROPIC_API_KEY` in `.env`).

### 1. Install and start Phoenix (terminal 1)

Phoenix gets its own virtual environment. It is a server, not an app dependency.

```bash
python3 -m venv ~/.phoenix-venv
~/.phoenix-venv/bin/pip install arize-phoenix
~/.phoenix-venv/bin/phoenix serve
```

Open http://localhost:6006 to see the Phoenix UI.

(Docker alternative: `docker run -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest`)

### 2. Turn tracing on

In `se-interview/.env`:

```
PHOENIX_TRACING_ENABLED=true
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006
PHOENIX_PROJECT_NAME=travel-agent
```

### 3. Start the app (terminal 2)

```bash
cd ~/git/agent_framework_evaluation/se-interview
poetry run uvicorn api:app --reload
```

### 4. Send a few requests (terminal 3)

```bash
curl -s -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"What is the weather in Lisbon this weekend, and how much is 300 USD in EUR?"}'
curl -s -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"What are the top attractions in Porto?"}'
```

### 5. See the traces

- **UI:** http://localhost:6006 → project **travel-agent** → open a trace to see the tree, each
  Claude call (prompt, tool calls, tokens, latency) and each tool call (arguments, JSON
  result).
- **PX CLI:**

  ```bash
  npm install -g @arizeai/phoenix-cli --legacy-peer-deps   # needs Node.js 18+
  px span list --endpoint http://localhost:6006 --project travel-agent --span-kind LLM -n 10
  px span list --endpoint http://localhost:6006 --project travel-agent --span-kind TOOL -n 10
  ```

  `--legacy-peer-deps` works around an npm 10 bug (`Cannot read properties of null (reading
  'edgesOut')`) seen on this machine.

### 6. PX skills (optional, for coding agents)

```bash
px setup skills     # installs the Phoenix skills for coding agents such as Claude Code
px docs fetch       # downloads Phoenix docs into .px/docs for the agent to read
```

With the skills installed, you can ask a coding agent questions like "show me the slowest LLM
calls in project travel-agent" and it will run `px` commands for you.

---

## What gets captured

| Span kind | Example name | Key attributes |
|---|---|---|
| `LLM` | `ChatAnthropic` | `llm.model_name` (`claude-haiku-5-5`), `llm.provider` (`anthropic`), `llm.input_messages`, `llm.output_messages` (incl. `tool_calls`), `llm.tools` (the 3 tool schemas), `llm.token_count.prompt/completion/total`, `llm.invocation_parameters`, latency, status |
| `TOOL` | `get_weather_forecast`, `convert_currency`, `duckduckgo_search` | `tool.name`, `tool.description`, `input.value` (the arguments), `output.value` (the structured `ToolMessage` with the JSON content and `status`), latency, status |
| `CHAIN` | `LangGraph`, `llm_call`, `tool_node`, `should_continue` | `input.value` / `output.value` of each node, so you can follow the agent loop step by step |

Because the Step 2 tools return `{"status": "ok"|"error", "error": {"code": ...}}`, a failed
lookup (e.g. `unsupported_currency`) is visible directly in the TOOL span output. That is the
basis for the tracing and evaluation work in Steps 4–5.

---

## Design decisions

1. **Phoenix's official LangChain integration, not hand-written spans.** `LangChainInstrumentor`
   understands LangGraph nodes, chat models and tools, so LLM and tool spans come with the
   standard OpenInference attributes Phoenix's UI and evals expect. No agent code had to change.
2. **Explicit instrumentation (`auto_instrument=False`).** Only LangChain is instrumented. If the
   Anthropic SDK were also auto-instrumented, every Claude call would appear twice (LangChain
   span + SDK span).
3. **`batch=True`.** Spans are exported by a background thread, so tracing adds no latency to
   `/chat` and a slow or unavailable Phoenix never fails a request. Tested: with Phoenix down,
   the app still answers and only logs export warnings.
4. **Tracing set up before the agent is built**, then flushed on shutdown so the last requests
   are not lost.
5. **Configuration through environment variables** (`PHOENIX_*`). The same code works with a
   local Phoenix, Docker, Kubernetes or Phoenix Cloud, and tracing can be switched off without
   code changes.
6. **Phoenix server outside the app's dependencies.** `arize-phoenix` is a large server package
   with its own Python constraints. Keeping it in its own venv (or Docker) keeps the app's
   lock file small and lets the two be upgraded independently.
7. **Tested without a server.** `test_observability.py` attaches an in-memory span exporter and
   asserts that `LLM` and `TOOL` spans are produced, so instrumentation regressions are caught
   in CI.

---

## Verification status

| Check | Result |
|---|---|
| Phoenix 20.26.1 installed in its own venv and served on `localhost:6006` | ✅ |
| Traced agent run exported to Phoenix and read back with `px span list` (PX CLI 1.18.9) | ✅ `LangGraph` → `llm_call` → **LLM** span; `tool_node` → **TOOL** `get_weather_forecast` + **TOOL** `convert_currency` (real Open-Meteo and Frankfurter calls); final **LLM** span |
| Unit tests incl. tracing test (`poetry run pytest`) | ✅ 22 passed |
| App wired to the real Anthropic API | ✅ A dummy key gets `anthropic.AuthenticationError 401` from Anthropic, as expected |
| Real `ChatAnthropic` LLM span attributes in Phoenix (from that failed call) | ✅ `llm.model_name=claude-haiku-5-5`, `llm.provider=anthropic`, `llm.tools.0-2` (the 3 tool schemas), `llm.invocation_parameters`, `metadata.langgraph_node=llm_call`; status `ERROR` with the 401 recorded |
| App keeps working when Phoenix is down | ✅ |
| LLM spans from **real Claude calls** (`ChatAnthropic`, model, token counts) | ⏳ Needs your `ANTHROPIC_API_KEY` in `se-interview/.env`. During verification the LLM was a scripted stand-in, so its span is named `FakeToolModel`. |
