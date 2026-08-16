---
id: POL-TS-1.3
title: Courier-Customer Collusion
category: Trust & Safety
effective_date: 2025-01-01
---

# Courier-Customer Collusion

Governs detection of collusive "item missing" or "item not delivered"
refund claims between a customer and a specific courier/delivery partner.

## Rule

A customer-courier pair with 6 or more shared deliveries, where the
`item_missing` claim rate on that pair exceeds 35% (versus a platform
baseline of approximately 3%), and deliveries cluster in a tight
geography, is classified a `COLLUSION` candidate.

## Rationale

A single courier repeatedly assigned to the same customer, with an
anomalously high rate of "item missing" claims relative to platform
baseline, is a recognized collusion pattern: the courier keeps the item
and the customer claims a refund, splitting the proceeds. Isolated missing
claims are normal service failures; the signal here is the concentration
of claims on one specific pairing.

## Required Evidence

1. Event history for the customer showing claim outcomes per courier.
2. The pair's claim rate versus platform baseline claim rate, with sample
   size (pair order count) — a 100% claim rate on 2 orders is not
   evidence; this pattern requires n >= 6 to be actionable.
3. Geographic clustering of the affected deliveries.

## Disposition Guidance

- Pair claim rate >= 35% with n >= 6 and tight geo clustering:
  `ESCALATE_TO_HUMAN` for manual courier/customer account review.
- Elevated but sub-threshold claim rate, or n < 6: `HOLD_PENDING_VERIFICATION`
  and flag as insufficient sample size in the report.

## Exceptions

Couriers serving a single dense micro-region (e.g., a small town with one
active courier) will naturally show repeated pairings with many
customers; this policy applies to pair-level anomalies, not to expected
geographic concentration of courier assignments.
