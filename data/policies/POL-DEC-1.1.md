---
id: POL-DEC-1.1
title: Evidence Sufficiency and Insufficient-Evidence Handling
category: Decisioning
effective_date: 2025-01-01
---

# Evidence Sufficiency and Insufficient-Evidence Handling

Defines the standard for concluding that available evidence is
insufficient to support any disposition other than escalation, and how
that conclusion must be documented.

## Rule

A case has insufficient evidence when tool queries return empty results,
truncated history (e.g., a newly created account with minimal event
history), or when all available findings are `WEAK` strength. Insufficient
evidence is a valid and expected conclusion, not a system failure, and
must route to `ESCALATE_TO_HUMAN` per POL-ESC-1.0.

## Rationale

A system that always produces a confident disposition regardless of
evidence quality is more dangerous than one that correctly recognizes and
reports the limits of what it was able to retrieve. Explicitly modeling
"insufficient evidence" as a first-class outcome, rather than forcing a
best-guess disposition, is core to this system's auditability guarantee.

## Required Evidence

A report citing insufficient evidence must still include:
1. Which tools were called and what they returned (even if empty).
2. Specifically what additional evidence, if it existed, would have
   resolved the case (stated in `unresolved_questions`).

## Disposition Guidance

Insufficient evidence always routes to `ESCALATE_TO_HUMAN`, never to
`APPROVE` — the absence of evidence of fraud is not evidence of absence,
and defaulting to APPROVE under uncertainty would silently erode the
system's safety guarantees.

## Exceptions

None — this is a hard rule, mirrored by the deterministic
`escalation_gate` node, which does not depend on the LLM correctly
applying this policy on its own.
