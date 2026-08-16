"""Runs the full 120-case eval set through the real agent graph."""
import json
import sys

import pandas as pd

from sentinel.batch_runner import run_batch
from sentinel.eval.build_eval_set import case_context_for_row

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "full-eval-001"


def main():
    eval_df = pd.read_parquet("data/processed/eval_set.parquet")
    case_contexts = {row["case_id"]: case_context_for_row(row) for _, row in eval_df.iterrows()}
    case_ids = list(case_contexts.keys())

    print(f"running {len(case_ids)} cases as run_id={RUN_ID}")
    result = run_batch(RUN_ID, case_ids, use_cache=True, checkpoint_every=5, case_contexts=case_contexts)
    print(json.dumps({k: v for k, v in result.items() if k != "token_report"}, indent=2, default=str))
    print("token report:")
    for row in result["token_report"]:
        print(row)


if __name__ == "__main__":
    main()
