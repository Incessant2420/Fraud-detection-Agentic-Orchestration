"""LangGraph state machine: executor -> synthesizer -> (critic?) -> validator
-> (synthesizer | escalation_gate) -> END.

A bare ReAct loop was explicitly rejected in the spec: this graph gives us
controllability (bounded retries, forced escalation, a conditional critic
on a *different* model) that a single-prompt loop cannot guarantee.
"""
import difflib
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, END

from sentinel.agent.prompts import executor_first_prompt, executor_next_prompt, \
    synthesizer_prompt, critic_prompt
from sentinel.budget import TokenBudgetTracker
from sentinel.cache import ResponseCache
from sentinel.llm import LLMRouter, safe_json_loads
from sentinel.schemas import CaseReport, Disposition, GenerationAttemptLog
from sentinel.tools.registry import EvidenceLedger, get_tool, all_tool_schemas
import sentinel.tools.impl  # noqa: F401 -- registers all @tool-decorated functions;
# without this import, all_tool_schemas() silently returns [] until something
# else happens to import sentinel.tools.impl first (a real bug found live:
# the executor prompt's tool list was empty, so EVERY hallucinated tool name
# was actually a guess with zero grounding, not a misread of a real list).

MAX_TOOL_CALLS = 6
MAX_SYNTH_RETRIES = 2       # validator retries
MAX_CRITIC_LOOPS = 2

CRITIC_TRIGGER_CONFIDENCE = 0.7


class AgentState(TypedDict, total=False):
    case_id: str
    domain: str
    case_context: dict
    plan: list
    ledger: EvidenceLedger
    draft_report: Optional[dict]
    critique: Optional[str]
    retry_count: int
    critic_loop_count: int
    validation_errors: list
    tokens_used: dict
    generation_log: list
    llm: LLMRouter
    final_report: Optional[dict]
    escalation_reasons: list
    critic_triggered: bool
    tool_name_repairs: list


def _known_tool_names() -> list[str]:
    # Computed fresh each call rather than cached at import time -- the
    # earlier module-level-constant version silently returned [] whenever
    # this module happened to import before sentinel.tools.impl registered
    # its @tool functions, which is exactly what happened in the first live
    # batch eval run (see the explicit import above for the primary fix;
    # this is defense in depth against the same class of bug recurring).
    return [s["name"] for s in all_tool_schemas()]


def _resolve_tool_name(name: str | None) -> tuple[str | None, bool]:
    """Returns (resolved_name, was_fuzzy_repaired). Smaller open-weights
    models sometimes invent a plausible-but-wrong tool name (e.g.
    "account_history" instead of "get_event_history"); rather than
    silently starving the investigation of evidence, we fuzzy-match
    against the known tool registry -- mirroring the JSON-repair layer's
    philosophy, and logged the same way so the rescue rate is measurable."""
    if not name:
        return None, False
    if name in _known_tool_names():
        return name, False
    # Case-insensitive: the executor model frequently invents names in
    # SCREAMING_SNAKE_CASE (e.g. "GET_USER_ACCOUNT_HISTORY"); difflib's
    # SequenceMatcher is case-sensitive, so without lowercasing first,
    # every one of those was silently un-matchable and evidence-starving
    # the whole investigation (a real bug found via live batch runs).
    match = difflib.get_close_matches(name.lower(), _known_tool_names(), n=1, cutoff=0.45)
    if match:
        return match[0], True
    return None, False


def _dispatch_tool_calls(ledger: EvidenceLedger, tool_calls: list[dict],
                          repair_log: list | None = None) -> list[dict]:
    executed = []
    for tc in tool_calls:
        raw_name = tc.get("tool_name")
        args = tc.get("arguments", {}) or {}
        name, was_repaired = _resolve_tool_name(raw_name)
        if was_repaired and repair_log is not None:
            repair_log.append({"raw_name": raw_name, "resolved_name": name})
        if name is None:
            continue
        try:
            fn = get_tool(name)
        except KeyError:
            continue
        try:
            fn(ledger, **args)
            executed.append(tc)
        except Exception as e:
            # Log a synthetic error record so the escalation gate's
            # "ledger contains a tool error" check can see it.
            from sentinel.schemas import ToolCallRecord
            from datetime import datetime, timezone
            eid = ledger.next_evidence_id()
            ledger.add(ToolCallRecord(
                evidence_id=eid, tool_name=name or "unknown", arguments=args,
                result_digest=f"tool error: {str(e)[:60]}", raw_result={"error": str(e)},
                latency_ms=0, called_at=datetime.now(timezone.utc).isoformat(),
            ))
    return executed


