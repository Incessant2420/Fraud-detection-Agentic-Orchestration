"""Pydantic v2 schemas — the enforcement layer. This is the heart of the
project: no Finding can cite evidence that doesn't exist in the ledger, no
ESCALATE_TO_HUMAN disposition can omit what's unresolved, and no
high-confidence disposition can rest on weak evidence alone.
"""
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class Disposition(str, Enum):
    APPROVE = "APPROVE"
    HOLD_PENDING_VERIFICATION = "HOLD_PENDING_VERIFICATION"
    BLOCK = "BLOCK"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"


class ToolCallRecord(BaseModel):
    evidence_id: str            # "EV-003"
    tool_name: str
    arguments: dict
    result_digest: str          # <= 80 tokens, deterministic, THIS is what the LLM sees
    raw_result: dict            # full payload; judge + UI only, never in a prompt
    latency_ms: int
    called_at: str


class Finding(BaseModel):
    claim: str = Field(..., min_length=10)
    evidence_ids: list[str] = Field(..., min_length=1)   # HARD REQUIREMENT
    supports_fraud: bool
    strength: Literal["WEAK", "MODERATE", "STRONG"]


class PolicyCitation(BaseModel):
    policy_id: str
    excerpt: str
    relevance: str


class CaseReport(BaseModel):
    case_id: str
    domain: Literal["BANK", "COMMERCE"]
    disposition: Disposition
    confidence: float = Field(..., ge=0.0, le=1.0)
    findings: list[Finding] = Field(..., min_length=1)
    policy_citations: list[PolicyCitation]
    reasoning_summary: str = Field(..., min_length=50)
    unresolved_questions: list[str]
    evidence_ledger: list[ToolCallRecord]

    @model_validator(mode="after")
    def all_evidence_ids_must_exist(self):
        ledger_ids = {e.evidence_id for e in self.evidence_ledger}
        for f in self.findings:
            missing = set(f.evidence_ids) - ledger_ids
            if missing:
                raise ValueError(f"Finding cites non-existent evidence: {missing}")
        return self

    @model_validator(mode="after")
    def escalation_requires_open_questions(self):
        if self.disposition == Disposition.ESCALATE_TO_HUMAN and not self.unresolved_questions:
            raise ValueError("Escalation must state what is unresolved.")
        return self

    @model_validator(mode="after")
    def high_confidence_requires_strong_evidence(self):
        if self.confidence > 0.85 and not any(f.strength == "STRONG" for f in self.findings):
            raise ValueError("Confidence > 0.85 requires >= 1 STRONG finding.")
        return self


# --- Failure-handling pipeline bookkeeping -----------------------------
# Every attempt at producing a CaseReport is logged at each stage. These
# counts (uncited-claim rate, JSON-repair rescue rate, retry rescue rate,
# forced-escalation rate) are the project's headline metrics, not
# incidental logging.

class GenerationAttemptLog(BaseModel):
    case_id: str
    attempt_number: int                      # 1, 2, 3 (max 2 retries -> 3 attempts)
    raw_output: str
    json_repair_applied: bool
    json_repair_succeeded: Optional[bool] = None
    pydantic_valid: bool
    validation_errors: list[str] = Field(default_factory=list)
    had_uncited_claim: bool                  # true if this was the specific failure mode
    forced_escalation: bool = False
