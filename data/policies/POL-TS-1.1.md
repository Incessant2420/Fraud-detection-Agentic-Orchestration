---
id: POL-TS-1.1
title: Multi-Accounting and Promotional Abuse Rings
category: Trust & Safety
effective_date: 2025-01-01
---

# Multi-Accounting and Promotional Abuse Rings

Governs detection of coordinated multi-account creation used to
repeatedly claim first-order promotions or referral incentives.

## Rule

A cluster of 8 or more accounts sharing a device identifier and payment
instrument prefix, whose first orders fall within a 48-hour window and
each redeem a first-order discount or referral promo, is classified a
`PROMO_RING`.

## Rationale

Promotional incentives are priced assuming one redemption per genuine
new customer. Coordinated account farms erase that unit economics
assumption and are among the highest-volume abuse patterns on
e-commerce and quick-commerce platforms. The tight timing window (first
orders clustered within 48 hours) is what separates a ring from
organic growth of a household or shared device over time.

## Required Evidence

1. Shared-entity network showing cluster size, shared device, and payment
   prefix.
2. Event history confirming first-order timing clustering and promo
   redemption on each account.
3. Explicit consideration of legitimate carve-outs (POL-TS-2.2) — a family
   signing up together during a launch promotion looks superficially
   similar and must be distinguished by refund/dispute behavior and
   address diversity, not device sharing alone.

## Disposition Guidance

- Cluster size >= 8, tight timing window, matching payment prefix, low
  address diversity: `BLOCK` the ring's remaining unredeemed promo value;
  `ESCALATE_TO_HUMAN` for the already-redeemed accounts.
- Cluster size 5-7 or looser timing: `HOLD_PENDING_VERIFICATION`.

## Exceptions

Corporate bulk sign-up events (a company onboarding a device fleet) and
household launches should be excluded when device sharing is the only
common factor and refund/dispute rates are otherwise normal.
