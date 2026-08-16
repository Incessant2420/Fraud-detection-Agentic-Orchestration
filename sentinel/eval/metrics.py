"""Eval metrics per spec section 10, all with bootstrap CIs (500 resamples)."""
import json

import numpy as np
from sklearn.metrics import f1_score, accuracy_score

DISPOSITIONS = ["APPROVE", "HOLD_PENDING_VERIFICATION", "BLOCK", "ESCALATE_TO_HUMAN"]


def bootstrap_ci(values: list, statistic_fn=np.mean, n_resamples: int = 500,
                  seed: int = 20260817) -> dict:
    values = np.asarray(values)
    if len(values) == 0:
        return {"point": None, "ci_low": None, "ci_high": None, "n": 0}
    rng = np.random.default_rng(seed)
    point = float(statistic_fn(values))
    boots = []
    for _ in range(n_resamples):
        sample = rng.choice(values, size=len(values), replace=True)
        boots.append(float(statistic_fn(sample)))
    boots.sort()
    lo = boots[int(0.025 * n_resamples)]
    hi = boots[int(0.975 * n_resamples) - 1]
    return {"point": point, "ci_low": lo, "ci_high": hi, "n": len(values)}


def load_results(results_path: str) -> list[dict]:
    rows = []
    with open(results_path) as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def decision_accuracy_and_macro_f1(results: list[dict], eval_lookup: dict) -> dict:
    y_true, y_pred = [], []
    for r in results:
        case_id = r["case_id"]
        if r.get("final_report") is None or case_id not in eval_lookup:
            continue
        y_true.append(eval_lookup[case_id]["expected_disposition"])
        y_pred.append(r["final_report"]["disposition"])
    if not y_true:
        return {"accuracy": None, "macro_f1": None, "n": 0}
    acc = accuracy_score(y_true, y_pred)
    f1 = f1_score(y_true, y_pred, labels=DISPOSITIONS, average="macro", zero_division=0)
    return {
        "accuracy": bootstrap_ci([int(t == p) for t, p in zip(y_true, y_pred)]),
        "macro_f1_point_estimate": float(f1),
        "n": len(y_true),
    }


def pre_validation_uncited_claim_rate(results: list[dict]) -> dict:
    """From first-attempt generation logs: how often the raw model cited
    nonexistent evidence before any validator/critic intervention."""
    first_attempts = []
    for r in results:
        log = r.get("generation_log") or []
        firsts = [a for a in log if a["attempt_number"] == 1]
        if firsts:
            first_attempts.append(1 if firsts[0]["had_uncited_claim"] else 0)
    return bootstrap_ci(first_attempts) if first_attempts else {"point": None, "n": 0}


def post_validation_uncited_claim_rate(results: list[dict]) -> dict:
    """Must be 0 by construction -- the Pydantic validator rejects any
    finding citing a nonexistent evidence_id, so no *final* report can have
    one. Included as an explicit measured check, not an assumption."""
    violations = 0
    n = 0
    for r in results:
        fr = r.get("final_report")
        if fr is None:
            continue
        n += 1
        ledger_ids = {e["evidence_id"] for e in fr["evidence_ledger"]}
        for finding in fr["findings"]:
            if set(finding["evidence_ids"]) - ledger_ids:
                violations += 1
                break
    return {"rate": violations / n if n else None, "violations": violations, "n": n}


def json_repair_rescue_rate(results: list[dict]) -> dict:
    needed, rescued = 0, 0
    for r in results:
        for a in r.get("generation_log") or []:
            if a["json_repair_applied"]:
                needed += 1
                if a.get("json_repair_succeeded"):
                    rescued += 1
    return {"rate": rescued / needed if needed else None, "needed": needed, "rescued": rescued}


def retry_rescue_rate(results: list[dict]) -> dict:
    """Of cases whose first attempt failed pydantic validation, how many
    were rescued by a subsequent retry (final_report exists)."""
    first_failed = 0
    rescued = 0
    for r in results:
        log = r.get("generation_log") or []
        firsts = [a for a in log if a["attempt_number"] == 1]
        if firsts and not firsts[0]["pydantic_valid"]:
            first_failed += 1
            if r.get("final_report") is not None and not (r.get("generation_log")[-1].get("forced_escalation")):
                rescued += 1
    return {"rate": rescued / first_failed if first_failed else None,
            "first_attempt_failures": first_failed, "rescued": rescued}


def escalation_precision_recall(results: list[dict], eval_lookup: dict) -> dict:
    tp = fp = fn = tn = 0
    for r in results:
        case_id = r["case_id"]
        if case_id not in eval_lookup or r.get("final_report") is None:
            continue
        is_insufficient = eval_lookup[case_id]["stratum"] == "insufficient_evidence"
        escalated = r["final_report"]["disposition"] == "ESCALATE_TO_HUMAN"
        if is_insufficient and escalated:
            tp += 1
        elif is_insufficient and not escalated:
            fn += 1
        elif not is_insufficient and escalated:
            fp += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {"precision": precision, "recall": recall, "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def mean_tool_calls_and_critic_rate(results: list[dict]) -> dict:
    tool_calls = [r.get("n_tool_calls", 0) for r in results if r.get("final_report") is not None]
    critic_triggers = [1 if r.get("critic_triggered") else 0 for r in results]
    return {
        "mean_tool_calls_per_case": bootstrap_ci(tool_calls) if tool_calls else {"point": None},
        "critic_trigger_rate": bootstrap_ci(critic_triggers) if critic_triggers else {"point": None},
    }


def retry_rate(results: list[dict]) -> dict:
    retried = [1 if len(r.get("generation_log") or []) > 1 else 0 for r in results]
    return bootstrap_ci(retried) if retried else {"point": None}
