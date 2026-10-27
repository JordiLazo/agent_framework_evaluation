"""Phoenix access + pure pandas helpers that shape raw spans into evaluation units."""

from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd

ROOT_SPAN_NAME = "chat"
SESSION_COL = "attributes.session.id"


# --------------------------------------------------------------------------- Phoenix access


def phoenix_base_url() -> str:
    url = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006").rstrip("/")
    return url.removesuffix("/v1/traces")


def project_name() -> str:
    return os.getenv("PHOENIX_PROJECT_NAME", "travel-agent")


def phoenix_client():
    from phoenix.client import Client

    return Client(base_url=phoenix_base_url(), api_key=os.getenv("PHOENIX_API_KEY"))


def fetch_spans(client, project: str, *, limit: int = 20_000) -> pd.DataFrame:
    df = client.spans.get_spans_dataframe(project_identifier=project, limit=limit, timeout=60)
    if df is None or df.empty:
        return pd.DataFrame()
    if df.index.name == "context.span_id" and "context.span_id" not in df.columns:
        df = df.reset_index()
    return df.sort_values("start_time").reset_index(drop=True)


# --------------------------------------------------------------------------- parsing


def as_obj(value: Any) -> Any:
    """Span attributes may arrive as JSON strings or already-parsed objects."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def metadata_of(row: pd.Series) -> dict[str, Any]:
    meta = as_obj(row.get("attributes.metadata"))
    return meta if isinstance(meta, dict) else {}


def filter_run(spans: pd.DataFrame, run_id: str) -> pd.DataFrame:
    """Keep only the traces whose root span carries metadata run_id == ``run_id``."""
    traces = {
        row["context.trace_id"]
        for _, row in spans.iterrows()
        if metadata_of(row).get("run_id") == run_id
    }
    return spans[spans["context.trace_id"].isin(traces)]


# --------------------------------------------------------------------------- turns


def build_turns(spans: pd.DataFrame) -> pd.DataFrame:
    """One row per user turn (root ``chat`` span) with the prior conversation as context."""
    if spans.empty:
        return pd.DataFrame()
    roots = spans[(spans["name"] == ROOT_SPAN_NAME) & spans["parent_id"].isna()].copy()
    if roots.empty:
        return pd.DataFrame()
    if SESSION_COL not in roots.columns:
        roots[SESSION_COL] = None
    roots[SESSION_COL] = roots[SESSION_COL].fillna(roots["context.trace_id"])
    rows = []
    for session_id, group in roots.sort_values("start_time").groupby(SESSION_COL, sort=False):
        history: list[str] = []
        for turn_index, (_, row) in enumerate(group.iterrows()):
            user_message = str(row.get("attributes.input.value") or "")
            assistant = str(row.get("attributes.output.value") or "")
            meta = metadata_of(row)
            rows.append(
                {
                    "span_id": row["context.span_id"],
                    "trace_id": row["context.trace_id"],
                    "session_id": session_id,
                    "turn_index": turn_index,
                    "conversation": "\n".join(history) if history else "(no previous messages)",
                    "user_message": user_message,
                    "assistant_response": assistant,
                    "scenario": meta.get("scenario"),
                    "expected_user_frustration": meta.get("expected_user_frustration"),
                }
            )
            history += [f"USER: {user_message}", f"ASSISTANT: {assistant}"]
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- tool executions


def _tool_payload(output_value: Any) -> tuple[dict[str, Any] | None, str | None]:
    """(structured tool result, ToolMessage status) from a TOOL span's output.value."""
    out = as_obj(output_value)
    message_status, content = None, out
    if isinstance(out, dict) and "data" in out:  # a serialized ToolMessage
        data = out.get("data") or {}
        message_status = data.get("status")
        content = data.get("artifact") or as_obj(data.get("content"))
    return (content if isinstance(content, dict) else None), message_status


def evaluate_tool_executions(spans: pd.DataFrame) -> pd.DataFrame:
    """Deterministic CODE evaluator: did each tool call succeed?

    success    - span OK and the tool's structured result says status == "ok"
                 (or a plain-text tool such as web search ran without error)
    tool_error - the tool returned a handled error (out of range, unsupported currency, ...)
    exception  - the tool raised; the agent turned it into an error message
    """
    tools = spans[spans["span_kind"] == "TOOL"]
    rows = []
    for _, row in tools.iterrows():
        payload, message_status = _tool_payload(row.get("attributes.output.value"))
        if row.get("status_code") == "ERROR" or (message_status == "error" and payload is None):
            label, score = "exception", 0.0
            explanation = str(row.get("status_message") or row.get("attributes.output.value"))[:500]
        elif payload and payload.get("status") == "error":
            err = payload.get("error") or {}
            label, score = "tool_error", 0.0
            explanation = f"{err.get('code')}: {err.get('message')}"
        else:
            label, score, explanation = "success", 1.0, "Tool ran and returned a result"
        rows.append(
            {
                "span_id": row["context.span_id"],
                "trace_id": row["context.trace_id"],
                "tool_name": row.get("attributes.tool.name") or row["name"],
                "label": label,
                "score": score,
                "explanation": explanation,
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- metrics


def binary_metrics(y_true: list[bool], y_pred: list[bool]) -> dict[str, Any]:
    pairs = list(zip(y_true, y_pred, strict=True))
    tp = sum(t and p for t, p in pairs)
    tn = sum((not t) and (not p) for t, p in pairs)
    fp = sum((not t) and p for t, p in pairs)
    fn = sum(t and (not p) for t, p in pairs)
    n = len(pairs)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall
        else (0.0 if precision == 0 or recall == 0 else None)
    )
    return {
        "n": n,
        "accuracy": round((tp + tn) / n, 3) if n else None,
        "precision": round(precision, 3) if precision is not None else None,
        "recall": round(recall, 3) if recall is not None else None,
        "f1": round(f1, 3) if f1 is not None else None,
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    }
