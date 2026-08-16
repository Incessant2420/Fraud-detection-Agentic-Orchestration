---
id: POL-TS-2.2
title: Address Clustering — Legitimate Carve-Outs
category: Trust & Safety
effective_date: 2025-01-01
---

# Address Clustering — Legitimate Carve-Outs

Governs how tight geographic/address clustering of orders should be
interpreted, and — critically — when it must **not** be treated as
evidence of abuse.

## Rule

Distinct accounts whose delivery addresses collapse to a tight geohash
cluster, combined with high order value and elevated refund rate, are
classified `ADDRESS_FARM` candidates. However, address clustering **alone
is explicitly insufficient** and must be paired with an elevated refund or
dispute rate and a lack of a plausible legitimate explanation before any
disposition more severe than `HOLD_PENDING_VERIFICATION` is applied.

## Mandatory Carve-Outs

The following patterns produce identical address-clustering signatures to
genuine abuse and must be affirmatively ruled out, not merely
unconsidered, before escalating on this policy:

1. **Family households** — multiple accounts (e.g., spouses, roommates,
   adult children) ordering to one shared home address. Distinguishing
   signal: normal refund rates, diverse order categories/timing, no
   device-farming pattern.
2. **Shared offices** — many employees receiving deliveries at one
   business address. Distinguishing signal: business-hours ordering
   pattern, high account diversity, normal refund rate, often a named
   commercial address type.
3. **Shared accommodation** (hostels, dorms, co-living spaces) — many
   distinct residents, one physical address, transient population.
   Distinguishing signal: high account turnover, normal per-account refund
   behavior.

## Required Evidence

1. Geo risk tool output including sample_size — never cite a fraud rate
   without it.
2. Refund/dispute rate for the cluster versus baseline.
3. An explicit statement addressing which (if any) of the three carve-outs
   above was considered and why it was ruled in or out.

## Disposition Guidance

- Tight geo cluster + high value + refund rate significantly above
  baseline + no plausible carve-out: `BLOCK` or `ESCALATE_TO_HUMAN`.
- Tight geo cluster with normal refund rate and a plausible carve-out
  (family/office/shared housing): `APPROVE`, explicitly noting the
  carve-out in reasoning.
