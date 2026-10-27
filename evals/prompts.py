"""Step 5: the user-frustration judge prompt.

Adapted from Phoenix's user-frustration / user-friction templates and specialised for a travel
assistant. It is evaluated PER USER TURN, with the earlier conversation as context, so the judge
can tell "re-asserting an ignored constraint" from "a new question".
"""

USER_FRUSTRATION_CHOICES = {"frustrated": 1.0, "not_frustrated": 0.0}

USER_FRUSTRATION_PROMPT = """\
You are an expert in conversational UX reviewing a conversation between a USER and an AI
TRAVEL ASSISTANT. Decide whether the LATEST USER MESSAGE shows that the user is frustrated
with the assistant.

FRUSTRATED - the latest message contains at least one of these signals, directed at the
assistant's previous behaviour:
- Negative affect: annoyance, impatience, anger, sarcasm or disappointment
  (e.g. "useless", "seriously?", "ugh", "you're not helping").
- Re-asserting a request or constraint the assistant already ignored or got wrong, especially
  with emphasis (capitals, "I already said", "again", "second time", "I literally asked").
- Giving up: "forget it", "never mind, you can't do this".
- Complaining that the answer was wrong, irrelevant or did not address the request.

NOT_FRUSTRATED:
- The first message of a conversation (there is no assistant behaviour to react to yet),
  even if it is urgent or demanding.
- Neutral follow-ups, refinements, new questions or topic switches
  (e.g. "and what about 120 pounds?").
- Thanks, acceptance, small talk, or calmly accepting a limitation ("ok no worries").
- Calm clarification questions about the previous answer.

Judge only what the user EXPRESSES, not whether the assistant was actually wrong.
When the evidence is ambiguous, choose not_frustrated.

<conversation_before_latest_user_message>
{conversation}
</conversation_before_latest_user_message>

<latest_user_message>
{user_message}
</latest_user_message>

Explain your reasoning briefly, then answer with exactly one label: frustrated or not_frustrated.
"""
