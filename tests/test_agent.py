"""Graph wiring tests with a scripted fake chat model (no network, no Anthropic API)."""

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver

import api
from agent import DEFAULT_MODEL, build_agent, default_model, message_text, system_message, tools


class FakeToolModel(GenericFakeChatModel):
    """Replays scripted AI messages; ignores tool binding."""

    def bind_tools(self, tools, **kwargs):
        return self


@tool
def lookup_city(city: str) -> str:
    """Return a canned fact about a city."""
    return f'{{"status": "ok", "city": "{city}"}}'


@tool
def broken_tool(x: int) -> str:
    """Always fails."""
    raise RuntimeError("boom")


def make_agent(*scripted, checkpointer=None):
    return build_agent(
        model=FakeToolModel(messages=iter(scripted)),
        agent_tools=[lookup_city, broken_tool],
        checkpointer=checkpointer,
    )


def call(name, args, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def test_new_tools_are_registered_with_the_agent():
    assert {t.name for t in tools} == {"duckduckgo_search", "get_weather_forecast", "convert_currency"}


def test_system_prompt_contains_todays_date():
    import datetime as dt

    assert "2026-10-26 (Monday)" in system_message(dt.date(2026, 10, 26)).content


def test_tool_call_is_executed_and_fed_back_to_the_llm():
    agent = make_agent(call("lookup_city", {"city": "Porto"}), AIMessage(content="Porto it is."))
    result = agent.invoke({"messages": [HumanMessage(content="Tell me about Porto")]})

    tool_message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert "Porto" in tool_message.content
    assert result["messages"][-1].content == "Porto it is."


def test_tool_exception_becomes_error_message_not_a_crash():
    agent = make_agent(call("broken_tool", {"x": 1}), AIMessage(content="Sorry, that failed."))
    result = agent.invoke({"messages": [HumanMessage(content="break it")]})

    tool_message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool_message.status == "error" and "boom" in tool_message.content
    assert result["messages"][-1].content == "Sorry, that failed."


def test_unknown_tool_name_is_reported_to_the_llm():
    agent = make_agent(call("does_not_exist", {}), AIMessage(content="ok"))
    result = agent.invoke({"messages": [HumanMessage(content="?")]})
    tool_message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert "unknown tool" in tool_message.content


def test_chat_endpoint_reports_tool_calls(monkeypatch):
    fake = make_agent(
        call("lookup_city", {"city": "Rome"}), AIMessage(content="Rome!"), checkpointer=MemorySaver()
    )
    monkeypatch.setattr(api, "agent", fake)

    body = TestClient(api.app).post("/chat", json={"message": "Rome?"}).json()

    assert body["response"] == "Rome!"
    assert body["tool_calls"] == [{"name": "lookup_city", "args": {"city": "Rome"}, "status": "success"}]


def test_default_model_is_the_cheapest_claude_and_sends_no_temperature(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    model = default_model()
    assert DEFAULT_MODEL == "claude-haiku-5-5"
    assert model.model == "claude-haiku-5-5"
    payload = model._get_request_payload([HumanMessage(content="hi")])
    assert "temperature" not in payload


def test_message_text_keeps_only_text_blocks_from_claude():
    claude_reply = AIMessage(
        content=[
            {"type": "thinking", "thinking": "", "signature": "abc"},
            {"type": "text", "text": "Lisbon will be sunny."},
        ]
    )
    assert message_text(claude_reply) == "Lisbon will be sunny."
    assert message_text(AIMessage(content="plain")) == "plain"


def test_chat_endpoint_returns_text_for_claude_content_blocks(monkeypatch):
    reply = AIMessage(content=[{"type": "thinking", "thinking": "", "signature": "s"},
                               {"type": "text", "text": "Hi!"}])
    monkeypatch.setattr(api, "agent", make_agent(reply, checkpointer=MemorySaver()))
    body = TestClient(api.app).post("/chat", json={"message": "hello"}).json()
    assert body["response"] == "Hi!"


def test_session_id_keeps_conversation_memory_and_reports_only_new_tool_calls(monkeypatch):
    fake = make_agent(
        call("lookup_city", {"city": "Rome"}),
        AIMessage(content="Rome!"),
        AIMessage(content="You asked about Rome."),
        checkpointer=MemorySaver(),
    )
    monkeypatch.setattr(api, "agent", fake)
    client = TestClient(api.app)

    first = client.post("/chat", json={"message": "Rome?"}).json()
    second = client.post(
        "/chat", json={"message": "What did I ask?", "session_id": first["session_id"]}
    ).json()

    assert second["session_id"] == first["session_id"]
    assert second["tool_calls"] == []  # tool calls from turn 1 are not repeated
    history = fake.get_state({"configurable": {"thread_id": first["session_id"]}}).values["messages"]
    assert [m.content for m in history if isinstance(m, HumanMessage)] == ["Rome?", "What did I ask?"]


def test_new_session_when_no_session_id(monkeypatch):
    monkeypatch.setattr(
        api, "agent", make_agent(AIMessage(content="a"), AIMessage(content="b"), checkpointer=MemorySaver())
    )
    client = TestClient(api.app)
    ids = {client.post("/chat", json={"message": "hi"}).json()["session_id"] for _ in range(2)}
    assert len(ids) == 2
