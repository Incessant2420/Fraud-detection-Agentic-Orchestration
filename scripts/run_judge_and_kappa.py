"""Phase 9 (judge): sample 150 findings from the completed eval run, run the
semantic-hallucination judge, then compute Cohen's kappa between the judge
and a careful hand-labeling of 50 of those same findings.
"""
import json
import sys

from sentinel.budget import TokenBudgetTracker
from sentinel.cache import ResponseCache
from sentinel.eval import metrics as M
from sentinel.eval.judge import extract_findings, run_semantic_judge, cohens_kappa
from sentinel.llm import LLMRouter

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "full-eval-001"


def main():
    results = M.load_results(f"data/eval_runs/{RUN_ID}.jsonl")
    results = [r for r in results if "error" not in r]
    findings = extract_findings(results)
    print(f"extracted {len(findings)} findings from {len(results)} completed cases")

    cache = ResponseCache("data/response_cache.sqlite")
    budget = TokenBudgetTracker("data/token_budget.sqlite")
    llm = LLMRouter(run_id=f"judge-{RUN_ID}", cache=cache, budget=budget, use_cache=True)

    # Reduced from the spec's 150-finding judge sample -- see run_ablations.py
    # for why (2 of 4 model buckets hit real daily caps in one day of testing).
    judge_result = run_semantic_judge(findings, llm, n_sample=min(50, len(findings)))
    print(f"judged {judge_result['n_sampled']} / {judge_result['n_available']} available findings")
    print("counts:", judge_result["counts"])
    print("semantic_hallucination_rate:", judge_result["semantic_hallucination_rate"])

    # Reduced from the spec's 50-finding hand-label set to 20 -- same reason.
    hand_label_pool = judge_result["judged"][:20]
    out_path = f"data/eval_runs/{RUN_ID}_hand_label_pool.json"
    with open(out_path, "w") as f:
        json.dump(hand_label_pool, f, indent=2, default=str)
    print(f"\nwrote {len(hand_label_pool)}-finding hand-label pool to {out_path}")
    print("Next: run scripts/apply_hand_labels.py after hand-labeling this pool.")

    judge_out_path = f"data/eval_runs/{RUN_ID}_judge_results.json"
    with open(judge_out_path, "w") as f:
        json.dump(judge_result, f, indent=2, default=str)

    cache.close()
    budget.close()


if __name__ == "__main__":
    main()
