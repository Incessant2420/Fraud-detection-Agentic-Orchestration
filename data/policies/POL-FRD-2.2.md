---
id: POL-FRD-2.2
title: Card Testing — Low-Value Probe Transactions
category: Fraud
effective_date: 2025-01-01
---

# Card Testing — Low-Value Probe Transactions

Governs detection of stolen-card validation via small "test" transactions
preceding a larger fraudulent charge.

## Rule

A sequence of 3 or more transactions under a low fixed value threshold,
followed within 24 hours by a transaction at least 10x that value on the
same account or card instrument, is classified a card-testing candidate.

## Rationale

Fraudsters validate stolen card numbers with small, often-declined
transactions before attempting a large purchase. The value-ratio signature
(many small probes, then one large charge) is more specific than velocity
alone and produces fewer false positives on legitimate high-frequency
small spenders.

## Required Evidence

1. Event history showing the specific transaction amounts and sequence.
2. Velocity features confirming the timing window.
3. Outcome field on the probe transactions (approved/declined mix is
   itself informative — an all-declined-then-one-approved pattern is a
   stronger signal than an all-approved pattern).

## Disposition Guidance

- Pattern confirmed with a >=10x value jump within 24h: `BLOCK` the large
  transaction pending verification; `ESCALATE_TO_HUMAN` if the account is
  also `UNVERIFIED` tenure (POL-FRD-2.4).
- Value jump present but ratio below 10x, or window exceeds 24h: treat as
  weak supporting evidence only.

## Exceptions

Subscription trials that upgrade to a paid tier can produce a similar
small-then-large pattern; check for matching merchant/product identifiers
consistent with a trial-to-paid conversion before treating this as
probative.
