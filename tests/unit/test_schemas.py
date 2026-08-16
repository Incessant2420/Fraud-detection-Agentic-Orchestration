import pytest
from pydantic import ValidationError

from sentinel.schemas import CaseReport, Disposition, Finding, PolicyCitation, ToolCallRecord


def _ledger():
    return [
        ToolCallRecord(
            evidence_id="EV-001", tool_name="get_entity_profile", arguments={"user_id": "u1"},
            result_digest="user=u1 age_days=40 events=5", raw_result={"n_events": 5},
            latency_ms=12, called_at="2026-01-01T00:00:00Z",
        )
    ]


def _valid_kwargs(**overrides):
    base = dict(
        case_id="C-1", domain="BANK", disposition=Disposition.HOLD_PENDING_VERIFICATION,
        confidence=0.5,
        findings=[Finding(claim="Account shows unusual velocity spike", evidence_ids=["EV-001"],
                           supports_fraud=True, strength="MODERATE")],
        policy_citations=[PolicyCitation(policy_id="POL-FRD-2.1", excerpt="...", relevance="velocity")],
        reasoning_summary="This is a sufficiently long reasoning summary for the test case report.",
        unresolved_questions=[],
        evidence_ledger=_ledger(),
    )
    base.update(overrides)
    return base


def test_valid_report_constructs():
    report = CaseReport(**_valid_kwargs())
    assert report.disposition == Disposition.HOLD_PENDING_VERIFICATION


def test_finding_must_cite_evidence_ids():
    with pytest.raises(ValidationError):
        Finding(claim="No evidence claim here", evidence_ids=[], supports_fraud=True, strength="WEAK")


def test_uncited_evidence_id_rejected():
    kwargs = _valid_kwargs(
        findings=[Finding(claim="Cites evidence that does not exist", evidence_ids=["EV-999"],
                           supports_fraud=True, strength="WEAK")]
    )
    with pytest.raises(ValidationError, match="non-existent evidence"):
        CaseReport(**kwargs)


def test_escalation_requires_unresolved_questions():
    kwargs = _valid_kwargs(disposition=Disposition.ESCALATE_TO_HUMAN, unresolved_questions=[])
    with pytest.raises(ValidationError, match="unresolved"):
        CaseReport(**kwargs)

    kwargs2 = _valid_kwargs(disposition=Disposition.ESCALATE_TO_HUMAN,
                             unresolved_questions=["Could not confirm device ownership"])
    report = CaseReport(**kwargs2)
    assert report.disposition == Disposition.ESCALATE_TO_HUMAN


def test_high_confidence_requires_strong_finding():
    kwargs = _valid_kwargs(
        confidence=0.9,
        findings=[Finding(claim="Only a moderate finding present here", evidence_ids=["EV-001"],
                           supports_fraud=True, strength="MODERATE")],
    )
    with pytest.raises(ValidationError, match="STRONG"):
        CaseReport(**kwargs)

    kwargs2 = _valid_kwargs(
        confidence=0.9,
        findings=[Finding(claim="A strong, well-supported finding here", evidence_ids=["EV-001"],
                           supports_fraud=True, strength="STRONG")],
    )
    report = CaseReport(**kwargs2)
    assert report.confidence == 0.9
