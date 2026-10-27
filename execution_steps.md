# Execution steps: running the starter app on macOS

This guide takes you from a Mac with nothing installed to a working app answering questions at
`http://localhost:8000`. It runs the starter repository
[`trevorlaviale/se-interview`](https://github.com/trevorlaviale/se-interview) exactly as
published (Step 1 of the technical assessment). The app is a LangGraph agent that uses GPT-4o
and DuckDuckGo web search, served by FastAPI.

Tested on macOS (Apple Silicon M2 Pro), zsh, Python 3.12.2 (python.org installer) and
Poetry 2.5.1.

Do the steps in order. Each one ends with a **✅ Check**. Don't move on until it passes.

| Step | What you do | Time |
|---|---|---|
| 1 | Open Terminal | 1 min |
| 2 | Install Apple's command line tools (git, curl) | 5 min |
| 3 | Install Python 3.11+ and its SSL certificates | 5 min |
| 4 | Install Poetry | 2 min |
| 5 | Get the code | 1 min |
| 6 | Install the app's dependencies | 2 min |
| 7 | Add your OpenAI API key | 2 min |
| 8 | Start the server | 1 min |
| 9 | Test the app | 2 min |
| 10 | Stop it, and start it again later | — |

> **You need an OpenAI API key** (https://platform.openai.com/api-keys) on an account with
> credit and access to `gpt-4o`. The starter hard-codes `ChatOpenAI(model="gpt-4o")` in
> `agent.py`, so an Anthropic (Claude) key won't work without changing the code.

---

## Step 1: Open Terminal

Press `⌘ + Space`, type **Terminal** and press Enter. Every command below goes into this window.
Paste a command with `⌘ + V` and press Enter.

macOS uses the **zsh** shell, and its settings file is `~/.zshrc`. Some steps add a line to it.

---

## Step 2: Install Apple's command line tools (git, curl)

```bash
xcode-select --install
```

- If a dialog appears, click **Install** and wait for it to finish (around 5 minutes).
- If you see `command line tools are already installed`, there's nothing to do.

**✅ Check**

```bash
git --version     # e.g. git version 2.39.5 (Apple Git-154)
curl --version    # prints curl 8.x ...
```

---

## Step 3: Install Python 3.11 or newer, and its certificates

### 3.1 Check whether you already have it

```bash
python3 --version
```

- If it shows **Python 3.11.x, 3.12.x or 3.13.x**, go to **3.3**.
- If it shows Python 3.9 / 3.10 or `command not found`, do **3.2**.

### 3.2 Install Python (choose ONE option)

**Option A: python.org installer (recommended)**

1. Go to https://www.python.org/downloads/macos/ and download the **macOS 64-bit universal2
   installer** for Python **3.12.x**.
2. Open the `.pkg` file and click through the installer.
3. **Close Terminal completely (`⌘ + Q`) and open it again** so it picks up the new Python.

**Option B: Homebrew**

```bash
# Install Homebrew first if `brew --version` fails:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zshrc && source ~/.zshrc

brew install python@3.12
```

### 3.3 Install the SSL certificates (python.org Python only, required)

Python from the python.org installer ships **without** root certificates. Until you install
them, every HTTPS download from Python fails with
`SSL: CERTIFICATE_VERIFY_FAILED ... unable to get local issuer certificate`, including the
Poetry installer in Step 4. Run the one-time script that comes with Python:

```bash
open "/Applications/Python 3.12/Install Certificates.command"
```

Change `3.12` to your version if it's different (`ls /Applications | grep Python` shows it). A
new Terminal window opens. Wait until it prints `-- update complete`, then close that window.

If you installed Python with Homebrew (Option B), skip this; Homebrew sets up certificates for
you.

**✅ Check**

```bash
python3 --version
python3 -c "import urllib.request; urllib.request.urlopen('https://pypi.org'); print('SSL OK')"
```

You should see your Python version and then `SSL OK`. If you get a `CERTIFICATE_VERIFY_FAILED`
error instead, repeat 3.3.

---

## Step 4: Install Poetry

Poetry is the dependency manager the project uses (`pyproject.toml` + `poetry.lock`).

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

The installer puts Poetry in `~/.local/bin`. Add that folder to your PATH permanently and
reload the shell:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**✅ Check**

```bash
poetry --version     # Poetry (version 2.x.x)
```

<details>
<summary>If the official installer doesn't work for you, use one of these instead</summary>

```bash
# Alternative 1: Homebrew + pipx
brew install pipx
pipx ensurepath && source ~/.zshrc
pipx install poetry

# Alternative 2: a dedicated virtualenv (pip has its own certificates, so this
# works even before Step 3.3)
python3 -m venv ~/.poetry-venv
~/.poetry-venv/bin/pip install poetry
echo 'alias poetry="$HOME/.poetry-venv/bin/poetry"' >> ~/.zshrc && source ~/.zshrc
```
</details>

---

## Step 5: Get the code

Go to the folder where you keep projects and clone the repository:

```bash
mkdir -p ~/git && cd ~/git
git clone https://github.com/trevorlaviale/se-interview.git
cd se-interview
```

> If you already cloned it inside this assessment folder, just go there:
> `cd ~/git/agent_framework_evaluation/se-interview`

**✅ Check**

```bash
ls
# .env.example  README.md  __init__.py  agent.py  api.py  poetry.lock  pyproject.toml
```

(`.env.example` only shows with `ls -a`.)

---

## Step 6: Install the app's dependencies

Run this **inside the `se-interview` folder**:

```bash
poetry install
```

Poetry creates an isolated virtual environment and installs the exact versions pinned in
`poetry.lock`, for example `langgraph 0.2.76`, `langchain-openai 0.2.14`, `fastapi`,
`uvicorn 0.32.1` and `ddgs`. Warnings such as `[tool.poetry.authors] is deprecated` are
harmless.

If Poetry picks the wrong Python, point it at the right one and install again:

```bash
poetry env use python3.12
poetry install
```

**✅ Check**

```bash
poetry run python --version                     # Python 3.11+ 
poetry run python -c "import langgraph, fastapi; print('deps OK')"
```

---

## Step 7: Add your OpenAI API key

1. Create an API key at https://platform.openai.com/api-keys and copy it (it starts with
   `sk-`). Make sure the account has billing/credit.
2. Create your `.env` file from the template:

   ```bash
   cp .env.example .env
   ```

3. Open it in TextEdit:

   ```bash
   open -e .env
   ```

4. Replace the placeholder so the file contains exactly one line, with no quotes and no spaces
   around `=`:

   ```
   OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxx
   ```

5. Save with `⌘ + S` and close TextEdit.

`.env` is listed in `.gitignore`, so the key is never committed. Don't paste the key anywhere
else.

**✅ Check** (prints only the first characters of the key)

```bash
grep -o '^OPENAI_API_KEY=sk-.\{4\}' .env    # OPENAI_API_KEY=sk-proj
```

---

## Step 8: Start the server

```bash
poetry run uvicorn api:app --reload
```

**✅ Check:** the output ends with:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Application startup complete.
```

Leave this window open, because it is the running server and its log. `--reload` restarts it
whenever you edit a `.py` file.

---

## Step 9: Test the app

Open a **new Terminal tab** with `⌘ + T`. The server keeps running in the first tab.

### 9.1 Health check (doesn't call OpenAI)

```bash
curl http://localhost:8000/health
```

**✅ Expected:** `{"status":"ok"}`

### 9.2 Ask the agent a question (calls GPT-4o and maybe DuckDuckGo)

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What are the top attractions in Lisbon?"}'
```

**✅ Expected** after a few seconds:

```json
{"response": "Here are some of the top attractions in Lisbon: ..."}
```

In the server tab you'll see `"POST /chat HTTP/1.1" 200 OK`.

### 9.3 Use the browser UI

```bash
open http://localhost:8000/docs
```

Swagger UI opens in your browser. Click **POST /chat**, then **Try it out**, edit the message
and click **Execute**.

---

## Step 10: Stop the app, and start it again later

**Stop:** go to the server tab and press `Ctrl + C`.

**Start again later:** Steps 1–7 only need to be done once. After that:

```bash
cd ~/git/se-interview        # or ~/git/agent_framework_evaluation/se-interview
poetry run uvicorn api:app --reload
```

**Optional: work inside the virtual environment** so you don't need `poetry run`:

```bash
source "$(poetry env info --path)/bin/activate"
uvicorn api:app --reload
deactivate        # when you're done
```

---

## How a request flows (for reference)

1. `POST /chat` (`api.py`) wraps the message in a `HumanMessage` and calls the compiled graph.
2. The `llm_call` node (`agent.py`) sends a system prompt and the messages to GPT-4o, with the
   DuckDuckGo search tool bound.
3. If GPT-4o returns tool calls, `should_continue` routes to `tool_node`. That node runs the
   search and appends a `ToolMessage`, then control goes back to `llm_call`.
4. When GPT-4o answers without tool calls, the graph ends and the last message's content is
   returned as `{"response": ...}`.

```
START -> llm_call --(tool calls?)--> tool_node -> llm_call -> ... -> END
```

Each request is **stateless**: the API keeps no conversation memory between calls.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `xcrun: error: invalid active developer path` when running `git` | Command line tools are missing or broken (common after a macOS update) | `xcode-select --install` (Step 2) |
| Poetry installer fails with `SSL: CERTIFICATE_VERIFY_FAILED ... unable to get local issuer certificate` | python.org Python without certificates | Step 3.3: `open "/Applications/Python 3.12/Install Certificates.command"`, then rerun Step 4 |
| `command not found: poetry` | `~/.local/bin` is not on your PATH, or Terminal wasn't reloaded | `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc` |
| `The currently activated Python version 3.9.x is not supported by the project (^3.11)` | Poetry picked macOS's old system Python | `poetry env use python3.12 && poetry install` |
| `[Errno 48] Address already in use` | Port 8000 is taken (often an old server still running) | `lsof -i :8000` and then `kill <PID>`, or start on another port: `--port 8001` |
| `ModuleNotFoundError: No module named 'langgraph'` | Running `uvicorn` outside Poetry's virtualenv | Prefix with `poetry run`, or activate the venv (Step 10) |
| `/health` works but `/chat` returns `Internal Server Error`, and the server log shows `openai.AuthenticationError: Error code: 401` | Missing, wrong or placeholder `OPENAI_API_KEY`, or `.env` is not in the folder you started the server from | Fix `.env` (Step 7), make sure you're in `se-interview/`, and restart the server |
| Log shows `openai.RateLimitError` / `insufficient_quota` | The OpenAI account has no credit | Add billing on platform.openai.com |
| Log shows `NotFoundError ... model gpt-4o` | The key's project can't use `gpt-4o` | Use a key with access, or change the model in `agent.py` |
| `/chat` is slow, or the log shows `RatelimitException` from DuckDuckGo | DuckDuckGo throttled your IP | Wait a minute and retry; GPT-4o can still answer without search |
| `curl: (7) Failed to connect to localhost port 8000` | The server isn't running | Start it (Step 8) and keep that tab open |

---

## Quick reference (after first-time setup)

```bash
cd ~/git/se-interview                  # project folder
poetry install                         # only after pulling new dependencies
poetry run uvicorn api:app --reload    # start the server (tab 1)

# tab 2 (⌘ + T)
curl http://localhost:8000/health
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"Hello"}'
open http://localhost:8000/docs
```
