---
id: POL-AML-4.3
title: Structuring — Sub-Threshold Transaction Patterns
category: AML
effective_date: 2025-01-01
---

# Structuring — Sub-Threshold Transaction Patterns

This policy addresses "structuring": deliberately splitting transactions
into amounts just under a reporting or velocity threshold to avoid
detection.

## Rule

A cluster of three (3) or more transactions from the same user within a
24-hour window, each individually below the platform's single-transaction
review threshold but summing above it, must be flagged as a structuring
candidate.

## Rationale

Structuring is a classic evasion pattern for both money-laundering
(avoiding currency transaction reporting) and card-fraud testing
(splitting a large purchase into several smaller ones that individually
evade velocity rules). The signature is not any single transaction but the
pattern across several.

## Required Evidence

1. Event history for the user showing the individual transaction amounts
   and timestamps.
2. Velocity features (24h window) showing count and summed amount.
3. Confirmation the summed amount exceeds, and each individual transaction
   is below, the single-transaction review threshold.

## Disposition Guidance

- Confirmed structuring pattern with clean evidence:
  `HOLD_PENDING_VERIFICATION` at minimum; `ESCALATE_TO_HUMAN` if paired
  with a new/unverified account (see POL-FRD-2.4).
- A single below-threshold transaction is not evidence of structuring on
  its own and must not be cited as such.

## Exceptions

Recurring legitimate billing (subscriptions, installment plans) can
produce multiple same-day small transactions; check for round, repeating
amounts consistent with billing schedules before escalating.
