import datetime as dt
import logging
import operator
import os
from typing import Annotated, Literal

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from tools import convert_currency, get_weather_forecast

load_dotenv()
logger = logging.getLogger(__name__)

# Claude Haiku 5.5 is the cheapest current Claude model ($0.10 / $0.50 per 1M input/output
# tokens). Override with ANTHROPIC_MODEL, e.g. claude-sonnet-5-5 for harder reasoning.
DEFAULT_MODEL = "claude-haiku-5-5"

search_tool = DuckDuckGoSearchRun()
# Step 2: two structured tools added next to the starter's web search.
tools: list[BaseTool] = [search_tool, get_weather_forecast, convert_currency]

SYSTEM_PROMPT = """\
You are a helpful travel assistant. Today is {today} ({weekday}).
You help users plan trips: flights, hotels, attractions, weather and budgets.

Tools - pick the most specific one:
- get_weather_forecast: weather for a city on specific dates (only up to 15 days ahead).
- convert_currency: any money conversion. Never quote exchange rates from memory.
- duckduckgo_search: flights, hotels, attractions, events, opening hours and other current info.

Rules:
- Resolve relative dates ("this weekend", "tomorrow") against today's date before calling tools.
- Call several tools when a request needs it (e.g. weather AND budget).
- Base facts on tool results. If a tool returns status "error", briefly explain the limitation
  and offer the best alternative instead of inventing data.
- Be concise: lead with the answer, then short bullet points.
"""


class MessagesState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]


def system_message(today: dt.date | None = None) -> SystemMessage:
    today = today or dt.date.today()
    return SystemMessage(
        content=SYSTEM_PROMPT.format(today=today.isoformat(), weekday=today.strftime("%A"))
    )


def run_tool_calls(tool_calls: list[dict], tools_by_name: dict[str, BaseTool]) -> list[ToolMessage]:
    """Execute the tool calls of one AI message.

    Passing the full ``tool_call`` (not just its args) makes LangChain return a ToolMessage that
    keeps the tool's structured ``artifact``. Failures become error ToolMessages so the LLM can
    recover and the request does not crash.
    """
    messages = []
    for tool_call in tool_calls:
        tool = tools_by_name.get(tool_call["name"])
        if tool is None:
            messages.append(
                ToolMessage(
                    content=f"Error: unknown tool '{tool_call['name']}'.",
                    tool_call_id=tool_call["id"],
                    name=tool_call["name"],
                    status="error",
                )
            )
            continue
        try:
            messages.append(tool.invoke(tool_call))
        except Exception as exc:  # invalid arguments, unexpected tool failure, ...
            logger.warning("tool %s failed: %s", tool_call["name"], exc)
            messages.append(
                ToolMessage(
                    content=f"Error: {type(exc).__name__}: {exc}. Fix the arguments or try another approach.",
                    tool_call_id=tool_call["id"],
                    name=tool_call["name"],
                    status="error",
                )
            )
    return messages


def should_continue(state: MessagesState) -> Literal["tool_node", "__end__"]:
    """Determine whether to continue to tool execution or end."""
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tool_node"
    return END


def default_model() -> ChatAnthropic:
    """Claude via the Anthropic API (reads ANTHROPIC_API_KEY from the environment / .env).

    No ``temperature`` is sent on purpose: current Claude models reject sampling parameters.
    Claude Haiku 5.5 runs adaptive thinking by default, which works with normal tool calling.
    """
    return ChatAnthropic(
        model=os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL),
        max_tokens=4096,
        timeout=120,
        max_retries=2,
    )


def message_text(message) -> str:
    """Final answer text of an AI message.

    Claude returns a list of content blocks (e.g. ``thinking`` + ``text``) rather than a plain
    string; keep only the text blocks.
    """
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "") if isinstance(block, dict) else str(block)
        for block in content
        if not isinstance(block, dict) or block.get("type") == "text"
    )


def build_agent(
    model: BaseChatModel | None = None,
    agent_tools: list[BaseTool] | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Compile the graph.

    ``model`` and ``agent_tools`` can be injected (used by the tests). With a ``checkpointer``
    the graph keeps each conversation's messages under its ``thread_id`` (= session id), so a
    follow-up message sees the earlier turns.
    """
    agent_tools = agent_tools if agent_tools is not None else tools
    tools_by_name = {tool.name: tool for tool in agent_tools}
    model_with_tools = (model or default_model()).bind_tools(agent_tools)

    def llm_call(state: MessagesState) -> dict:
        """Call the LLM with the current messages and available tools."""
        return {"messages": [model_with_tools.invoke([system_message()] + state["messages"])]}

    def tool_node(state: MessagesState) -> dict:
        """Execute tool calls from the last message."""
        return {"messages": run_tool_calls(state["messages"][-1].tool_calls, tools_by_name)}

    graph_builder = StateGraph(MessagesState)

    graph_builder.add_node("llm_call", llm_call)
    graph_builder.add_node("tool_node", tool_node)

    graph_builder.add_edge(START, "llm_call")
    graph_builder.add_conditional_edges("llm_call", should_continue, ["tool_node", END])
    graph_builder.add_edge("tool_node", "llm_call")

    agent = graph_builder.compile(checkpointer=checkpointer)
    return agent
