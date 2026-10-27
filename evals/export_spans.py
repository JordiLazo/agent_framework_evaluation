"""Step 4: export the project's spans from Phoenix to disk (JSONL + CSV).

    poetry run python -m evals.export_spans                    # every span of the project
    poetry run python -m evals.export_spans --run-id <run_id>  # only one traffic run

Same thing with the Phoenix CLI:
    px span list data/exports/spans_px.json --endpoint http://localhost:6006 \
        --project travel-agent --format json -n 5000
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from dotenv import load_dotenv

from evals.phoenix_data import fetch_spans, filter_run, phoenix_client, project_name

EXPORT_DIR = Path("data/exports")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=None)
    parser.add_argument("--run-id", default=None, help="only export traces from this run")
    parser.add_argument("--limit", type=int, default=20_000)
    args = parser.parse_args(argv)
    load_dotenv()

    project = args.project or project_name()
    spans = fetch_spans(phoenix_client(), project, limit=args.limit)
    if args.run_id and not spans.empty:
        spans = filter_run(spans, args.run_id)
    if spans.empty:
        print(f"No spans found in project '{project}'. Did you run evals.run_queries?", file=sys.stderr)
        return 1

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"spans_{project}_{dt.datetime.now():%Y%m%d-%H%M%S}"
    jsonl_path, csv_path = EXPORT_DIR / f"{stem}.jsonl", EXPORT_DIR / f"{stem}.csv"
    spans.to_json(jsonl_path, orient="records", lines=True, date_format="iso", default_handler=str)
    spans.to_csv(csv_path, index=False)

    roots = spans[spans["parent_id"].isna()]
    print(f"Project '{project}': exported {len(spans)} spans from {roots['context.trace_id'].nunique()} traces")
    print(spans["span_kind"].value_counts().rename("spans per kind").to_string())
    print(f"\n-> {jsonl_path}\n-> {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
