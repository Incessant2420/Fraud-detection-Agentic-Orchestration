---
id: POL-ESC-1.0
title: Escalation Criteria
category: Escalation
effective_date: 2025-01-01
---

# Escalation Criteria

Defines when a case must be routed to a human analyst rather than
resolved by automated disposition.

## Rule

A case must receive disposition `ESCALATE_TO_HUMAN` if any of the
following hold:

1. Overall confidence is below 0.60.
2. Fewer than 2 findings were produced.
3. All findings are of `WEAK` strength.
4. The evidence ledger contains a tool call that returned an error.
5. A geo or network finding rests on a `sample_size` below 5.
6. The investigating agent (automated or human) cannot resolve the case
   within its stated evidence budget and has one or more genuinely
   unresolved questions.

These criteria are intentionally deterministic and mechanically
checkable — escalation is a backstop that must not depend on a model's
self-assessed confidence being trustworthy.

## Rationale

The cost asymmetry between an unnecessary escalation (a human spends a
few minutes confirming a clear case) and a missed escalation (an
under-evidenced disposition ships as APPROVE or BLOCK) strongly favors
erring toward escalation whenever evidentiary support is thin. This is
especially important on evidence classes prone to small-sample noise
(see the `sample_size` requirement on all geo/network tools).

## Required Evidence

Any report reaching `ESCALATE_TO_HUMAN` must state, in
`unresolved_questions`, specifically what could not be determined —
"insufficient evidence" alone is not acceptable; state which question
went unanswered and why.

## Disposition Guidance

Escalation is not a failure state — it is the correct outcome whenever
the above criteria are met, and its recall on genuinely
under-evidenced cases is a primary system quality metric.
