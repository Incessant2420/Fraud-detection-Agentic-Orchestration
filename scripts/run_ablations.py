"""Phase 10: 3 ablations on a fixed 40-case subset.
  - full system      (executor -> synthesizer -> critic? -> validator -> escalation_gate)
  - no critic         (same graph, critic node skipped)
  - single-shot baseline (one prompt, no LangGraph, no validation)
"""
import json
import sys

import numpy as np
import pandas as pd

from sentinel.agent.graph import run_case, run_case_no_critic, run_case_single_shot
from sentinel.batch_runner import run_batch
from sentinel.eval.build_eval_set import case_context_for_row

SEED = 20260817
# Reduced from the spec's 40-case ablation subset to 16 -- by this point in
# the live eval, 2 of 4 Groq free-tier model buckets (llama-3.3-70b-versatile,
# openai/gpt-oss-120b) had hit real daily token caps in a single day of
# testing; running 3x40 additional live agent calls risked the same fate
# well before completion. 16 cases still spans all 4 strata (see
# get_ablation_subset) and is enough to compare the 3 variants directionally
# -- documented explicitly as a reduction, not a silent shortcut.
N_SUBSET = 16


def get_ablation_subset() -> pd.DataFrame:
    eval_df = pd.read_parquet("data/processed/eval_set.parquet")
    rng = np.random.default_rng(SEED)
    # stratified 40-case subset, proportional to the full eval set's strata
    parts = []
    for stratum, grp in eval_df.groupby("stratum"):
        frac = len(grp) / len(eval_df)
        n = max(1, round(frac * N_SUBSET))
        idx = rng.choice(grp.index.values, size=min(n, len(grp)), replace=False)
        parts.append(grp.loc[idx])
    subset = pd.concat(parts, ignore_index=True).head(N_SUBSET)
    subset.to_parquet("data/processed/ablation_subset.parquet", index=False)
    return subset


VARIANTS = {
    "full_system": run_case,
    "no_critic": run_case_no_critic,
    "single_shot_baseline": run_case_single_shot,
}


def main():
    subset = get_ablation_subset()
    case_contexts = {row["case_id"]: case_context_for_row(row) for _, row in subset.iterrows()}
    case_ids = list(case_contexts.keys())
    print(f"ablation subset: {len(case_ids)} cases")

    for variant_name, fn in VARIANTS.items():
        run_id = f"ablation-{variant_name}"
        print(f"\n=== running ablation: {variant_name} ===")
        result = run_batch(run_id, case_ids, use_cache=True, checkpoint_every=5,
                            case_contexts=case_contexts, run_case_fn=fn)
        print(json.dumps({k: v for k, v in result.items() if k != "token_report"}, default=str))


if __name__ == "__main__":
    main()
