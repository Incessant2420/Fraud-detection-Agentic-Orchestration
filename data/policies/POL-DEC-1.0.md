---
id: POL-DEC-1.0
title: Disposition Definitions
category: Decisioning
effective_date: 2025-01-01
---

# Disposition Definitions

Defines the four case dispositions used across both the bank/AML and
commerce/trust-and-safety arms of the platform.

## APPROVE

The case shows no material fraud/abuse signal, or all superficially
concerning signals have a well-evidenced legitimate explanation (e.g., a
carve-out under POL-TS-2.2). Confidence should typically be high, and if
confidence exceeds 0.85 at least one STRONG supporting finding must be
present to justify that certainty.

## HOLD_PENDING_VERIFICATION

The case shows a moderate signal that warrants additional verification
(e.g., contacting the account holder, requesting identity documents)
before further action, but does not yet meet the bar for BLOCK. This is
the correct disposition when evidence is suggestive but not conclusive,
and when sample sizes are borderline (see POL-ESC-1.0's sample_size < 5
rule, which forces escalation rather than a HOLD in the most severe
small-sample cases).

## BLOCK

The case shows clear, well-evidenced fraud/abuse per one or more of the
specific policies (POL-AML-4.2, POL-AML-4.3, POL-FRD-2.1, POL-TS-1.1,
POL-TS-1.3, POL-TS-2.2) with at least one STRONG finding and no
unaddressed contradicting evidence.

## ESCALATE_TO_HUMAN

The case cannot be safely resolved by automated disposition per the
criteria in POL-ESC-1.0. This is distinct from BLOCK: escalation means
"a human must decide," not "this is fraud."

## Confidence Calibration

Confidence should reflect the strength and independence of supporting
evidence, not merely the number of findings. A single STRONG,
well-corroborated finding can justify higher confidence than several WEAK
findings pointing the same direction. Confidence above 0.85 is reserved
for cases with unambiguous, policy-matched STRONG evidence.

## Required Evidence

Every disposition must be traceable to specific cited findings and, where
applicable, specific policy IDs — a disposition with no policy citation
should be rare and is itself worth flagging as an unresolved question.
