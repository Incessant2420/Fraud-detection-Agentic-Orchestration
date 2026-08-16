"""LightGBM baseline flagging model, one per domain. Temporal split (not
random -- fraud data is time-ordered and a random split leaks). Reports
AUC-PR (not ROC-AUC -- with ~2-4% positives, PR is the honest metric).
Flags at the 98th percentile and attaches top-5 SHAP drivers per flagged
case, which the executor agent receives as investigative hints.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
import shap
from sklearn.metrics import average_precision_score

PROCESSED = Path("data/processed")


def _build_features(domain: str) -> pd.DataFrame:
    events = pd.read_parquet(PROCESSED / "events.parquet")
    links = pd.read_parquet(PROCESSED / "entity_links.parquet")
    labels = pd.read_parquet(PROCESSED / "labels.parquet")

    dom_events = events[events["domain"] == domain].copy()
    dom_events = dom_events.merge(labels, on="event_id", how="inner")
    dom_events = dom_events.sort_values("timestamp").reset_index(drop=True)

    # prior_event_count and account_age_days per user, computed causally
    # (only using events strictly before the current one -- no label leakage).
    dom_events["prior_event_count"] = dom_events.groupby("actor_user_id").cumcount()
    first_seen = dom_events.groupby("actor_user_id")["timestamp"].transform("min")
    dom_events["account_age_days"] = (dom_events["timestamp"] - first_seen).dt.total_seconds() / 86400

    # distinct-entity count per event + a cluster-size proxy: for each
    # entity linked to this event, how many distinct users have ever used
    # that entity (global, not time-aware -- a documented simplification
    # for baseline feature speed; the agent's real-time tool call is exact).
    dom_links = links[links["event_id"].isin(dom_events["event_id"])].merge(
        dom_events[["event_id", "actor_user_id"]], on="event_id"
    )
    entity_user_counts = dom_links.groupby("entity_id")["actor_user_id"].nunique().rename("entity_user_count")
    dom_links = dom_links.merge(entity_user_counts, on="entity_id")
    per_event_cluster = dom_links.groupby("event_id").agg(
        n_linked_entities=("entity_id", "nunique"),
        max_entity_cluster_size=("entity_user_count", "max"),
    ).reset_index()

    dom_events = dom_events.merge(per_event_cluster, on="event_id", how="left")
    dom_events["n_linked_entities"] = dom_events["n_linked_entities"].fillna(0)
    dom_events["max_entity_cluster_size"] = dom_events["max_entity_cluster_size"].fillna(1)

    return dom_events


FEATURE_COLS = ["amount", "prior_event_count", "account_age_days",
                "n_linked_entities", "max_entity_cluster_size"]


def train_and_flag(domain: str, top_n_cases: int = 120) -> dict:
    df = _build_features(domain)
    df = df.dropna(subset=FEATURE_COLS)

    split_idx = int(len(df) * 0.7)
    train_df, test_df = df.iloc[:split_idx], df.iloc[split_idx:]

    X_train, y_train = train_df[FEATURE_COLS], train_df["is_fraud"].astype(int)
    X_test, y_test = test_df[FEATURE_COLS], test_df["is_fraud"].astype(int)

    model = lgb.LGBMClassifier(n_estimators=200, max_depth=5, learning_rate=0.05,
                                class_weight="balanced", verbosity=-1)
    model.fit(X_train, y_train)

    import joblib
    PROCESSED.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, PROCESSED / f"model_{domain.lower()}.joblib")
    # full (train+test) feature table persisted so the eval harness can
    # score/explain ANY event_id (including hard negatives / insufficient-
    # evidence cases that a 98th-percentile flag would never surface).
    df.to_parquet(PROCESSED / f"features_{domain.lower()}.parquet", index=False)

    test_scores = model.predict_proba(X_test)[:, 1]
    auc_pr = average_precision_score(y_test, test_scores) if y_test.sum() > 0 else float("nan")

    threshold = np.percentile(test_scores, 98)
    test_df = test_df.copy()
    test_df["risk_score"] = test_scores
    flagged = test_df[test_df["risk_score"] >= threshold].sort_values("risk_score", ascending=False)
    flagged = flagged.head(top_n_cases)

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(flagged[FEATURE_COLS])
    if isinstance(shap_values, list):  # binary classifier sometimes returns [neg, pos]
        shap_values = shap_values[1]

    cases = []
    for i, (_, row) in enumerate(flagged.iterrows()):
        contribs = list(zip(FEATURE_COLS, shap_values[i]))
        contribs.sort(key=lambda x: -abs(x[1]))
        top5 = [{"feature": f, "shap_value": round(float(v), 5)} for f, v in contribs[:5]]
        cases.append({
            "case_id": f"CASE-{domain}-{row['event_id']}",
            "event_id": row["event_id"],
            "domain": domain,
            "user_id": row["actor_user_id"],
            "risk_score": round(float(row["risk_score"]), 5),
            "shap_drivers": json.dumps(top5),
            "ground_truth_is_fraud": bool(row["is_fraud"]),
            "abuse_type": row["abuse_type"],
            "timestamp": str(row["timestamp"]),
        })

    cases_df = pd.DataFrame(cases)
    out_path = PROCESSED / f"cases_{domain.lower()}.parquet"
    cases_df.to_parquet(out_path, index=False)

    return {
        "domain": domain, "auc_pr": auc_pr, "n_train": len(train_df), "n_test": len(test_df),
        "n_flagged": len(cases_df), "threshold_98pct": float(threshold), "out_path": str(out_path),
    }


def score_events_by_id(domain: str, event_ids: list[str]) -> pd.DataFrame:
    """Score arbitrary event_ids (not just the top-98th-percentile flagged
    set) using the persisted model — needed so the eval harness can build a
    stratified set that includes hard negatives and insufficient-evidence
    cases the flagging threshold would never surface on its own."""
    import joblib
    model = joblib.load(PROCESSED / f"model_{domain.lower()}.joblib")
    features = pd.read_parquet(PROCESSED / f"features_{domain.lower()}.parquet")
    subset = features[features["event_id"].isin(event_ids)].copy()
    subset["risk_score"] = model.predict_proba(subset[FEATURE_COLS])[:, 1]

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(subset[FEATURE_COLS])
    if isinstance(shap_values, list):
        shap_values = shap_values[1]

    drivers = []
    for i in range(len(subset)):
        contribs = sorted(zip(FEATURE_COLS, shap_values[i]), key=lambda x: -abs(x[1]))
        drivers.append(json.dumps([{"feature": f, "shap_value": round(float(v), 5)} for f, v in contribs[:5]]))
    subset["shap_drivers"] = drivers
    return subset


if __name__ == "__main__":
    for d in ["BANK", "COMMERCE"]:
        result = train_and_flag(d)
        print(result)
