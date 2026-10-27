"""Step 3: Arize Phoenix tracing via OpenTelemetry + OpenInference.

``setup_tracing()`` does two things:

1. ``phoenix.otel.register`` builds an OpenTelemetry ``TracerProvider`` whose exporter sends
   spans (OTLP over HTTP) to the Phoenix collector, tagged with the Phoenix project name.
2. ``LangChainInstrumentor`` hooks LangChain/LangGraph callbacks and turns every graph run,
   node, LLM call and tool call into OpenInference spans:
     * LLM spans: input/output messages, tool schemas, tool calls, token counts, model name
     * TOOL spans: tool name, arguments, and the structured result
     * CHAIN spans: the LangGraph run and each node (llm_call, tool_node)

It must run BEFORE the agent is built and used, and it is idempotent.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

_tracer_provider = None


def tracing_enabled() -> bool:
    return os.getenv("PHOENIX_TRACING_ENABLED", "true").strip().lower() not in {"0", "false", "no"}


def setup_tracing():
    """Register Phoenix as the trace destination and instrument LangChain (once per process)."""
    global _tracer_provider
    if _tracer_provider is not None or not tracing_enabled():
        return _tracer_provider

    from openinference.instrumentation.langchain import LangChainInstrumentor
    from phoenix.otel import register

    base_url = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006").rstrip("/")
    endpoint = base_url if base_url.endswith("/v1/traces") else f"{base_url}/v1/traces"
    project = os.getenv("PHOENIX_PROJECT_NAME", "travel-agent")

    _tracer_provider = register(
        project_name=project,
        endpoint=endpoint,
        batch=True,  # export in a background thread: never slow down the request
        auto_instrument=False,  # instrument explicitly below (no double LLM spans)
        verbose=False,
    )
    LangChainInstrumentor().instrument(tracer_provider=_tracer_provider)
    logger.info("Phoenix tracing enabled: project=%s endpoint=%s", project, endpoint)
    return _tracer_provider


def shutdown_tracing() -> None:
    """Flush buffered spans (call on shutdown so the last requests are not lost)."""
    if _tracer_provider is not None:
        _tracer_provider.force_flush()


# --------------------------------------------------------------------------- Step 4: turn spans

ROOT_SPAN_NAME = "chat"


@contextmanager
def turn_span(user_message: str, session_id: str, metadata: dict[str, Any] | None = None):
    """One AGENT span per user turn, wrapping the whole LangGraph run.

    * input.value / output.value are the plain user message and final answer, which gives
      evaluators and datasets a clean "conversation turn" unit instead of LangGraph's
      serialized state.
    * ``using_attributes`` propagates ``session.id`` and ``metadata`` to EVERY span created
      inside (LLM, TOOL, CHAIN), which powers Phoenix's Sessions view and metadata filters.

    Yields the span (call ``span.set_output(...)``), or ``None`` when tracing is disabled.
    """
    from openinference.instrumentation import using_attributes

    with using_attributes(session_id=session_id, metadata=metadata or {}):
        if _tracer_provider is None:
            yield None
            return
        from opentelemetry.trace import Status, StatusCode

        tracer = _tracer_provider.get_tracer("travel_agent")
        with tracer.start_as_current_span(ROOT_SPAN_NAME, openinference_span_kind="agent") as span:
            span.set_input(user_message)
            span.set_attribute("session.id", session_id)
            yield span
            span.set_status(Status(StatusCode.OK))  # an exception skips this and records ERROR


def current_trace_id(span) -> str | None:
    if span is None:
        return None
    from opentelemetry.trace import format_trace_id

    return format_trace_id(span.get_span_context().trace_id)
