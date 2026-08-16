"""For the single-shot ablation, the model self-reports a fabricated
evidence_ledger (it never called real tools), so judging its findings
against that ledger would just check internal self-consistency, not
whether it hallucinated facts about the actual case. This module
independently calls the REAL tools for a case's user once and returns the
genuine evidence, which the judge should compare single-shot findings
against instead.
"""
from sentinel.tools.registry import EvidenceLedger
from sentinel.tools.impl import (
    get_entity_profile, get_event_history, get_shared_entity_network,
    get_velocity_features,
)


def fetch_real_evidence_bundle(user_id: str) -> dict:
    ledger = EvidenceLedger()
    get_entity_profile(ledger, user_id=user_id)
    get_event_history(ledger, user_id=user_id, lookback_days=365, limit=30)
    get_shared_entity_network(ledger, user_id=user_id)
    get_velocity_features(ledger, user_id=user_id)
    return {r.evidence_id: r.raw_result for r in ledger.all()}


def extract_findings_against_ground_truth(results: list[dict], case_contexts: dict) -> list[dict]:
    """Like judge.extract_findings, but every finding is judged against the
    REAL evidence for that case's user, ignoring whatever self-fabricated
    ledger the single-shot model reported."""
    out = []
    cache: dict[str, dict] = {}
    for r in results:
        fr = r.get("final_report")
        if fr is None:
            continue
        case_id = fr["case_id"]
        user_id = case_contexts.get(case_id, {}).get("user_id")
        if user_id is None:
            continue
        if user_id not in cache:
            cache[user_id] = fetch_real_evidence_bundle(user_id)
        real_evidence = cache[user_id]
        for i, finding in enumerate(fr["findings"]):
            out.append({
                "case_id": case_id, "finding_index": i, "claim": finding["claim"],
                "supports_fraud": finding["supports_fraud"], "strength": finding["strength"],
                "cited_evidence": real_evidence,  # the REAL bundle, not the model's own fabrication
            })
    return out
