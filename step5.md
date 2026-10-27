# Step 5: Evaluation (user frustration)

## What the assessment asks

> Configure evaluation on your traces using Phoenix. You must include:
> **1. User Frustration Evaluation.** Use Phoenix documentation to create a user frustration
> evaluation. Attach evaluation results to spans following the documentation. Filter examples in
> Phoenix and create a dataset of frustrated interactions. Explain your evaluation methodology.

## Summary

- **User-frustration evaluation:** an LLM-as-a-judge built with **Phoenix Evals**
  (`ClassificationEvaluator`, judge = Claude Haiku 5.5). It scores **every user turn** with the
  earlier conversation as context. Labels: `frustrated` / `not_frustrated`, each with an
  explanation.
- **Attached to spans:** the results are logged as **span annotations** (`user_frustration`) on
  each turn's root `chat` span with `log_span_annotations_dataframe`, plus a
  `session_frustration` roll-up per conversation.
- **Filtered in Phoenix → dataset:** the annotations are queried **back from Phoenix**, filtered
  to `label == 'frustrated'`, and turned into the Phoenix dataset **`frustrated-interactions`**
  (5 examples, each linked to its source span). The same filter works in the UI:
  `annotations['user_frustration'].label == 'frustrated'`.
- **Extra signals:**
  - Phoenix's built-in **`UserFrictionEvaluator`** as a second, independent judge.
  - A deterministic **`tool_execution`** CODE check on every TOOL span.
- **Result on the 22 real turns:** the judge flagged **5 frustrated turns** and agreed with all 22
  reference labels (precision 1.0, recall 1.0). The built-in friction judge agreed as well. The
  limits of this result are discussed below.
- **Cost:** 44 judge calls with Claude Haiku 5.5, well under $0.01.

---

## Evaluation methodology

### 1. Unit of evaluation: a user turn, with its conversation

Frustration is a reaction to the assistant's earlier behaviour. "No, I said CHEAP" means
nothing without the previous turn. So:

- each **user turn** (one `chat` span = one trace) is one evaluation example;
- the input is `conversation` (all earlier USER/ASSISTANT turns of the same `session.id`,
  rebuilt from the `chat` spans in time order) plus `user_message` (the latest message);
- the result is attached to **that turn's `chat` span**, so it sits on the trace where the
  frustration happened. A session-level roll-up is added on top.

### 2. The judge (LLM-as-a-judge with Phoenix Evals)

- **API:** `phoenix.evals.ClassificationEvaluator` with
  `LLM(provider="anthropic", model="claude-haiku-5-5")`.
- **Labels:** `{"frustrated": 1.0, "not_frustrated": 0.0}`, `direction="minimize"` (lower is
  better). Every label comes with an explanation.
- **Prompt** (`evals/prompts.py`): adapted from Phoenix's user-frustration and user-friction
  templates, with an explicit rubric:
  - **frustrated** = negative affect ("useless", "ugh"), re-asserting an ignored constraint
    ("I said CHEAP", "second time"), giving up ("forget it"), or complaining that the answer
    was wrong or irrelevant;
  - **not_frustrated** = first messages, neutral follow-ups or refinements ("and 120 pounds?"),
    thanks, calm topic switches ("ok no worries");
  - "judge only what the user **expresses**", and "if ambiguous, choose not_frustrated", which
    favours precision.
- **Why per-turn rather than per-session:** it pinpoints *which* answer caused the frustration
  (the span to debug). The session label is derived from the turn labels.
- **Thinking off for the judge:** Phoenix's Anthropic adapter gets structured output through a
  forced tool call, which can't be combined with extended thinking. Haiku 5.5 thinks by default,
  so the judge sends `thinking={"type": "disabled"}`. A one-label classification doesn't need
  it.

### 3. Second opinion: Phoenix's built-in `UserFrictionEvaluator`

A pre-built Phoenix metric (labels `friction` / `no_friction`) with a different, independently
written rubric (corrections, retries, frustration, challenges). It's cheap, and when the two
judges disagree, that points to an ambiguous or mislabelled example worth reviewing by hand.

### 4. Measuring the judge (meta-evaluation)

An LLM judge is itself a model that can be wrong, so it is measured too. Every scripted turn
carries a reference label (`expected_user_frustration` in the span metadata, from
`evals/scenarios.py`). `evaluate.py` compares each judge with these labels and reports
accuracy, precision, recall, F1 and the confusion matrix.

### 5. Deterministic tool check (`tool_execution`, CODE)

For every TOOL span, a code check reads the tool's structured result:

- `success`: ran and returned a result;
- `tool_error`: a handled error, with its code (e.g. `unsupported_currency`);
- `exception`: the tool raised.

It is logged as an annotation with `annotator_kind="CODE"`, which makes it easy to link a
frustrated turn to the tool failure that caused it.

