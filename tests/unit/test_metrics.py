from sentinel.eval import metrics as M
from sentinel.eval.judge import cohens_kappa


def test_bootstrap_ci_basic():
    out = M.bootstrap_ci([1, 1, 1, 1, 0, 0, 0, 0])
    assert out["point"] == 0.5
    assert out["ci_low"] <= 0.5 <= out["ci_high"]
    assert out["n"] == 8


def test_bootstrap_ci_empty():
    out = M.bootstrap_ci([])
    assert out["point"] is None


def _mk_result(case_id, disposition, findings=None):
    return {
        "case_id": case_id,
        "final_report": {"disposition": disposition, "findings": findings or [{"strength": "STRONG"}],
                          "evidence_ledger": [{"evidence_id": "EV-001"}]},
        "generation_log": [{"attempt_number": 1, "had_uncited_claim": False, "pydantic_valid": True,
                             "json_repair_applied": False}],
        "n_tool_calls": 2, "critic_triggered": False,
    }


def test_decision_accuracy_perfect_match():
    results = [_mk_result("c1", "BLOCK"), _mk_result("c2", "APPROVE")]
    eval_lookup = {"c1": {"expected_disposition": "BLOCK"}, "c2": {"expected_disposition": "APPROVE"}}
    out = M.decision_accuracy_and_macro_f1(results, eval_lookup)
    assert out["accuracy"]["point"] == 1.0


def test_decision_accuracy_all_wrong():
    results = [_mk_result("c1", "BLOCK"), _mk_result("c2", "BLOCK")]
    eval_lookup = {"c1": {"expected_disposition": "APPROVE"}, "c2": {"expected_disposition": "APPROVE"}}
    out = M.decision_accuracy_and_macro_f1(results, eval_lookup)
    assert out["accuracy"]["point"] == 0.0


def test_escalation_precision_recall():
    results = [
        _mk_result("c1", "ESCALATE_TO_HUMAN"),  # TP: insufficient_evidence, escalated
        _mk_result("c2", "APPROVE"),             # FN: insufficient_evidence, not escalated
        _mk_result("c3", "ESCALATE_TO_HUMAN"),  # FP: not insufficient_evidence, escalated
        _mk_result("c4", "APPROVE"),             # TN
    ]
    eval_lookup = {
        "c1": {"stratum": "insufficient_evidence"}, "c2": {"stratum": "insufficient_evidence"},
        "c3": {"stratum": "true_fraud"}, "c4": {"stratum": "clear_legitimate"},
    }
    out = M.escalation_precision_recall(results, eval_lookup)
    assert out["tp"] == 1 and out["fn"] == 1 and out["fp"] == 1 and out["tn"] == 1
    assert out["recall"] == 0.5
    assert out["precision"] == 0.5


def test_post_validation_uncited_rate_detects_violation():
    bad_result = {
        "final_report": {
            "findings": [{"evidence_ids": ["EV-999"]}],
            "evidence_ledger": [{"evidence_id": "EV-001"}],
        }
    }
    good_result = {
        "final_report": {
            "findings": [{"evidence_ids": ["EV-001"]}],
            "evidence_ledger": [{"evidence_id": "EV-001"}],
        }
    }
    out = M.post_validation_uncited_claim_rate([bad_result, good_result])
    assert out["violations"] == 1
    assert out["n"] == 2
    assert out["rate"] == 0.5


def test_cohens_kappa_perfect_agreement():
    labels = ["SUPPORTED", "UNSUPPORTED", "PARTIALLY_SUPPORTED", "SUPPORTED"]
    assert cohens_kappa(labels, labels) == 1.0


def test_cohens_kappa_chance_agreement_is_near_zero():
    a = ["SUPPORTED", "SUPPORTED", "UNSUPPORTED", "UNSUPPORTED"]
    b = ["UNSUPPORTED", "SUPPORTED", "SUPPORTED", "UNSUPPORTED"]
    kappa = cohens_kappa(a, b)
    assert -1.0 <= kappa <= 1.0
    assert kappa < 0.5  # half agreement with balanced classes -> low kappa
