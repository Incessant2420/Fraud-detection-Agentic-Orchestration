"""Semantic hallucination judge (spec section 10.5) + Cohen's kappa
validation against hand-labeled findings (10.6).

Judge sees ONLY the claim + its cited evidence's raw payloads -- never the
digest, never the rest of the ledger -- and classifies:
SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED.
"""
import json
import re

import numpy as np

from sentinel.llm import LLMRouter, safe_json_loads

LABELS = ["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED"]


def extract_findings(results: list[dict]) -> list[dict]:
    """Flatten every (case_id, finding, cited_evidence) triple out of a
    batch of agent run results."""
    out = []
    for r in results:
        fr = r.get("final_report")
        if fr is None:
            continue
        ledger_by_id = {e["evidence_id"]: e for e in fr["evidence_ledger"]}
        for i, finding in enumerate(fr["findings"]):
            cited = {eid: ledger_by_id[eid]["raw_result"] for eid in finding["evidence_ids"] if eid in ledger_by_id}
            out.append({
                "case_id": fr["case_id"], "finding_index": i, "claim": finding["claim"],
                "supports_fraud": finding["supports_fraud"], "strength": finding["strength"],
                "cited_evidence": cited,
            })
    return out


def judge_prompt(claim: str, cited_evidence: dict) -> str:
    return f"""You are a strict fact-checker. You will be shown ONE claim from a fraud
investigation report and ONLY the raw evidence payloads it cited (nothing else about
the case). Classify whether the evidence actually supports the claim.

CLAIM:
{claim}

CITED EVIDENCE (evidence_id -> raw tool result):
{json.dumps(cited_evidence, indent=2, default=str)}

Respond with ONLY a JSON object:
{{"label": "SUPPORTED" | "PARTIALLY_SUPPORTED" | "UNSUPPORTED", "reason": "one sentence"}}

SUPPORTED: the evidence fully and directly substantiates the claim.
PARTIALLY_SUPPORTED: the evidence is relevant and consistent with the claim but does not
fully establish it (e.g. suggestive but small sample size, or supports part of a
compound claim).
UNSUPPORTED: the evidence does not support the claim, contradicts it, or the claim
asserts something the evidence doesn't contain."""


def run_semantic_judge(findings: list[dict], llm: LLMRouter, n_sample: int = 150,
                        seed: int = 20260817) -> dict:
    rng = np.random.default_rng(seed)
    n = min(n_sample, len(findings))
    idx = rng.choice(len(findings), size=n, replace=False)
    sampled = [findings[i] for i in idx]

    judged = []
    for f in sampled:
        prompt = judge_prompt(f["claim"], f["cited_evidence"])
        resp = llm.call("judge", prompt, case_id=f["case_id"])
        parsed, _, _ = safe_json_loads(resp["content"])
        label = parsed.get("label") if parsed and parsed.get("label") in LABELS else "UNSUPPORTED"
        judged.append({**f, "judge_label": label, "judge_reason": (parsed or {}).get("reason", "")})

    counts = {lbl: sum(1 for j in judged if j["judge_label"] == lbl) for lbl in LABELS}
    total = len(judged)
    return {
        "n_sampled": total, "n_available": len(findings), "counts": counts,
        "semantic_hallucination_rate": counts["UNSUPPORTED"] / total if total else None,
        "partially_supported_rate": counts["PARTIALLY_SUPPORTED"] / total if total else None,
        "supported_rate": counts["SUPPORTED"] / total if total else None,
        "judged": judged,
    }


def cohens_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    assert len(labels_a) == len(labels_b)
    n = len(labels_a)
    categories = sorted(set(labels_a) | set(labels_b))
    observed_agreement = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / n

    p_a = {c: labels_a.count(c) / n for c in categories}
    p_b = {c: labels_b.count(c) / n for c in categories}
    expected_agreement = sum(p_a[c] * p_b[c] for c in categories)

    if expected_agreement == 1.0:
        return 1.0
    return (observed_agreement - expected_agreement) / (1 - expected_agreement)
