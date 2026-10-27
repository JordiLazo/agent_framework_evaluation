"""Step 4: send every scenario in ``evals/scenarios.py`` through the running API.

Each scenario is one session (multi-turn conversations reuse the same ``session_id``). Each
turn sends span metadata (run id, scenario, turn index, reference frustration label), so the
traces can be filtered in Phoenix, e.g. ``metadata['scenario'] == 'frustrated_units'``.

    poetry run python -m evals.run_queries                     # all 13 sessions / 22 turns
    poetry run python -m evals.run_queries --only weather_weekend currency_simple
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from evals.scenarios import SCENARIOS, Scenario

RUNS_DIR = Path("data/runs")


def run_scenario(client: httpx.Client, scenario: Scenario, run_id: str) -> list[dict[str, Any]]:
    session_id = f"{scenario.id}-{run_id}"
    rows = []
    for index, turn in enumerate(scenario.turns):
        metadata = {
            "traffic": "synthetic",
            "run_id": run_id,
            "scenario": scenario.id,
            "turn_index": index,
            "expected_user_frustration": "frustrated" if turn.expected_frustrated else "not_frustrated",
        }
        try:
            response = client.post(
                "/chat",
                json={"message": turn.message, "session_id": session_id, "metadata": metadata},
            )
            response.raise_for_status()
            body, error = response.json(), None
        except Exception as exc:  # one failing turn must not abort the run
            body, error = {}, f"{type(exc).__name__}: {exc}"
        rows.append(
            {
                "run_id": run_id,
                "scenario": scenario.id,
                "session_id": session_id,
                "turn_index": index,
                "message": turn.message,
                "expected_frustrated": turn.expected_frustrated,
                "response": body.get("response"),
                "trace_id": body.get("trace_id"),
                "tool_calls": body.get("tool_calls", []),
                "error": error,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--only", nargs="*", help="scenario ids to run (default: all)")
    parser.add_argument("--concurrency", type=int, default=4, help="sessions run in parallel")
    args = parser.parse_args(argv)

    scenarios = [s for s in SCENARIOS if not args.only or s.id in args.only]
    if not scenarios:
        print(f"No scenarios match {args.only}", file=sys.stderr)
        return 2
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]

    with httpx.Client(base_url=args.base_url, timeout=180) as client:
        client.get("/health").raise_for_status()
        print(f"run_id={run_id}: {len(scenarios)} sessions, "
              f"{sum(len(s.turns) for s in scenarios)} turns -> {args.base_url}\n")
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            results = list(pool.map(lambda s: run_scenario(client, s, run_id), scenarios))

    rows = [row for scenario_rows in results for row in scenario_rows]
    for row in rows:
        tools = ", ".join(f"{t['name']}[{t.get('status')}]" for t in row["tool_calls"]) or "-"
        status = f"ERROR {row['error']}" if row["error"] else "ok"
        print(f"[{row['scenario']} #{row['turn_index']}] {status} | tools: {tools}")
        print(f"   user : {row['message'][:100]}")
        print(f"   agent: {(row['response'] or '')[:140]!r}")

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RUNS_DIR / f"run_{run_id}.jsonl"
    with out_path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")
    failed = sum(1 for r in rows if r["error"])
    print(f"\n{len(rows)} turns, {failed} failed. Results: {out_path}")
    print(f"Phoenix: filter traces with  metadata['run_id'] == '{run_id}'")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