def executor_node(state: AgentState) -> dict:
    llm: LLMRouter = state["llm"]
    ledger = state["ledger"]
    case_context = state["case_context"]

    repairs: list = []
    prompt = executor_first_prompt(case_context)
    resp = llm.call("executor", prompt, case_id=state["case_id"])
    parsed, repaired, err = safe_json_loads(resp["content"])
    plan = (parsed or {}).get("plan", []) or ["Investigate the flagged case."]
    tool_calls = (parsed or {}).get("tool_calls", []) if parsed else []

    n_calls = 0
    n_calls += len(_dispatch_tool_calls(ledger, tool_calls[:MAX_TOOL_CALLS], repair_log=repairs))

    stale_rounds = 0
    while n_calls < MAX_TOOL_CALLS and stale_rounds < 2:
        remaining = MAX_TOOL_CALLS - n_calls
        prompt = executor_next_prompt(case_context, plan, ledger.digests_for_prompt(), remaining)
        resp = llm.call("executor", prompt, case_id=state["case_id"])
        parsed, repaired, err = safe_json_loads(resp["content"])
        if not parsed:
            stale_rounds += 1
            continue
        plan = plan + (parsed.get("new_questions") or [])
        if parsed.get("done") or not parsed.get("tool_calls"):
            break
        executed = _dispatch_tool_calls(ledger, parsed["tool_calls"][:remaining], repair_log=repairs)
        if not executed:
            stale_rounds += 1
            continue
        stale_rounds = 0
        n_calls += len(executed)

    # Deterministic fallback: if the model never managed a single successful
    # tool call (repeated hallucinated names beyond repair), bootstrap with
    # the one tool guaranteed to apply to any case so the investigation is
    # never evidence-free by construction.
    if not ledger.all():
        from sentinel.tools.impl import get_entity_profile
        get_entity_profile(ledger, user_id=case_context["user_id"])

    return {"plan": plan, "ledger": ledger, "tool_name_repairs": repairs}


def synthesizer_node(state: AgentState) -> dict:
    llm: LLMRouter = state["llm"]
    ledger = state["ledger"]
    prior_error = None
    if state.get("validation_errors"):
        prior_error = "; ".join(state["validation_errors"])
    elif state.get("critique"):
        prior_error = state["critique"]

    prompt = synthesizer_prompt(state["case_context"], state.get("plan", []),
                                 ledger.digests_for_prompt(), prior_error=prior_error)
    resp = llm.call("synthesizer", prompt, case_id=state["case_id"])
    parsed, repaired, err = safe_json_loads(resp["content"])

    log = state.get("generation_log", [])
    attempt_n = state.get("retry_count", 0) + 1
    had_uncited = False
    if parsed:
        ledger_ids = {r.evidence_id for r in ledger.all()}
        for f in parsed.get("findings", []):
            if set(f.get("evidence_ids", [])) - ledger_ids:
                had_uncited = True
                break
    log.append(GenerationAttemptLog(
        case_id=state["case_id"], attempt_number=attempt_n, raw_output=resp["content"][:2000],
        json_repair_applied=repaired, json_repair_succeeded=(parsed is not None) if repaired else None,
        pydantic_valid=False,  # validator node determines this
        had_uncited_claim=had_uncited,
    ).model_dump())

    return {"draft_report": parsed, "generation_log": log, "critique": None}


def _needs_critic(draft: dict) -> bool:
    if not draft:
        return False
    if draft.get("confidence", 0) > CRITIC_TRIGGER_CONFIDENCE:
        return True
    supports = {f.get("supports_fraud") for f in draft.get("findings", [])}
    return len(supports) > 1


