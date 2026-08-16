"""Phase 9: build the 120-case stratified eval set per spec section 10.

Stratification:
  40% true fraud/abuse with clear evidence   (48 cases: 24 bank + 24 commerce)
  25% hard negatives                          (30 cases: commerce only -- see note)
  20% insufficient_evidence                   (24 cases: 12 bank + 12 commerce)
  15% clear legitimate                        (18 cases: 9 bank + 9 commerce)

Note on hard negatives: IEEE-CIS (bank arm) has no constructed "looks like
fraud but isn't" cases -- only real is_fraud true/false. The hard-negative
stratum therefore draws exclusively from the commerce arm's injected
Pattern D (family/office/shared-accommodation). This is a real, stated
limitation, not an oversight -- see README.

"insufficient_evidence" cases are selected (not synthesized) as real
first-ever-activity events (prior_event_count == 0), which is what a
"deliberately truncated history" naturally looks like from the tools'
point of view -- every history/velocity tool call for these users
legitimately returns near-empty results.
"""
import json

import numpy as np
import pandas as pd

from sentinel.baseline import score_events_by_id, FEATURE_COLS

SEED = 20260817
OUT_PATH = "data/processed/eval_set.parquet"

EXPECTED_DISPOSITION = {
    "true_fraud": "BLOCK",
    "hard_negative": "APPROVE",
    "insufficient_evidence": "ESCALATE_TO_HUMAN",
    "clear_legitimate": "APPROVE",
}


def _sample(df: pd.DataFrame, n: int, rng) -> pd.DataFrame:
    n = min(n, len(df))
    idx = rng.choice(df.index.values, size=n, replace=False)
    return df.loc[idx]


def build_eval_set(n_total: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    bank = pd.read_parquet("data/processed/features_bank.parquet")
    commerce = pd.read_parquet("data/processed/features_commerce.parquet")

    n_true_fraud = round(n_total * 0.40)
    n_hard_neg = round(n_total * 0.25)
    n_insufficient = round(n_total * 0.20)
    n_clear_legit = n_total - n_true_fraud - n_hard_neg - n_insufficient

    rows = []

    # true_fraud: split across domains
    bank_fraud = bank[(bank["is_fraud"]) & (bank["prior_event_count"] > 0)]
    comm_fraud = commerce[(commerce["is_fraud"]) & (commerce["prior_event_count"] >= 0)]
    n_bank_f = n_true_fraud // 2
    n_comm_f = n_true_fraud - n_bank_f
    rows.append(_sample(bank_fraud, n_bank_f, rng).assign(stratum="true_fraud", domain="BANK"))
    rows.append(_sample(comm_fraud, n_comm_f, rng).assign(stratum="true_fraud", domain="COMMERCE"))

    # hard_negative: commerce only (see module docstring)
    comm_hard_neg = commerce[commerce["abuse_type"] == "NONE"]
    rows.append(_sample(comm_hard_neg, n_hard_neg, rng).assign(stratum="hard_negative", domain="COMMERCE"))

    # insufficient_evidence: first-ever-activity events, split across domains
    bank_sparse = bank[bank["prior_event_count"] == 0]
    comm_sparse = commerce[commerce["prior_event_count"] == 0]
    n_bank_i = n_insufficient // 2
    n_comm_i = n_insufficient - n_bank_i
    rows.append(_sample(bank_sparse, n_bank_i, rng).assign(stratum="insufficient_evidence", domain="BANK"))
    rows.append(_sample(comm_sparse, n_comm_i, rng).assign(stratum="insufficient_evidence", domain="COMMERCE"))

    # clear_legitimate: established, no abuse label, split across domains
    bank_clean = bank[(~bank["is_fraud"]) & (bank["prior_event_count"] > 2)]
    comm_clean = commerce[(commerce["abuse_type"].isna()) & (commerce["prior_event_count"] > 2)]
    n_bank_c = n_clear_legit // 2
    n_comm_c = n_clear_legit - n_bank_c
    rows.append(_sample(bank_clean, n_bank_c, rng).assign(stratum="clear_legitimate", domain="BANK"))
    rows.append(_sample(comm_clean, n_comm_c, rng).assign(stratum="clear_legitimate", domain="COMMERCE"))

    combined = pd.concat(rows, ignore_index=True)

    # score + SHAP-explain every eval case (not just the 98th-percentile
    # flagged set) via the persisted baseline models
    scored_parts = []
    for domain, grp in combined.groupby("domain"):
        scored = score_events_by_id(domain, grp["event_id"].tolist())
        scored_parts.append(scored.merge(
            grp[["event_id", "stratum"]], on="event_id", how="inner"
        ))
    scored_df = pd.concat(scored_parts, ignore_index=True)

    eval_rows = []
    for i, row in scored_df.iterrows():
        case_id = f"EVAL-{row['domain']}-{row['event_id']}"
        eval_rows.append({
            "case_id": case_id,
            "domain": row["domain"],
            "user_id": row["actor_user_id"],
            "event_id": row["event_id"],
            "risk_score": float(row["risk_score"]),
            "shap_drivers": row["shap_drivers"],
            "flagged_at": str(row["timestamp"]),
            "stratum": row["stratum"],
            "expected_disposition": EXPECTED_DISPOSITION[row["stratum"]],
            "ground_truth_is_fraud": bool(row["is_fraud"]),
            "abuse_type": row["abuse_type"],
        })

    eval_df = pd.DataFrame(eval_rows).drop_duplicates(subset=["case_id"])
    eval_df.to_parquet(OUT_PATH, index=False)
    return eval_df


def case_context_for_row(row: dict) -> dict:
    return {
        "case_id": row["case_id"], "domain": row["domain"], "user_id": row["user_id"],
        "event_id": row["event_id"], "baseline_risk_score": row["risk_score"],
        "shap_drivers": json.loads(row["shap_drivers"]) if isinstance(row["shap_drivers"], str) else row["shap_drivers"],
        "flagged_at": row["flagged_at"],
    }


if __name__ == "__main__":
    df = build_eval_set()
    print(f"eval set: {len(df)} cases")
    print(df.groupby(["stratum", "domain"]).size())
