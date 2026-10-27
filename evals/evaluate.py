"""Step 5: user-frustration evaluation with Phoenix Evals, written back to Phoenix.

Pipeline
  1. Pull the project's spans from Phoenix and build one row per user turn (root ``chat`` span),
     with the earlier conversation of the same session as context.
  2. Run the evaluators:
       user_frustration - LLM-as-a-judge (Claude, custom rubric in evals/prompts.py)  -> chat span
       user_friction    - Phoenix's built-in UserFrictionEvaluator (second opinion)   -> chat span
       tool_execution   - deterministic CODE check of every tool call                 -> TOOL span
  3. Log the results as span annotations, plus a session_frustration roll-up per session.
  4. Compare the judges with the scenario reference labels (accuracy / precision / recall / F1).
  5. Query the user_frustration annotations BACK from Phoenix, keep label == "frustrated" and
     create a Phoenix dataset of frustrated interactions, linked to the source spans.

    poetry run python -m evals.evaluate                    # every turn in the project
    poetry run python -m evals.evaluate --run-id <run_id>  # only one traffic run
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from evals.phoenix_data import (
    binary_metrics,
    build_turns,
    evaluate_tool_executions,
    fetch_spans,
    filter_run,
    phoenix_client,
    project_name,
)
from evals.prompts import USER_FRUSTRATION_CHOICES, USER_FRUSTRATION_PROMPT

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
RESULTS_DIR = Path("data/eval_results")
DEFAULT_JUDGE_MODEL = "claude-haiku-5-5"

# Phoenix's Anthropic adapter gets structured labels through a *forced* tool call, which can't be
# combined with extended thinking. Claude Haiku 5.5 thinks adaptively by default, so thinking is
# switched off for the judge (allowed at its default effort). A one-label classification
# doesn't need it.
JUDGE_INVOCATION_KWARGS: dict[str, Any] = {"thinking": {"type": "disabled"}}


def make_evaluators(judge_model: str):
    from phoenix.evals import LLM, ClassificationEvaluator
    from phoenix.evals.metrics.user_friction import UserFrictionEvaluator

    llm = LLM(provider="anthropic", model=judge_model)
    frustration = ClassificationEvaluator(
        name="user_frustration",
        llm=llm,
        prompt_template=USER_FRUSTRATION_PROMPT,
        choices=USER_FRUSTRATION_CHOICES,
        direction="minimize",
        **JUDGE_INVOCATION_KWARGS,
    )
    friction = UserFrictionEvaluator(llm=llm, **JUDGE_INVOCATION_KWARGS)
    return [frustration, friction]


def score_field(results: pd.DataFrame, score_name: str, field: str) -> pd.Series:
    def get(value: Any) -> Any:
        if isinstance(value, str):
            value = json.loads(value) if value.strip() else None
        return (value or {}).get(field)

    return results[f"{score_name}_score"].map(get)


def to_annotations(results: pd.DataFrame, score_name: str) -> pd.DataFrame:
    """Evaluator output -> Phoenix span-annotation dataframe (index = span_id)."""
    from phoenix.evals.utils import to_annotation_dataframe

    ann = to_annotation_dataframe(
        dataframe=results[["span_id", f"{score_name}_score"]], score_names=[score_name]
    )
    return ann.dropna(subset=["label"]).set_index("span_id")


def create_frustration_dataset(client, project: str, turns: pd.DataFrame, name: str) -> dict:
    """Filter in Phoenix (annotations stored server-side) and build a dataset from the matches."""
    ann = client.spans.get_span_annotations_dataframe(
        span_ids=list(turns["span_id"]),
        project_identifier=project,
        include_annotation_names=["user_frustration"],
        limit=10_000,
        timeout=60,
    )
    if ann is None or ann.empty:
        return {"created": False, "examples": 0, "reason": "no user_frustration annotations"}
    ann = ann.reset_index()
    frustrated = ann[ann["result.label"] == "frustrated"][["span_id", "result.explanation"]]
    frustrated = frustrated.drop_duplicates("span_id").rename(
        columns={"result.explanation": "judge_explanation"}
    )
    if frustrated.empty:
        return {"created": False, "examples": 0, "reason": "no frustrated turns"}

    examples = turns.merge(frustrated, on="span_id")[
        ["span_id", "session_id", "turn_index", "scenario", "conversation", "user_message",
         "assistant_response", "judge_explanation"]
    ].astype({"turn_index": int})
    dataset = client.datasets.create_dataset(
        name=name,
        dataframe=examples,
        input_keys=["conversation", "user_message"],
        output_keys=["assistant_response"],
        metadata_keys=["session_id", "turn_index", "scenario", "judge_explanation"],
        span_id_key="span_id",  # links each example back to its trace in Phoenix
        dataset_description=f"User turns labelled 'frustrated' by the user_frustration judge "
        f"in project '{project}'.",
        timeout=60,
    )
    return {"created": True, "name": name, "examples": len(examples), "id": getattr(dataset, "id", None)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=None)
    parser.add_argument("--run-id", default=None, help="only evaluate turns from this run")
    parser.add_argument("--judge-model", default=None, help=f"default: $JUDGE_MODEL or {DEFAULT_JUDGE_MODEL}")
    parser.add_argument("--dataset-name", default=None)
    parser.add_argument("--no-log", action="store_true", help="don't write anything to Phoenix")
    args = parser.parse_args(argv)
    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is required for the LLM judge", file=sys.stderr)
        return 2

    from phoenix.evals import evaluate_dataframe

    project = args.project or project_name()
    judge_model = args.judge_model or os.getenv("JUDGE_MODEL", DEFAULT_JUDGE_MODEL)
    client = phoenix_client()

    # 1. spans -> turns
    spans = fetch_spans(client, project)
    if args.run_id and not spans.empty:
        spans = filter_run(spans, args.run_id)
    turns = build_turns(spans)
    if turns.empty:
        print(f"No 'chat' turns found in project '{project}'", file=sys.stderr)
        return 1
    print(f"Evaluating {len(turns)} turns from {turns['session_id'].nunique()} sessions "
          f"(project={project}, judge={judge_model}) ...")

    # 2. evaluators
    results = evaluate_dataframe(
        dataframe=turns, evaluators=make_evaluators(judge_model), exit_on_error=False, max_retries=3
    )
    turns["frustration_label"] = score_field(results, "user_frustration", "label")
    turns["frustration_explanation"] = score_field(results, "user_frustration", "explanation")
    turns["friction_label"] = score_field(results, "user_friction", "label")
    tool_exec = evaluate_tool_executions(spans)

    # 3. write the results back to Phoenix
    if not args.no_log:
        for name in ("user_frustration", "user_friction"):
            client.spans.log_span_annotations_dataframe(dataframe=to_annotations(results, name), sync=True)
        if not tool_exec.empty:
            client.spans.log_span_annotations_dataframe(
                dataframe=tool_exec.set_index("span_id")[["label", "score", "explanation"]],
                annotation_name="tool_execution",
                annotator_kind="CODE",
                sync=True,
            )
        per_session = (
            turns.assign(frustrated=turns["frustration_label"].eq("frustrated"))
            .groupby("session_id")["frustrated"]
            .agg(["sum", "size"])
            .reset_index()
        )
        client.sessions.log_session_annotations_dataframe(
            dataframe=pd.DataFrame(
                {
                    "session_id": per_session["session_id"],
                    "name": "session_frustration",
                    "label": per_session["sum"].gt(0).map({True: "frustrated", False: "not_frustrated"}),
                    "score": (per_session["sum"] / per_session["size"]).round(3),
                    "explanation": [
                        f"{int(s)} of {int(n)} user turns judged frustrated"
                        for s, n in zip(per_session["sum"], per_session["size"], strict=True)
                    ],
                }
            ),
            annotator_kind="CODE",
            sync=True,
        )

    # 4. how good is the judge? (reference labels come from evals/scenarios.py)
    summary: dict[str, Any] = {
        "project": project,
        "judge_model": judge_model,
        "turns": len(turns),
        "sessions": int(turns["session_id"].nunique()),
        "frustrated_turns": int(turns["frustration_label"].eq("frustrated").sum()),
        "friction_turns": int(turns["friction_label"].eq("friction").sum()),
        "judge_errors": int(turns["frustration_label"].isna().sum()),
    }
    labelled = turns.dropna(subset=["expected_user_frustration", "frustration_label"])
    if not labelled.empty:
        truth = labelled["expected_user_frustration"].eq("frustrated").tolist()
        summary["user_frustration_vs_reference"] = binary_metrics(
            truth, labelled["frustration_label"].eq("frustrated").tolist()
        )
        summary["user_friction_vs_reference"] = binary_metrics(
            truth, labelled["friction_label"].eq("friction").tolist()
        )
    if not tool_exec.empty:
        summary["tool_execution"] = (
            tool_exec.groupby(["tool_name", "label"]).size().unstack(fill_value=0).to_dict(orient="index")
        )

    # 5. dataset of frustrated interactions, filtered from the annotations stored in Phoenix
    if not args.no_log:
        name = args.dataset_name or f"frustrated-interactions-{dt.datetime.now():%Y%m%d-%H%M%S}"
        summary["dataset"] = create_frustration_dataset(client, project, turns, name)

    out_dir = RESULTS_DIR / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    turns.to_csv(out_dir / "turn_evals.csv", index=False)
    tool_exec.to_csv(out_dir / "tool_execution_evals.csv", index=False)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    print("\n=== Summary ===")
    print(json.dumps(summary, indent=2, default=str))
    print("\n=== Turns judged frustrated ===")
    for _, row in turns[turns["frustration_label"] == "frustrated"].iterrows():
        print(f"- [{row['session_id']} #{row['turn_index']}] {row['user_message'][:90]}")
        print(f"    judge: {str(row['frustration_explanation'])[:180]}")
    print(f"\nFiles: {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
