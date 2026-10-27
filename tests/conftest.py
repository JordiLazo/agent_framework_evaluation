import os
import sys
from pathlib import Path

# The project is not a package (package-mode = false): make the repo root importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ChatAnthropic needs a key to be constructed; tests never call the Anthropic API.
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-not-used")
# Tests don't send traces to Phoenix (test_observability.py checks the wiring explicitly).
os.environ["PHOENIX_TRACING_ENABLED"] = "false"