---

## Changes made

All paths are in `se-interview/`.

| File | Change |
|---|---|
| `evals/prompts.py` | **New.** The user-frustration judge prompt and labels. |
| `evals/evaluate.py` | **New.** The full pipeline: spans → turns → judges (`evaluate_dataframe`) → span annotations (`to_annotation_dataframe` + `log_span_annotations_dataframe`) → CODE tool annotations → session annotations (`log_session_annotations_dataframe`) → judge metrics → read annotations back (`get_span_annotations_dataframe`), filter `frustrated` → `datasets.create_dataset(..., span_id_key="span_id")`. Saves `data/eval_results/<timestamp>/`. |
| `evals/phoenix_data.py` | `build_turns()` (session history per turn), `evaluate_tool_executions()` (CODE check), `binary_metrics()`. |
| `tools/currency.py` | Fix found while debugging the traces: the `unsupported_currency` error now names only the unsupported code (see Debugging insights). |
| `observability.py` | The `chat` span now ends with status `OK` (or `ERROR` on exceptions). |
| `.env.example` | Optional `JUDGE_MODEL` (default `claude-haiku-5-5`). |
| `tests/test_evals.py`, `tests/test_tools.py` | Tests for turn building, run filtering, the CODE evaluator, the metrics and the new currency error. 30 tests total, all offline. |

---

## How to run it

Phoenix and the API are running, and the Step 4 traffic has been sent. From `se-interview/`:

```bash
poetry run python -m evals.evaluate --run-id 20261026-202215-bac6 --dataset-name frustrated-interactions
```

- Without `--run-id`, every turn in the project is evaluated.
- Without `--dataset-name`, the dataset is called `frustrated-interactions-<timestamp>`.
- `--no-log` computes everything without writing to Phoenix.

Real output:

```
Evaluating 22 turns from 13 sessions (project=travel-agent, judge=claude-haiku-5-5) ...

=== Summary ===
{
  "project": "travel-agent",
  "judge_model": "claude-haiku-5-5",
  "turns": 22,
  "sessions": 13,
  "frustrated_turns": 5,
  "friction_turns": 5,
  "judge_errors": 0,
  "user_frustration_vs_reference": {
    "n": 22, "accuracy": 1.0, "precision": 1.0, "recall": 1.0, "f1": 1.0,
    "confusion": {"tp": 5, "fp": 0, "tn": 17, "fn": 0}
  },
  "user_friction_vs_reference": {
    "n": 22, "accuracy": 1.0, "precision": 1.0, "recall": 1.0, "f1": 1.0,
    "confusion": {"tp": 5, "fp": 0, "tn": 17, "fn": 0}
  },
  "tool_execution": {
    "convert_currency":     {"success": 4, "tool_error": 1},
    "duckduckgo_search":    {"success": 11, "tool_error": 0},
    "get_weather_forecast": {"success": 6, "tool_error": 0}
  },
  "dataset": {"created": true, "name": "frustrated-interactions", "examples": 5, "id": "RGF0YXNldDoy"}
}

=== Turns judged frustrated ===
- [frustrated_units-... #1] I literally asked for Fahrenheit. Why do I keep getting Celsius?? Just convert them, it's
    judge: The user explicitly asked for Fahrenheit in the first message. The assistant gave Fahrenheit with Celsius in parentheses, and the user responds with "I literally asked for Fahrenhe...
- [frustrated_far_future-... #1] That's useless. I don't care about your limitations, I just need to know whether to pack a
    judge: The user calls the assistant's answer "useless", expresses annoyance ("I don't care about your limitations"), and re-asserts their actual need ...
- [frustrated_cheap_hotel-... #1] No, I said CHEAP. Under 100 pounds a night. This is the second time I'm asking.
    judge: The user emphasizes a constraint ("CHEAP", "Under 100 pounds a night") that the assistant had not addressed, and explicitly notes "This is the second time I'm asking," ...
- [frustrated_cheap_hotel-... #2] Forget it, you're not helping at all.
    judge: The user says "Forget it, you're not helping at all." This is giving up plus direct complaint that the assistant is unhelpful ...
- [unsupported_currency-... #1] Ugh, seriously? I don't need an official rate, just give me a rough number like I asked.
    judge: The user opens with "Ugh, seriously?" which is clear annoyance and sarcasm directed at the assistant's refusal to give a number ...

Files: data/eval_results/20261026-202416/
```

Files written to `data/eval_results/<timestamp>/`:

- `turn_evals.csv`: one row per turn with the conversation, message, answer, reference label,
  judge label and explanation, and friction label;
- `tool_execution_evals.csv`;
- `summary.json`.

---

## Viewing the results in Phoenix, and building the dataset in the UI

