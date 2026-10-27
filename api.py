import uuid
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

from agent import build_agent, message_text
from observability import current_trace_id, setup_tracing, shutdown_tracing, turn_span

load_dotenv()

# Step 3: tracing must be configured before the agent is built and invoked.
setup_tracing()
# Step 4: in-memory checkpointer = multi-turn memory per session_id (lost on restart).
agent = build_agent(checkpointer=MemorySaver())

# Each llm_call -> tool_node round trip uses 2 graph steps; this stops runaway tool loops.
RECURSION_LIMIT = 12


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    shutdown_tracing()  # flush buffered spans so the last requests reach Phoenix


app = FastAPI(
    title="LangGraph Agent API",
    description="A LangGraph travel agent (Claude) with web search, weather forecast and "
    "currency tools, traced with Arize Phoenix",
    version="0.4.0",
    lifespan=lifespan,
)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = Field(
        default=None,
        description="Conversation id. Reuse the session_id from a previous response to continue "
        "that conversation; omit it to start a new one.",
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional key/values attached to every span of this turn"
    )


class ToolCallInfo(BaseModel):
    name: str
    args: dict[str, Any]
    status: str | None = Field(
        default=None, description="'ok' / 'error' from the tool's structured result, if any"
    )


class ChatResponse(BaseModel):
    response: str
    session_id: str
    trace_id: str | None = Field(default=None, description="Phoenix trace id of this turn")
    tool_calls: list[ToolCallInfo] = Field(
        default_factory=list, description="Tools the agent invoked to produce the answer"
    )


def summarize_tool_calls(messages: list) -> list[ToolCallInfo]:
    """Pair each tool call the model made with the status of its result."""
    statuses = {}
    for message in messages:
        if isinstance(message, ToolMessage):
            artifact = message.artifact if isinstance(message.artifact, dict) else {}
            statuses[message.tool_call_id] = artifact.get("status") or message.status
    return [
        ToolCallInfo(name=call["name"], args=call["args"], status=statuses.get(call["id"]))
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    ]


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """Send a message to the agent and get a response (one call = one turn = one trace)."""
    session_id = request.session_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": RECURSION_LIMIT}
    with turn_span(request.message, session_id, request.metadata) as span:
        history = agent.get_state(config).values.get("messages", [])
        result = agent.invoke({"messages": [HumanMessage(content=request.message)]}, config)
        new_messages = result["messages"][len(history) :]  # only this turn's messages
        answer = message_text(result["messages"][-1])
        if span is not None:
            span.set_output(answer)
    return ChatResponse(
        response=answer,
        session_id=session_id,
        trace_id=current_trace_id(span),
        tool_calls=summarize_tool_calls(new_messages),
    )


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}
