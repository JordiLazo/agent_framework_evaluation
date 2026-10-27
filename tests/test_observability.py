"""Step 3: tracing wiring - spans for the graph, LLM and tool calls are produced and exported."""

from langchain_core.messages import AIMessage, HumanMessage
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import observability
from tests.test_agent import call, make_agent


def test_tracing_can_be_disabled(monkeypatch):
    monkeypatch.setenv("PHOENIX_TRACING_ENABLED", "false")
    monkeypatch.setattr(observability, "_tracer_provider", None)
    assert observability.setup_tracing() is None


def test_llm_and_tool_spans_are_captured(monkeypatch):
    monkeypatch.setenv("PHOENIX_TRACING_ENABLED", "true")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:9")  # nothing listens
    monkeypatch.setattr(observability, "_tracer_provider", None)
    provider = observability.setup_tracing()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        agent = make_agent(call("lookup_city", {"city": "Rome"}), AIMessage(content="Rome!"))
        agent.invoke({"messages": [HumanMessage(content="Rome?")]})
        spans = exporter.get_finished_spans()
        kinds = {s.name: s.attributes.get("openinference.span.kind") for s in spans}
        assert kinds["lookup_city"] == "TOOL"
        assert "LLM" in kinds.values()
        assert kinds["LangGraph"] == "CHAIN"
        tool_span = next(s for s in spans if s.name == "lookup_city")
        assert "Rome" in tool_span.attributes["input.value"]
    finally:
        from openinference.instrumentation.langchain import LangChainInstrumentor

        LangChainInstrumentor().uninstrument()
        monkeypatch.setattr(observability, "_tracer_provider", None)


def test_turn_span_is_root_agent_span_and_propagates_session(monkeypatch):
    monkeypatch.setenv("PHOENIX_TRACING_ENABLED", "true")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:9")
    monkeypatch.setattr(observability, "_tracer_provider", None)
    provider = observability.setup_tracing()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        agent = make_agent(call("lookup_city", {"city": "Rome"}), AIMessage(content="Rome!"))
        with observability.turn_span("Rome?", "sess-1", {"scenario": "demo"}) as span:
            agent.invoke({"messages": [HumanMessage(content="Rome?")]})
            span.set_output("Rome!")
        spans = {s.name: s for s in exporter.get_finished_spans()}
        root = spans["chat"]
        assert root.parent is None
        assert root.attributes["openinference.span.kind"] == "AGENT"
        assert (root.attributes["input.value"], root.attributes["output.value"]) == ("Rome?", "Rome!")
        assert spans["lookup_city"].attributes["session.id"] == "sess-1"  # propagated to children
        assert "demo" in spans["lookup_city"].attributes["metadata"]
    finally:
        from openinference.instrumentation.langchain import LangChainInstrumentor

        LangChainInstrumentor().uninstrument()
        monkeypatch.setattr(observability, "_tracer_provider", None)
