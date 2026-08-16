"""Judges each ablation variant's findings for semantic hallucination.
full_system / no_critic are judged against their own REAL tool ledger.
single_shot never called real tools, so its self-reported evidence_ledger
is fabricated -- judging against it would only check self-consistency, not
whether it hallucinated facts about the actual case. Instead, single_shot's
findings are judged against independently-fetched REAL evidence for the
same user (see sentinel/eval/ground_truth_evidence.py).
"""
import json

import pandas as pd

from sentinel.budget import TokenBudgetTracker
from sentinel.cache import ResponseCache
from sentinel.eval import metrics as M
from sentinel.eval.build_eval_set import case_context_for_row
from sentinel.eval.ground_truth_evidence import extract_findings_against_ground_truth
from sentinel.eval.judge import extract_findings, run_semantic_judge
from sentinel.llm import LLMRouter

VARIANTS = ["full_system", "no_critic", "single_shot_baseline"]


def main():
    subset = pd.read_parquet("data/processed/ablation_subset.parquet")
    case_contexts = {row["case_id"]: case_context_for_row(row) for _, row in subset.iterrows()}

    cache = ResponseCache("data/response_cache.sqlite")
    budget = TokenBudgetTracker("data/token_budget.sqlite")
    llm = LLMRouter(run_id="ablation-judge", cache=cache, budget=budget, use_cache=True)

    out = {}
    for variant in VARIANTS:
        results = M.load_results(f"data/eval_runs/ablation-{variant}.jsonl")
        results = [r for r in results if "error" not in r]
        if variant == "single_shot_baseline":
            findings = extract_findings_against_ground_truth(results, case_contexts)
        else:
            findings = extract_findings(results)

        if not findings:
            out[variant] = {"n_available": 0}
            continue
        # Reduced sample size -- see run_ablations.py / run_judge_and_kappa.py for why.
        judged = run_semantic_judge(findings, llm, n_sample=min(30, len(findings)))
        out[variant] = {k: v for k, v in judged.items() if k != "judged"}
        print(f"{variant}: n={judged['n_sampled']} hallucination_rate={judged['semantic_hallucination_rate']}")

    with open("data/eval_runs/ablation_judge_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nwrote data/eval_runs/ablation_judge_results.json")
    cache.close()
    budget.close()


if __name__ == "__main__":
    main()