def critic_node(state: AgentState) -> dict:
    llm: LLMRouter = state["llm"]
    ledger = state["ledger"]
    draft = state["draft_report"]

    cited_ids = set()
    for f in (draft or {}).get("findings", []):
        cited_ids.update(f.get("evidence_ids", []))
    cited_evidence = {r.evidence_id: r.raw_result for r in ledger.all() if r.evidence_id in cited_ids}

    prompt = critic_prompt(draft, cited_evidence)
    resp = llm.call("critic", prompt, case_id=state["case_id"])
    parsed, _, _ = safe_json_loads(resp["content"])
    route_back = bool(parsed and parsed.get("route_back"))

    critique_text = ""
    if parsed:
        if parsed.get("unsupported_claims"):
            critique_text += "Unsupported claims: " + "; ".join(parsed["unsupported_claims"]) + ". "
        if parsed.get("ignored_contradictions"):
            critique_text += "Ignored contradicting evidence: " + "; ".join(parsed["ignored_contradictions"]) + ". "
        if parsed.get("confidence_justified") is False:
            critique_text += "Confidence level is not justified by evidence strength."

    return {
        "critique": critique_text if route_back else None,
        "critic_loop_count": state.get("critic_loop_count", 0) + 1,
        "_critic_route_back": route_back,
    }


def validator_node(state: AgentState) -> dict:
    ledger = state["ledger"]
    draft = state["draft_report"]
    log = state.get("generation_log", [])

    if draft is None:
        errors = ["No parseable JSON produced by synthesizer."]
        if log:
            log[-1]["pydantic_valid"] = False
            log[-1]["validation_errors"] = errors
        return {"validation_errors": errors, "final_report": None,
                "retry_count": state.get("retry_count", 0) + 1, "generation_log": log}

    payload = dict(draft)
    payload["evidence_ledger"] = [r.model_dump() for r in ledger.all()]
    try:
        report = CaseReport(**payload)
        if log:
            log[-1]["pydantic_valid"] = True
        return {"final_report": report.model_dump(), "validation_errors": [], "generation_log": log}
    except Exception as e:
        errors = [str(e)]
        if log:
            log[-1]["pydantic_valid"] = False
            log[-1]["validation_errors"] = errors
        return {"validation_errors": errors, "final_report": None,
                "retry_count": state.get("retry_count", 0) + 1, "generation_log": log}


def _force_escalation_report(state: AgentState) -> dict:
    ledger = state["ledger"]
    records = ledger.all()
    error_text = "; ".join(state.get("validation_errors", [])) or "Generation failed validation after retries."
    evidence_ids = [records[0].evidence_id] if records else []
    findings = [{
        "claim": "Automated report synthesis failed schema validation after retries.",
        "evidence_ids": evidence_ids or ["EV-000"],
        "supports_fraud": False, "strength": "WEAK",
    }] if evidence_ids else []
    if not findings:
        # No tool calls ever succeeded -- synthesize a placeholder ledger entry so
        # the CaseReport's own evidence-must-exist invariant still holds.
        from sentinel.schemas import ToolCallRecord
        from datetime import datetime, timezone
        eid = ledger.next_evidence_id()
        ledger.add(ToolCallRecord(
            evidence_id=eid, tool_name="none", arguments={},
            result_digest="no successful tool calls", raw_result={"error": "no evidence gathered"},
            latency_ms=0, called_at=datetime.now(timezone.utc).isoformat(),
        ))
        findings = [{
            "claim": "No evidence could be gathered or synthesis failed after retries.",
            "evidence_ids": [eid], "supports_fraud": False, "strength": "WEAK",
        }]

    payload = {
        "case_id": state["case_id"], "domain": state["domain"],
        "disposition": Disposition.ESCALATE_TO_HUMAN, "confidence": 0.0,
        "findings": findings, "policy_citations": [],
        "reasoning_summary": f"Forced escalation: {error_text[:300]}",
        "unresolved_questions": [error_text[:500]],
        "evidence_ledger": [r.model_dump() for r in ledger.all()],
    }
    report = CaseReport(**payload)
    log = state.get("generation_log", [])
    if log:
        log[-1]["forced_escalation"] = True
    return {"final_report": report.model_dump(), "generation_log": log}


