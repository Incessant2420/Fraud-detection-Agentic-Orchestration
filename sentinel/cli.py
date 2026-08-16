"""python -m sentinel.cli investigate --case-id <id>

Acceptance criterion #1: returns a validated CaseReport in < 90s.
"""
import argparse
import json
import sys
import time
import uuid

import pandas as pd

from sentinel.agent.graph import run_case
from sentinel.budget import TokenBudgetTracker
from sentinel.cache import ResponseCache
from sentinel.llm import LLMRouter

CASES_PATHS = {
    "BANK": "data/processed/cases_bank.parquet",
    "COMMERCE": "data/processed/cases_commerce.parquet",
}


def load_case_context(case_id: str) -> dict:
    for domain, path in CASES_PATHS.items():
        df = pd.read_parquet(path)
        row = df[df["case_id"] == case_id]
        if len(row):
            r = row.iloc[0].to_dict()
            return {
                "case_id": r["case_id"], "domain": r["domain"], "user_id": r["user_id"],
                "event_id": r["event_id"], "baseline_risk_score": r["risk_score"],
                "shap_drivers": json.loads(r["shap_drivers"]),
                "flagged_at": r["timestamp"],
            }
    raise ValueError(f"case_id {case_id} not found in {list(CASES_PATHS.values())}")


def investigate(case_id: str, use_cache: bool = True) -> dict:
    case_context = load_case_context(case_id)
    run_id = f"cli-{uuid.uuid4().hex[:8]}"
    cache = ResponseCache("data/response_cache.sqlite")
    budget = TokenBudgetTracker("data/token_budget.sqlite")
    llm = LLMRouter(run_id=run_id, cache=cache, budget=budget, use_cache=use_cache)

    start = time.perf_counter()
    result = run_case(case_context, llm)
    elapsed = time.perf_counter() - start

    result["elapsed_seconds"] = round(elapsed, 2)
    result["run_id"] = run_id
    cache.close()
    budget.close()
    return result


def main():
    parser = argparse.ArgumentParser(prog="sentinel.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("investigate")
    inv.add_argument("--case-id", required=True)
    inv.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    if args.command == "investigate":
        result = investigate(args.case_id, use_cache=not args.no_cache)
        print(json.dumps(result, indent=2, default=str))
        if result["elapsed_seconds"] >= 90:
            print(f"WARNING: exceeded 90s budget ({result['elapsed_seconds']}s)", file=sys.stderr)


if __name__ == "__main__":
    main()
