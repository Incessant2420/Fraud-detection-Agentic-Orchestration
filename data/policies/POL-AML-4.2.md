---
id: POL-AML-4.2
title: Linked Entity Rings — Device Sharing Threshold
category: AML
effective_date: 2025-01-01
---

# Linked Entity Rings — Device Sharing Threshold

This policy governs the review of transaction accounts that share physical
or digital device identifiers with other accounts on the platform.

## Rule

If five (5) or more distinct user accounts transact through the same
`device_id` within a rolling 30-day window, the cluster is classified as a
**review-triggering linked-entity ring** and must be escalated for manual
investigation before any account in the cluster is approved for a
disposition of APPROVE.

The threshold is deliberately set above ordinary shared-device scenarios
(see POL-TS-2.2 for legitimate shared-device carve-outs) to reduce false
positives from families or small offices sharing a single computer or
point-of-sale terminal.

## Rationale

Device-sharing rings are a leading indicator of synthetic identity fraud
and promotional abuse rings, where a single operator creates multiple
accounts to bypass per-user limits (promo abuse, chargeback laundering,
or structuring). A cluster size of 5+ accounts on one device within 30
days is empirically associated with coordinated abuse rather than
incidental sharing.

## Required Evidence

An analyst or automated agent citing this policy must produce:
1. The device identifier in question.
2. The count of distinct accounts sharing it within the 30-day window.
3. The cohesion/cluster metrics from the shared-entity network tool.

## Disposition Guidance

- Cluster size >= 5 in 30 days: minimum disposition is
  `HOLD_PENDING_VERIFICATION`; `BLOCK` or `ESCALATE_TO_HUMAN` if combined
  with velocity anomalies (see POL-FRD-2.1) or address clustering
  (POL-TS-2.2).
- Cluster size < 5: does not independently trigger this policy, though it
  may still be relevant supporting context for other findings.

## Exceptions

Shared corporate/office devices, family accounts, and shared public
terminals (library, hostel) are common false positives. See POL-TS-2.2 for
the required carve-out analysis before escalating on device-sharing alone.