def escalation_gate_node(state: AgentState) -> dict:
    if state.get("final_report") is None:
        return _force_escalation_report(state)

    report = state["final_report"]
    ledger = state["ledger"]
    reasons = []

    if report["confidence"] < 0.6:
        reasons.append("confidence below 0.6")
    if len(report["findings"]) < 2:
        reasons.append("fewer than 2 findings")
    if report["findings"] and all(f["strength"] == "WEAK" for f in report["findings"]):
        reasons.append("all findings WEAK")
    if ledger.has_tool_error():
        reasons.append("ledger contains a tool error")
    for r in ledger.all():
        if r.raw_result.get("sample_size") is not None and r.raw_result["sample_size"] < 5 \
                and r.tool_name in ("get_geo_risk", "get_shared_entity_network"):
            reasons.append(f"{r.tool_name} ({r.evidence_id}) rests on sample_size < 5")

    if reasons and report["disposition"] != Disposition.ESCALATE_TO_HUMAN.value:
        report = dict(report)
        report["disposition"] = Disposition.ESCALATE_TO_HUMAN.value
        report["unresolved_questions"] = list(report["unresolved_questions"]) + [
            f"Deterministic escalation gate override: {r}" for r in reasons
        ]
        # Source evidence_ledger from the real ledger object rather than
        # trusting it survived in `report` -- the gate must be authoritative
        # on its own, not dependent on upstream nodes having populated it.
        report["evidence_ledger"] = [r.model_dump() for r in ledger.all()]
        # re-validate through the schema to keep the enforcement layer authoritative
        validated = CaseReport(**report)
        report = validated.model_dump()

    return {"final_report": report, "escalation_reasons": reasons}


def _route_after_synthesizer(state: AgentState) -> str:
    if _needs_critic(state.get("draft_report")):
        return "critic"
    return "validator"


def _route_after_critic(state: AgentState) -> str:
    if state.get("_critic_route_back") and state.get("critic_loop_count", 0) < MAX_CRITIC_LOOPS:
        return "synthesizer"
    return "validator"


def _route_after_validator(state: AgentState) -> str:
    if state.get("final_report") is not None:
        return "escalation_gate"
    if state.get("retry_count", 0) <= MAX_SYNTH_RETRIES:
        return "synthesizer"
    return "escalation_gate"  # forced escalation -- final_report is None, gate builds it


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("executor", executor_node)
    g.add_node("synthesizer", synthesizer_node)
    g.add_node("critic", critic_node)
    g.add_node("validator", validator_node)
    g.add_node("escalation_gate", escalation_gate_node)

    g.set_entry_point("executor")
    g.add_edge("executor", "synthesizer")
    g.add_conditional_edges("synthesizer", _route_after_synthesizer,
                             {"critic": "critic", "validator": "validator"})
    g.add_conditional_edges("critic", _route_after_critic,
                             {"synthesizer": "synthesizer", "validator": "validator"})
    g.add_conditional_edges("validator", _route_after_validator,
                             {"synthesizer": "synthesizer", "escalation_gate": "escalation_gate"})
    g.add_edge("escalation_gate", END)
    return g.compile()


def run_case(case_context: dict, llm: LLMRouter) -> dict:
    graph = build_graph()
    init_state: AgentState = {
        "case_id": case_context["case_id"],
        "domain": case_context["domain"],
        "case_context": case_context,
        "plan": [],
        "ledger": EvidenceLedger(),
        "draft_report": None,
        "critique": None,
        "retry_count": 0,
        "critic_loop_count": 0,
        "validation_errors": [],
        "generation_log": [],
        "llm": llm,
        "final_report": None,
        "tool_name_repairs": [],
    }
    result = graph.invoke(init_state, config={"recursion_limit": 50})
    return {
        "final_report": result["final_report"],
        "generation_log": result.get("generation_log", []),
        "escalation_reasons": result.get("escalation_reasons", []),
        "tool_name_repairs": result.get("tool_name_repairs", []),
        "critic_triggered": result.get("critic_loop_count", 0) > 0,
        "n_tool_calls": len(result["ledger"].all()),
    }


