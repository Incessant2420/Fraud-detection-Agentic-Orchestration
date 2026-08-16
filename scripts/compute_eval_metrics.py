"""Computes every metric in spec section 10 from a completed (or
in-progress) eval run's results.jsonl + the eval_set.parquet, and writes a
single results JSON."""
import json
import sys

import pandas as pd

from sentinel.budget import TokenBudgetTracker
from sentinel.eval import metrics as M

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "full-eval-001"
RESULTS_PATH = f"data/eval_runs/{RUN_ID}.jsonl"


def main():
    eval_df = pd.read_parquet("data/processed/eval_set.parquet")
    eval_lookup = eval_df.set_index("case_id").to_dict(orient="index")

    results = M.load_results(RESULTS_PATH)
    results = [r for r in results if "error" not in r]  # drop hard failures from metric computation

    out = {
        "run_id": RUN_ID, "n_cases_in_results": len(results), "n_cases_in_eval_set": len(eval_df),
        "decision_accuracy_and_macro_f1": M.decision_accuracy_and_macro_f1(results, eval_lookup),
        "pre_validation_uncited_claim_rate": M.pre_validation_uncited_claim_rate(results),
        "post_validation_uncited_claim_rate": M.post_validation_uncited_claim_rate(results),
        "json_repair_rescue_rate": M.json_repair_rescue_rate(results),
        "retry_rescue_rate": M.retry_rescue_rate(results),
        "retry_rate": M.retry_rate(results),
        "escalation_precision_recall_on_insufficient_evidence": M.escalation_precision_recall(results, eval_lookup),
        "mean_tool_calls_and_critic_rate": M.mean_tool_calls_and_critic_rate(results),
    }

    budget = TokenBudgetTracker("data/token_budget.sqlite")
    out["token_budget_report"] = budget.report_by_node_and_model(RUN_ID)
    out["total_tokens"] = budget.total_used(run_id=RUN_ID)
    budget.close()

    out_path = f"data/eval_runs/{RUN_ID}_metrics.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
