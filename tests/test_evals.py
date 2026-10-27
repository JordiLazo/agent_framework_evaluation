"""Steps 4-5: span shaping, CODE evaluator and judge metrics (pure pandas, no network)."""

import json

import pandas as pd

from evals.phoenix_data import binary_metrics, build_turns, evaluate_tool_executions, filter_run
from evals.scenarios import SCENARIOS


def span(span_id, name, kind, parent, trace, t, status="OK", **attrs):
    return {
        "context.span_id": span_id,
        "context.trace_id": trace,
        "name": name,
        "span_kind": kind,
        "parent_id": parent,
        "start_time": pd.Timestamp("2026-10-26T10:00:00Z") + pd.Timedelta(seconds=t),
        "status_code": status,
        **{f"attributes.{k}": v for k, v in attrs.items()},
    }


def tool_output(payload):
    return json.dumps({"type": "tool", "data": {"content": json.dumps(payload), "status": "success",
                                                "artifact": payload}})


SPANS = pd.DataFrame(
    [
        span("r1", "chat", "AGENT", None, "t1", 0, **{
            "session.id": "s", "input.value": "Weather in Rome?", "output.value": "Sunny.",
            "metadata": json.dumps({"run_id": "R", "scenario": "x", "expected_user_frustration": "not_frustrated"})}),
        span("x1", "get_weather_forecast", "TOOL", "n1", "t1", 1, **{
            "tool.name": "get_weather_forecast", "output.value": tool_output({"status": "ok"})}),
        span("r2", "chat", "AGENT", None, "t2", 10, **{
            "session.id": "s", "input.value": "Useless!!", "output.value": "Sorry.",
            "metadata": {"run_id": "R", "expected_user_frustration": "frustrated"}}),
        span("x2", "convert_currency", "TOOL", "n2", "t2", 11, **{
            "tool.name": "convert_currency",
            "output.value": tool_output({"status": "error", "error": {"code": "unsupported_currency", "message": "m"}})}),
        span("x3", "duckduckgo_search", "TOOL", "n2", "t2", 12, status="ERROR", **{
            "tool.name": "duckduckgo_search", "output.value": "boom"}),
        span("r3", "chat", "AGENT", None, "t3", 20, **{
            "session.id": "other", "input.value": "hi", "output.value": "hello",
            "metadata": {"run_id": "OTHER"}}),
    ]
)


def test_scenarios_have_at_least_ten_queries_and_frustrated_examples():
    turns = [t for s in SCENARIOS for t in s.turns]
    assert len(turns) >= 10
    assert sum(t.expected_frustrated for t in turns) >= 3
    assert len({s.id for s in SCENARIOS}) == len(SCENARIOS)


def test_build_turns_orders_sessions_and_builds_history():
    turns = build_turns(SPANS).set_index("span_id")
    assert turns.loc["r1", "conversation"] == "(no previous messages)"
    assert turns.loc["r2", "conversation"] == "USER: Weather in Rome?\nASSISTANT: Sunny."
    assert turns.loc["r2", "turn_index"] == 1
    assert turns.loc["r2", "expected_user_frustration"] == "frustrated"
    assert turns.loc["r3", "turn_index"] == 0  # separate session


def test_filter_run_keeps_only_that_runs_traces():
    assert set(filter_run(SPANS, "R")["context.trace_id"]) == {"t1", "t2"}


def test_tool_execution_code_evaluator():
    out = evaluate_tool_executions(SPANS).set_index("span_id")
    assert out.loc["x1", "label"] == "success"
    assert out.loc["x2", "label"] == "tool_error"
    assert out.loc["x2", "explanation"].startswith("unsupported_currency")
    assert out.loc["x3", "label"] == "exception"


def test_binary_metrics():
    m = binary_metrics([True, True, False, False], [True, False, True, False])
    assert m["confusion"] == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}
    assert (m["accuracy"], m["precision"], m["recall"], m["f1"]) == (0.5, 0.5, 0.5, 0.5)