def run_case_single_shot(case_context: dict, llm: LLMRouter) -> dict:
    """Ablation: single-shot baseline. One prompt, all tools 'available' in
    the sense that the model is told about them, no LangGraph state machine,
    no critic, no validator, no retries -- the model must call tools and
    write the final report in one shot. This is what a naive ReAct-less
    implementation looks like, and is the ablation the whole architecture
    is meant to beat."""
    import json as _json
    from sentinel.tools.registry import all_tool_schemas
    from sentinel.llm import safe_json_loads

    ledger = EvidenceLedger()
    tools_desc = _json.dumps(all_tool_schemas(), indent=2)
    prompt = f"""You are a fraud investigation agent. Investigate this case and produce a
final case report in ONE response. You may reference tool results if you had called
tools, but no tools have actually been called -- reason only from the case context below.

CASE CONTEXT:
{_json.dumps(case_context, indent=2, default=str)}

TOOLS THAT EXIST ON THIS PLATFORM (for your awareness only -- you cannot call them):
{tools_desc}

Respond with ONLY a JSON CaseReport object with fields: case_id, domain, disposition
(APPROVE|HOLD_PENDING_VERIFICATION|BLOCK|ESCALATE_TO_HUMAN), confidence (0-1), findings
(list of {{claim, evidence_ids, supports_fraud, strength}}), policy_citations, reasoning_summary
(>=50 chars), unresolved_questions, evidence_ledger (list of {{evidence_id, tool_name,
arguments, result_digest, raw_result, latency_ms, called_at}} -- since you made no real
tool calls, invent plausible evidence_ledger entries consistent with your findings)."""

    resp = llm.call("synthesizer", prompt, case_id=case_context["case_id"])
    parsed, repaired, err = safe_json_loads(resp["content"])

    log = [GenerationAttemptLog(
        case_id=case_context["case_id"], attempt_number=1, raw_output=resp["content"][:2000],
        json_repair_applied=repaired, json_repair_succeeded=(parsed is not None) if repaired else None,
        pydantic_valid=False, had_uncited_claim=False,
    ).model_dump()]

    final_report = None
    if parsed:
        try:
            report = CaseReport(**parsed)
            final_report = report.model_dump()
            log[0]["pydantic_valid"] = True
        except Exception as e:
            log[0]["validation_errors"] = [str(e)]

    return {
        "final_report": final_report, "generation_log": log,
        "escalation_reasons": [], "tool_name_repairs": [],
        "critic_triggered": False, "n_tool_calls": 0,
    }


def run_case_no_critic(case_context: dict, llm: LLMRouter) -> dict:
    """Ablation: full graph minus the critic node (skip straight from
    synthesizer to validator regardless of confidence/conflict)."""
    graph = _build_graph_no_critic()
    init_state: AgentState = {
        "case_id": case_context["case_id"], "domain": case_context["domain"],
        "case_context": case_context, "plan": [], "ledger": EvidenceLedger(),
        "draft_report": None, "critique": None, "retry_count": 0, "critic_loop_count": 0,
        "validation_errors": [], "generation_log": [], "llm": llm, "final_report": None,
        "tool_name_repairs": [],
    }
    result = graph.invoke(init_state, config={"recursion_limit": 50})
    return {
        "final_report": result["final_report"], "generation_log": result.get("generation_log", []),
        "escalation_reasons": result.get("escalation_reasons", []),
        "tool_name_repairs": result.get("tool_name_repairs", []),
        "critic_triggered": False, "n_tool_calls": len(result["ledger"].all()),
    }


def _build_graph_no_critic():
    g = StateGraph(AgentState)
    g.add_node("executor", executor_node)
    g.add_node("synthesizer", synthesizer_node)
    g.add_node("validator", validator_node)
    g.add_node("escalation_gate", escalation_gate_node)
    g.set_entry_point("executor")
    g.add_edge("executor", "synthesizer")
    g.add_edge("synthesizer", "validator")
    g.add_conditional_edges("validator", _route_after_validator,
                             {"synthesizer": "synthesizer", "escalation_gate": "escalation_gate"})
    g.add_edge("escalation_gate", END)
    return g.compile()
