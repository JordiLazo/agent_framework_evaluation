# Step 1: Run the app on macOS (with Claude)

This guide gets the travel agent in `se-interview/` running on your Mac and answering at
`http://localhost:8000`. The app was originally written for OpenAI; it now runs on **Claude
(Anthropic)**. The changes are listed at the end.

Each step ends with a **✅ Check**. Do the steps in order.

---

## 1. Open Terminal

Press `⌘ + Space`, type **Terminal** and press Enter. Run every command below there.

## 2. Install Apple's command line tools

```bash
xcode-select --install
```

Click **Install** if a dialog appears. If it says the tools are already installed, continue.

**✅ Check:** `git --version` prints a version.

## 3. Install Python 3.12

1. Download the **macOS installer for Python 3.12** from https://www.python.org/downloads/macos/
   and run it.
2. Install its SSL certificates (needed once, for HTTPS downloads):

   ```bash
   open "/Applications/Python 3.12/Install Certificates.command"
   ```

   Wait for `-- update complete`, then close that window.
3. Quit Terminal (`⌘ + Q`) and open it again.

**✅ Check:** `python3 --version` prints `Python 3.12.x` (3.11–3.13 also work).

## 4. Install Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**✅ Check:** `poetry --version` prints `Poetry (version 2.x.x)`.

## 5. Go to the project

```bash
cd ~/git/agent_framework_evaluation/se-interview
```

(On a new machine, clone it first:
`git clone https://github.com/trevorlaviale/se-interview.git && cd se-interview`.)

**✅ Check:** `ls` shows `agent.py`, `api.py`, `observability.py`, `tools`, `pyproject.toml`.

## 6. Install the dependencies

```bash
poetry install
```

**✅ Check:** `poetry run python -c "import langchain_anthropic; print('OK')"` prints `OK`.

## 7. Add your Anthropic API key

1. Create a key at https://platform.claude.com/settings/keys. It starts with `sk-ant-`, and
   the account needs credit.
2. Create the settings file and open it:

   ```bash
   cp .env.example .env
   open -e .env
   ```

3. Change these two lines, then save (`⌘ + S`):

   ```
   ANTHROPIC_API_KEY=sk-ant-...your key...
   PHOENIX_TRACING_ENABLED=false
   ```

   Tracing stays off until Phoenix is running in Step 3.

**✅ Check:** `grep -c '^ANTHROPIC_API_KEY=sk-ant-' .env` prints `1`.

## 8. Start the app

```bash
poetry run uvicorn api:app --reload
```

**✅ Check:** the output ends with `Application startup complete.` Leave this window open.

## 9. Try it

Open a second Terminal tab (`⌘ + T`) and run:

```bash
curl http://localhost:8000/health
```

**✅ Check:** `{"status":"ok"}`

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the weather in Lisbon this weekend, and how much is 300 USD in EUR?"}'
```

**✅ Check:** a JSON answer with `"response"` and a `"tool_calls"` list (here
`get_weather_forecast` and `convert_currency`).

You can also use the browser: `open http://localhost:8000/docs` → **POST /chat** →
**Try it out** → **Execute**.

## 10. Stop and restart

- **Stop:** press `Ctrl + C` in the server tab.
- **Start again later:**

  ```bash
  cd ~/git/agent_framework_evaluation/se-interview
  poetry run uvicorn api:app --reload
  ```

---

## Quick reference

```bash
cd ~/git/agent_framework_evaluation/se-interview
poetry install
cp .env.example .env && open -e .env          # set ANTHROPIC_API_KEY (and tracing=false until Step 3)
poetry run uvicorn api:app --reload           # tab 1
curl http://localhost:8000/health             # tab 2
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"message":"Hello"}'
```

---

## Changes made to run on Claude (Anthropic) instead of OpenAI

| What | Before (starter) | Now |
|---|---|---|
| LLM | `ChatOpenAI(model="gpt-4o", temperature=0)` | `ChatAnthropic(model="claude-haiku-5-5", max_tokens=4096)`, the **cheapest Claude model** ($0.10 / $0.50 per million input/output tokens) |
| API key | `OPENAI_API_KEY` | `ANTHROPIC_API_KEY` (from https://platform.claude.com/settings/keys) |
| Model choice | Hard-coded | Default `claude-haiku-5-5`; optional `ANTHROPIC_MODEL` in `.env` to change it (e.g. `claude-sonnet-5-5`) |
| Dependency | `langchain-openai` (+ `openai`, `tiktoken`) | `langchain-anthropic 0.3.22` (+ `anthropic` SDK). LangGraph and LangChain keep the same versions |
| `temperature` | `0` | Not sent: current Claude models reject sampling parameters |
| Reply format | Plain string | Claude returns content blocks (`thinking` + `text`); a new `message_text()` in `agent.py` returns only the text, so `/chat` still gives a plain `"response"` string |
| `.env.example` | `OPENAI_API_KEY=...` | `ANTHROPIC_API_KEY`, optional `ANTHROPIC_MODEL`, and Phoenix settings for Step 3 |
| Python range | `^3.11` | `>=3.11,<3.14` (required by the Phoenix packages added in Step 3) |
| Tests | Dummy OpenAI key | Dummy Anthropic key; new tests check the default model, that no `temperature` is sent, and the text extraction |

Files changed for the switch: `agent.py`, `api.py`, `pyproject.toml`, `poetry.lock`,
`.env.example`, `README.md`, `tests/conftest.py`, `tests/test_agent.py`.
