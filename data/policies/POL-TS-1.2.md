---
id: POL-TS-1.2
title: Refund and Chargeback Abuse Rate
category: Trust & Safety
effective_date: 2025-01-01
---

# Refund and Chargeback Abuse Rate

Governs review of accounts with a personal refund/chargeback rate
significantly above the platform baseline.

## Rule

An account with a refund-claim rate exceeding 25% over its last 20 or more
orders (versus a platform baseline of approximately 5-8%) is classified a
refund-abuse candidate, provided the sample size (order count) is at least
10.

## Rationale

A small number of legitimate refunds is normal and expected; a
persistently elevated personal rate across a meaningful order history is a
much stronger signal than any single refund claim and correlates with
"free-item" abuse patterns (repeatedly claiming non-delivery or item
defects for items actually received).

## Required Evidence

1. Event history with refund/claim outcomes and total order count
   (sample_size).
2. Comparison against platform baseline refund rate.
3. Whether refund claims cluster around a specific courier (see
   POL-TS-1.3) or are diffuse across many couriers/merchants (diffuse
   patterns are more clearly attributable to the account itself).

## Disposition Guidance

- Refund rate >= 25% with sample_size >= 10 and diffuse courier
  attribution: `HOLD_PENDING_VERIFICATION`; `ESCALATE_TO_HUMAN` if rate
  exceeds 40%.
- Sample size < 10: insufficient evidence — do not cite this policy as a
  primary finding; note the small sample explicitly if mentioned at all.

## Exceptions

Categories with genuinely higher baseline refund/damage rates (fragile
goods, perishables) should be compared against a category-adjusted
baseline where available, not the platform-wide baseline.
