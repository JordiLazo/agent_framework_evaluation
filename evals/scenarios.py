"""Test conversations for Step 4: 13 sessions / 22 user turns (the assessment requires >= 10).

They cover every tool, tool errors, multi-tool requests, multi-turn follow-ups, out-of-scope
requests and, on purpose, users who get frustrated.

Each user turn carries a reference label ``expected_frustrated``. It describes what the
scripted USER expresses, not how well the agent did. Step 5 uses these labels to measure the
LLM judge (precision/recall). The frustrated follow-ups are scripted up front, so a few may
react to a problem the agent did not actually have in that run; that is fine for a judge
benchmark, because the judge classifies what the user expresses.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Turn:
    message: str
    expected_frustrated: bool = False


@dataclass(frozen=True)
class Scenario:
    id: str
    description: str
    turns: list[Turn]
    tags: list[str] = field(default_factory=list)


SCENARIOS: list[Scenario] = [
    Scenario(
        "weather_weekend",
        "Simple weather lookup with a relative date",
        [Turn("What's the weather going to be like in Lisbon this weekend?")],
        ["weather"],
    ),
    Scenario(
        "currency_simple",
        "Plain currency conversion",
        [Turn("How much is 250 US dollars in Japanese yen?")],
        ["currency"],
    ),
    Scenario(
        "attractions_porto",
        "Attractions via web search",
        [Turn("What are the top 5 attractions in Porto for a first-time visitor?")],
        ["search"],
    ),
    Scenario(
        "flights_then_weather",
        "Flight search, then a neutral follow-up that needs a different tool",
        [
            Turn("Find me flights from Madrid to Rome for next Friday."),
            Turn("Thanks! And what will the weather be like in Rome that day?"),
        ],
        ["search", "weather", "multi-turn"],
    ),
    Scenario(
        "tokyo_multi_tool",
        "One request that needs weather + currency",
        [
            Turn(
                "I'm flying to Tokyo next week with a budget of 1500 EUR. "
                "What's the weather going to be like and how much is my budget in yen?"
            )
        ],
        ["weather", "currency", "multi-tool"],
    ),
    Scenario(
        "hotels_barcelona",
        "Hotel recommendations via web search",
        [Turn("Recommend a few mid-range hotels near the Sagrada Familia in Barcelona.")],
        ["search"],
    ),
    Scenario(
        "frustrated_units",
        "User re-asserts a unit constraint with annoyance",
        [
            Turn(
                "What's the forecast for New York tomorrow? "
                "Please give me the temperatures in Fahrenheit."
            ),
            Turn(
                "I literally asked for Fahrenheit. Why do I keep getting Celsius?? "
                "Just convert them, it's not that hard.",
                expected_frustrated=True,
            ),
        ],
        ["weather", "frustration"],
    ),
    Scenario(
        "frustrated_far_future",
        "Forecast beyond the 16-day horizon -> tool error -> annoyed user",
        [
            Turn("What will the weather be in Paris on March 15th 2027?"),
            Turn(
                "That's useless. I don't care about your limitations, I just need to know "
                "whether to pack an umbrella for Paris in mid-March!",
                expected_frustrated=True,
            ),
        ],
        ["weather", "tool-error", "frustration"],
    ),
    Scenario(
        "frustrated_cheap_hotel",
        "Escalating frustration over an ignored budget constraint",
        [
            Turn("Find me a hotel in London for next weekend."),
            Turn(
                "No, I said CHEAP. Under 100 pounds a night. This is the second time I'm asking.",
                expected_frustrated=True,
            ),
            Turn("Forget it, you're not helping at all.", expected_frustrated=True),
        ],
        ["search", "frustration", "multi-turn"],
    ),
    Scenario(
        "unsupported_currency",
        "Currency not covered by ECB rates -> tool error -> impatient retry",
        [
            Turn("How much is 100 US dollars in Argentine pesos?"),
            Turn(
                "Ugh, seriously? I don't need an official rate, just give me a rough number "
                "like I asked.",
                expected_frustrated=True,
            ),
        ],
        ["currency", "tool-error", "frustration"],
    ),
    Scenario(
        "paris_then_thanks",
        "Weather lookup, then a satisfied follow-up",
        [
            Turn("What's the weather in Paris next Tuesday?"),
            Turn("Perfect, that's very helpful, thank you!"),
        ],
        ["weather", "multi-turn"],
    ),
    Scenario(
        "off_topic_then_kyoto",
        "Out-of-scope request, then a calm topic switch (NOT frustration)",
        [
            Turn("Can you help me write a Python script to sort a list?"),
            Turn("Ok no worries. Then tell me what to do in Kyoto in autumn."),
        ],
        ["out-of-scope", "search", "multi-turn"],
    ),
    Scenario(
        "currency_refinement",
        "A neutral refinement follow-up (NOT frustration)",
        [
            Turn("Convert 80 British pounds to euros."),
            Turn("And what about 120 pounds?"),
        ],
        ["currency", "multi-turn"],
    ),
]
