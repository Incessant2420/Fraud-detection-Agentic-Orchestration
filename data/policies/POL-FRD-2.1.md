---
id: POL-FRD-2.1
title: Card-Not-Present Velocity Thresholds
category: Fraud
effective_date: 2025-01-01
---

# Card-Not-Present (CNP) Velocity Thresholds

Governs review triggers for rapid-succession card-not-present transaction
activity, a common signature of stolen-card testing and account takeover.

## Rule

A user exceeding **8 transactions in a 1-hour window**, or **20
transactions in a 24-hour window**, on card-not-present channels triggers
mandatory review. The threshold applies to raw counts regardless of
individual transaction outcome (approved or declined).

## Rationale

Legitimate consumer purchasing rarely produces double-digit transaction
counts in a single hour. Card testing operations (validating stolen card
numbers via small purchases) and account-takeover cash-out attempts both
produce sharp, short-duration velocity spikes. Velocity, not any single
transaction's size, is the signal.

## Required Evidence

1. Velocity features for the 1h and 24h windows, including population
   percentile — a user at the 99.9th percentile is far more notable than
   one merely above the raw count threshold in a low-activity population.
2. Event history confirming transaction count and timing.
3. Note whether transactions are of near-identical small amounts
   (consistent with card testing) versus varied amounts.

## Disposition Guidance

- Velocity threshold exceeded with population percentile >= 0.99:
  `BLOCK` or `ESCALATE_TO_HUMAN` pending further identity verification.
- Threshold exceeded but percentile is unremarkable for this user segment
  (e.g., a known high-volume merchant account): treat as weak evidence
  only, and prefer `HOLD_PENDING_VERIFICATION`.

## Exceptions

Merchant/business accounts and bill-pay aggregators may legitimately
exceed these thresholds; check account type and historical baseline
before treating velocity alone as sufficient grounds for BLOCK.
