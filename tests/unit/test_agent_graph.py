"""Deterministic tests for the LangGraph agent's failure/escalation paths --
these must not depend on live LLM stochasticity, since the whole point of
the enforcement layer is that it behaves correctly regardless of what the
model outputs."""
import json

from sentinel.agent.graph import (
    executor_node, synthesizer_node, validator_node, escalation_gate_node,
    critic_node, AgentState, _resolve_tool_name,
)
from sentinel.tools.registry import EvidenceLedger
from sentinel.tools.impl import get_entity_profile


def test_resolve_tool_name_is_case_insensitive():
    """Real bug found via live batch runs: the executor model frequently
    invents SCREAMING_SNAKE_CASE tool names. difflib.get_close_matches is
    case-sensitive, so without lowercasing first these were silently
    unmatchable and every investigation fell back to a single bootstrap
    tool call regardless of how many rounds the executor loop ran."""
    name, repaired = _resolve_tool_name("GET_USER_ACCOUNT_HISTORY")
    assert repaired is True
    assert name in ("get_event_history", "get_entity_profile")

    name2, repaired2 = _resolve_tool_name("get_entity_profile")
    assert repaired2 is False
    assert name2 == "get_entity_profile"

    name3, repaired3 = _resolve_tool_name("completely_unrelated_gibberish_xyz")
    assert name3 is None


class StubLLM:
    """Replays a fixed queue of responses regardless of prompt content."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls = []

    def call(self, node, prompt, case_id=None, response_format_json=True):
        self.calls.append(node)
        if not self._responses:
            return {"content": "{}", "cached": False, "prompt_tokens": 1, "completion_tokens": 1}
        r = self._responses.pop(0)
        return {"content": json.dumps(r) if isinstance(r, dict) else r,
                "cached": False, "prompt_tokens": 10, "completion_tokens": 10}


def _base_state(llm) -> AgentState:
    ledger = EvidenceLedger()
    get_entity_profile(ledger, user_id="U-TEST-001")
    return {
        "case_id": "CASE-TEST-1", "domain": "COMMERCE",
        "case_context": {"case_id": "CASE-TEST-1", "domain": "COMMERCE", "user_id": "U-TEST-001"},
        "plan": ["q1"], "ledger": ledger, "draft_report": None, "critique": None,
        "retry_count": 0, "critic_loop_count": 0, "validation_errors": [],
        "generation_log": [], "llm": llm, "final_report": None,
    }


def test_validator_rejects_uncited_evidence_and_retries():
    bad_draft = {
        "case_id": "CASE-TEST-1", "domain": "COMMERCE", "disposition": "BLOCK",
        "confidence": 0.9,
        "findings": [{"claim": "Cites evidence that was never gathered by any tool",
                       "evidence_ids": ["EV-999"], "supports_fraud": True, "strength": "STRONG"}],
        "policy_citations": [], "reasoning_summary": "x" * 60, "unresolved_questions": [],
    }
    state = _base_state(StubLLM([]))
    state["draft_report"] = bad_draft
    out = validator_node(state)
    assert out["final_report"] is None
    assert out["retry_count"] == 1
    assert "non-existent evidence" in out["validation_errors"][0]


def test_validator_accepts_well_cited_report():
    ledger = EvidenceLedger()
    get_entity_profile(ledger, user_id="U-TEST-001")
    ev_id = ledger.all()[0].evidence_id
    good_draft = {
        "case_id": "CASE-TEST-1", "domain": "COMMERCE", "disposition": "HOLD_PENDING_VERIFICATION",
        "confidence": 0.5,
        "findings": [{"claim": "Account is new with a single event on record",
                       "evidence_ids": [ev_id], "supports_fraud": True, "strength": "MODERATE"}],
        "policy_citations": [], "reasoning_summary": "y" * 60, "unresolved_questions": [],
    }
    state = _base_state(StubLLM([]))
    state["ledger"] = ledger
    state["draft_report"] = good_draft
    out = validator_node(state)
    assert out["final_report"] is not None
    assert out["final_report"]["disposition"] == "HOLD_PENDING_VERIFICATION"


def test_forced_escalation_after_max_retries():
    """A synthesizer that NEVER produces valid JSON must, after MAX_SYNTH_RETRIES,
    force ESCALATE_TO_HUMAN with the validation error as an unresolved question --
    never silently fail or crash."""
    llm = StubLLM(["not json at all {{{", "still not json", "definitely not json"])
    state = _base_state(llm)

    for attempt in range(3):
        synth_out = synthesizer_node(state)
        state.update(synth_out)
        val_out = validator_node(state)
        state.update(val_out)
        if state["final_report"] is not None or state["retry_count"] > 2:
            break

    final = escalation_gate_node(state)["final_report"]
    assert final["disposition"] == "ESCALATE_TO_HUMAN"
    assert len(final["unresolved_questions"]) >= 1
    assert len(final["findings"]) >= 1  # schema requires >=1 finding even in forced escalation


def test_escalation_gate_overrides_low_confidence():
    ledger = EvidenceLedger()
    get_entity_profile(ledger, user_id="U-TEST-001")
    ev_id = ledger.all()[0].evidence_id
    state = _base_state(StubLLM([]))
    state["ledger"] = ledger
    state["final_report"] = {
        "case_id": "CASE-TEST-1", "domain": "COMMERCE", "disposition": "APPROVE",
        "confidence": 0.4,  # below 0.6 -> must be overridden
        "findings": [
            {"claim": "First weak finding about account activity", "evidence_ids": [ev_id],
             "supports_fraud": False, "strength": "WEAK"},
            {"claim": "Second weak finding about account activity", "evidence_ids": [ev_id],
             "supports_fraud": False, "strength": "WEAK"},
        ],
        "policy_citations": [], "reasoning_summary": "z" * 60, "unresolved_questions": [],
    }
    out = escalation_gate_node(state)
    assert out["final_report"]["disposition"] == "ESCALATE_TO_HUMAN"
    assert "confidence below 0.6" in out["escalation_reasons"]


def test_escalation_gate_overrides_small_sample_size():
    ledger = EvidenceLedger()
    from sentinel.tools.impl import get_geo_risk
    get_geo_risk(ledger, address_id="ADDR-FARM-000-000")  # small n by construction of test data
    ev_id = ledger.all()[0].evidence_id
    state = _base_state(StubLLM([]))
    state["ledger"] = ledger
    state["final_report"] = {
        "case_id": "CASE-TEST-1", "domain": "COMMERCE", "disposition": "BLOCK",
        "confidence": 0.9,
        "findings": [
            {"claim": "Geo risk shows elevated fraud rate in this area", "evidence_ids": [ev_id],
             "supports_fraud": True, "strength": "STRONG"},
            {"claim": "Second supporting finding present here too", "evidence_ids": [ev_id],
             "supports_fraud": True, "strength": "MODERATE"},
        ],
        "policy_citations": [], "reasoning_summary": "z" * 60, "unresolved_questions": [],
    }
    sample_size = ledger.all()[0].raw_result.get("sample_size", 0)
    out = escalation_gate_node(state)
    if sample_size < 5:
        assert out["final_report"]["disposition"] == "ESCALATE_TO_HUMAN"
        assert any("sample_size" in r for r in out["escalation_reasons"])
