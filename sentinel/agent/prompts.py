import json

from sentinel.tools.registry import all_tool_schemas


def _valid_names_block() -> str:
    names = ", ".join(f'"{s["name"]}"' for s in all_tool_schemas())
    return f"VALID tool_name VALUES -- you MUST use one of these EXACT strings, nothing else: {names}"


def executor_first_prompt(case_context: dict) -> str:
    tools = json.dumps(all_tool_schemas(), indent=2)
    return f"""You are a fraud/trust-and-safety investigation agent. You must decide what
evidence to gather before anyone can write a case report. You do NOT decide guilt yourself.

CASE CONTEXT:
{json.dumps(case_context, indent=2, default=str)}

{_valid_names_block()}

AVAILABLE TOOLS (facts only, no tool ever tells you "suspicious" -- you must reason):
{tools}

Respond with ONLY a JSON object of this exact shape:
{{
  "plan": ["question 1", "question 2", "... 3-5 investigative questions"],
  "tool_calls": [{{"tool_name": "...", "arguments": {{...}}}}, ... up to 3 calls]
}}

tool_name MUST be copied EXACTLY from the VALID tool_name VALUES list above -- do not
invent, abbreviate, or rename a tool. Pick tool_calls that address your plan's first
questions. user_id for tool calls is case_context.user_id unless a question needs a
different id (e.g. an address_id discovered from a prior tool result)."""


def executor_next_prompt(case_context: dict, plan: list[str], ledger_digests: list[dict],
                          calls_remaining: int) -> str:
    return f"""You are continuing a fraud investigation. Original plan:
{json.dumps(plan, indent=2)}

Evidence gathered so far (evidence_id: tool: digest):
{json.dumps(ledger_digests, indent=2, default=str)}

You have {calls_remaining} tool calls left in this investigation's budget.

{_valid_names_block()}

AVAILABLE TOOLS:
{json.dumps(all_tool_schemas(), indent=2)}

If a result was surprising (e.g. a much larger or smaller cluster/velocity than
expected), you may ADD a new question to the plan to follow up on it.

Respond with ONLY a JSON object:
{{
  "done": true or false,
  "new_questions": ["...any follow-up questions spawned by a surprising result, else []"],
  "tool_calls": [{{"tool_name": "...", "arguments": {{...}}}}, ... up to {calls_remaining} calls]
}}

tool_name MUST be copied EXACTLY from the VALID tool_name VALUES list above. Set "done":
true only when your plan's questions are addressed or no further tool call would add new
information. If done, tool_calls should be []."""


def synthesizer_prompt(case_context: dict, plan: list[str], ledger_digests: list[dict],
                        prior_error: str | None = None) -> str:
    error_block = ""
    if prior_error:
        error_block = f"""
YOUR PREVIOUS ATTEMPT WAS REJECTED. Fix this specific problem:
{prior_error}
"""
    return f"""You are the synthesizer for a fraud/trust-and-safety investigation. Produce a
final case report as a JSON object. This report will be schema-validated: EVERY finding
MUST cite at least one evidence_id that appears in the evidence ledger below. You may
NOT assert anything you did not retrieve via a tool call. Tools return facts, not
judgements -- you supply the reasoning about what those facts mean.

CASE CONTEXT:
{json.dumps(case_context, indent=2, default=str)}

INVESTIGATIVE PLAN:
{json.dumps(plan, indent=2)}

EVIDENCE LEDGER (evidence_id: tool: digest -- this is ALL the evidence that exists):
{json.dumps(ledger_digests, indent=2, default=str)}
{error_block}
Respond with ONLY a JSON object of this exact shape (do not include an evidence_ledger
field -- it will be attached automatically from the real ledger above):
{{
  "case_id": "{case_context.get('case_id', '')}",
  "domain": "{case_context.get('domain', '')}",
  "disposition": "APPROVE" | "HOLD_PENDING_VERIFICATION" | "BLOCK" | "ESCALATE_TO_HUMAN",
  "confidence": 0.0-1.0,
  "findings": [
    {{"claim": "...", "evidence_ids": ["EV-001"], "supports_fraud": true/false, "strength": "WEAK"|"MODERATE"|"STRONG"}}
  ],
  "policy_citations": [{{"policy_id": "...", "excerpt": "...", "relevance": "..."}}],
  "reasoning_summary": "at least 50 characters explaining the disposition",
  "unresolved_questions": ["..."]
}}

Rules: confidence > 0.85 requires at least one STRONG finding. ESCALATE_TO_HUMAN requires
at least one unresolved_question. Every evidence_id you cite MUST appear in the ledger
above -- citing anything else will cause automatic rejection."""


def critic_prompt(draft_report: dict, cited_evidence: dict) -> str:
    return f"""You are an adversarial reviewer for a fraud-investigation case report. You are
a DIFFERENT model from the one that wrote this draft -- your job is to catch what it
missed or overstated. Do not be polite; be skeptical.

DRAFT REPORT:
{json.dumps(draft_report, indent=2, default=str)}

FULL EVIDENCE PAYLOADS FOR EACH CITED evidence_id (the draft's findings must actually be
supported by these, not just superficially reference them):
{json.dumps(cited_evidence, indent=2, default=str)}

Check specifically for:
1. Any finding whose claim is NOT actually supported by its cited evidence's raw data.
2. Any evidence in the ledger that CONTRADICTS a finding, which the draft ignored.
3. Whether the stated confidence is justified by the evidence strength (e.g. sample_size
   traps -- a 100% rate on n<5 should not justify high confidence).

Respond with ONLY a JSON object:
{{
  "unsupported_claims": ["claim text ... reason it is not supported, for each problem found"],
  "ignored_contradictions": ["..."],
  "confidence_justified": true/false,
  "route_back": true/false
}}

Set "route_back": true if there is at least one unsupported claim, one ignored
contradiction, or an unjustified confidence level."""
