"""Runs no_critic and single_shot_baseline on the exact same case_ids that
full_system already completed, for a fair small-N comparison. See
BUILD_LOG.md for why the ablation subset was cut from 40 (spec) to 16, then
to these 9 -- sequential per-minute throttling once executor/synthesizer/
critic were all forced onto one shared model bucket (see config/models.yaml)."""
import json

import pandas as pd

from sentinel.agent.graph import run_case_no_critic, run_case_single_shot
from sentinel.batch_runner import run_batch
from sentinel.eval.build_eval_set import case_context_for_row

with open("data/ablation_case_ids.json") as f:
    case_ids = json.load(f)

subset = pd.read_parquet("data/processed/ablation_subset.parquet")
subset = subset[subset["case_id"].isin(case_ids)]
case_contexts = {row["case_id"]: case_context_for_row(row) for _, row in subset.iterrows()}

for variant_name, fn in [("no_critic", run_case_no_critic), ("single_shot_baseline", run_case_single_shot)]:
    run_id = f"ablation-{variant_name}"
    print(f"=== {variant_name} on {len(case_ids)} cases ===")
    result = run_batch(run_id, case_ids, use_cache=True, checkpoint_every=3,
                        case_contexts=case_contexts, run_case_fn=fn)
    print(json.dumps({k: v for k, v in result.items() if k != "token_report"}, default=str))