Open http://localhost:6006 → project **travel-agent**.

1. **Annotations on spans:** open any `chat` trace. The **Annotations** panel shows
   `user_frustration` (label, score, explanation) and `user_friction`. TOOL spans show
   `tool_execution`.
2. **Sessions:** the **Sessions** tab shows `session_frustration` per conversation (e.g.
   `frustrated_cheap_hotel`: "2 of 3 user turns judged frustrated").
3. **Filter the frustrated examples:** in the span filter box, type

   ```
   annotations['user_frustration'].label == 'frustrated'
   ```

   This returns **5 spans**. Other useful filters, all checked against the server:

   | Filter | Rows |
   |---|---|
   | `annotations['user_frustration'].label == 'frustrated'` | 5 |
   | `span_kind == 'TOOL' and annotations['tool_execution'].label == 'tool_error'` | 1 |
   | `metadata['run_id'] == '20261026-202215-bac6' and span_kind == 'AGENT'` | 22 |

4. **Create the dataset by hand (UI way):** select the filtered spans → **Add to Dataset** →
   new dataset. The script already did this through the API: the **Datasets** tab shows
   **`frustrated-interactions`** with 5 examples. Each example has:
   - **input:** `conversation`, `user_message`;
   - **output:** `assistant_response`;
   - **metadata:** `session_id`, `turn_index`, `scenario`, `judge_explanation`;
   - a link back to its source span.

From the terminal with the PX CLI:

```bash
px dataset list --endpoint http://localhost:6006
px span list --endpoint http://localhost:6006 --project travel-agent --name chat --include-annotations --format json -n 50
```

---

## Results and interpretation

| Judge | Accuracy | Precision | Recall | F1 | TP / FP / TN / FN |
|---|---|---|---|---|---|
| `user_frustration` (custom rubric, Claude Haiku 5.5) | 1.00 | 1.00 | 1.00 | 1.00 | 5 / 0 / 17 / 0 |
| `user_friction` (Phoenix built-in, Claude Haiku 5.5) | 1.00 | 1.00 | 1.00 | 1.00 | 5 / 0 / 17 / 0 |

**Read these numbers carefully.** 22 scripted turns is a small benchmark, and the frustrated
turns are deliberately explicit. The result shows the pipeline works and the judge handles
clear cases, including the tricky negatives:

- a calm topic switch ("Ok no worries. Then tell me what to do in Kyoto") → not frustrated;
- a neutral refinement ("And what about 120 pounds?") → not frustrated;
- thanks → not frustrated.

It does **not** prove the judge holds up on subtle, sarcastic or mixed messages. The next steps
would be:

- add harder, ambiguous examples;
- label a sample of real traffic by hand (Phoenix human annotations);
- track agreement between the two judges.

---

## Debugging insights (what the evaluation revealed)

The frustrated turns point to concrete causes, each visible in the linked trace:

| Frustrated turn | Root cause found in the trace | Action |
|---|---|---|
| `frustrated_cheap_hotel` #1, #2 ("second time I'm asking", "forget it") | The TOOL spans show `duckduckgo_search` returning booking-site ads with no prices. Claude refused to invent prices (good grounding), but couldn't satisfy a budget constraint. | Web search is the weak tool for hotels and flights. A structured hotel/flight API with price filters would fix the root cause. This is the clearest product gap. |
| `unsupported_currency` #1 ("Ugh, seriously? ... a rough number") | `tool_execution = tool_error` (`unsupported_currency`) on `convert_currency`. The error text said "'USD' or 'ARS' is not covered", and Claude told the user that **US dollars** weren't supported, which is wrong. | **Fixed** in `tools/currency.py`: the error now names only the missing code. After rerunning, Claude explains correctly, and on the follow-up it finds an approximate rate via web search (~1,500 ARS/USD). |
| `frustrated_far_future` #1 ("That's useless ... umbrella") | `get_weather_forecast` can't forecast 2027 (it covers 16 days). The first answer explained the limitation rather than giving typical seasonal weather. On the follow-up, Claude gave a useful climate-based answer. | The system prompt could say: "for dates outside the forecast range, give typical seasonal weather straight away". |
| `frustrated_units` #1 ("I literally asked for Fahrenheit") | The trace shows Claude **did** answer in °F, with °C in brackets. The user's complaint is scripted, so the judge correctly flags the frustration the user *expresses* even though the agent was mostly right. | A known limitation of scripted traffic. It also shows why "frustrated" ≠ "agent was wrong", and why the dataset should be reviewed by hand. |

**How to use the `frustrated-interactions` dataset next:** it is a regression set. After a
change (prompt, model, tools), run the agent on its `conversation` + `user_message` inputs as a
Phoenix **experiment** and check that the answers improve. For example, give a rough
budget-aware answer instead of "I couldn't find prices".
