---
id: POL-FRD-2.4
title: Account Age Risk Weighting
category: Fraud
effective_date: 2025-01-01
---

# Account Age Risk Weighting

Establishes how account tenure should weight into fraud-risk assessment
alongside behavioral signals.

## Rule

Accounts younger than 7 days are classified `UNVERIFIED` tenure risk;
accounts between 7 and 30 days are `PARTIAL`; accounts 30+ days with at
least 3 prior events are `VERIFIED` tenure risk. Any single risk signal
(velocity spike, device-sharing cluster, geo anomaly) occurring on an
`UNVERIFIED`-tenure account should be weighted as materially higher risk
than the identical signal on a `VERIFIED`-tenure account.

## Rationale

New-account fraud (synthetic identity, stolen-identity account opening,
promo-abuse account farming) concentrates overwhelmingly in the first days
of an account's life. The same velocity or network signal is far more
likely to reflect coordinated abuse when paired with a brand-new account
than when it appears on an account with months of clean history.

## Required Evidence

1. Entity profile showing account_age_days and verification_status.
2. At least one additional independent risk signal (velocity, network, or
   geo) — account age alone is never sufficient grounds for BLOCK or
   ESCALATE_TO_HUMAN.

## Disposition Guidance

- `UNVERIFIED` tenure + any STRONG independent finding: escalate weight of
  that finding; consider `BLOCK` or `ESCALATE_TO_HUMAN`.
- `VERIFIED` tenure + an isolated moderate signal: prefer
  `HOLD_PENDING_VERIFICATION` or `APPROVE` with a noted unresolved
  question, since tenure argues against coordinated abuse.

## Exceptions

Tenure risk must never be the sole cited finding for a disposition more
severe than `HOLD_PENDING_VERIFICATION`; it is a weighting factor, not a
standalone trigger.
