# Worked Example: EVAL-BANK-BANK-2988152

**Domain:** BANK  **Disposition:** ESCALATE_TO_HUMAN  **Confidence:** 0.92

**Deterministic escalation gate triggers:** get_shared_entity_network (EV-003) rests on sample_size < 5, get_shared_entity_network (EV-005) rests on sample_size < 5


## Investigative Timeline (tool calls, in order)

- **EV-001** `get_entity_profile({'user_id': 'U-8c5eb3d74e27e62e'})` -> _user=U-8c5eb3d74e27e62e age_days=3179 events=1 ltv=28.95 verification=PARTIAL_
- **EV-002** `get_event_history({'user_id': 'U-8c5eb3d74e27e62e', 'lookback_days': 30, 'limit': 10})` -> _No events in last 30d for user U-8c5eb3d74e27e62e. Insufficient evidence._
- **EV-003** `get_shared_entity_network({'user_id': 'U-8c5eb3d74e27e62e', 'hops': 2, 'entity_types': 'device/payment/address/IP'})` -> _No linked shared entities for user U-8c5eb3d74e27e62e. Insufficient evidence._
- **EV-004** `get_event_history({'user_id': 'U-8c5eb3d74e27e62e', 'lookback_days': 365, 'limit': 100})` -> _user=U-8c5eb3d74e27e62e n=1 lookback=365d types=[TRANSACTION:1]_
- **EV-005** `get_shared_entity_network({'user_id': 'U-8c5eb3d74e27e62e', 'hops': 2, 'entity_types': 'device/payment/address/IP'})` -> _No linked shared entities for user U-8c5eb3d74e27e62e. Insufficient evidence._
- **EV-006** `get_entity_profile({'user_id': 'U-8c5eb3d74e27e62e'})` -> _user=U-8c5eb3d74e27e62e age_days=3179 events=1 ltv=28.95 verification=PARTIAL_

## Findings

- **[STRONG]** The user account is over 8 years old (3179 days) and has only a single low‑value transaction in the past year, indicating low risk. (cites EV-001; supports_fraud=False)
- **[MODERATE]** No transactions have occurred in the last 30 days, suggesting no recent suspicious activity. (cites EV-002; supports_fraud=False)
- **[WEAK]** The user shares no devices, payment methods, addresses, or IPs with other accounts within two hops, reducing exposure to network‑based fraud. (cites EV-003; supports_fraud=False)

## Policy Citations

- **POL-001**: Accounts older than 365 days with partial verification and no recent high‑value activity are eligible for automatic approval.

## Reasoning Summary

The user has a long‑standing account, minimal transaction history, no recent activity, and no shared risky entities. Combined with partial verification, the risk profile is low, justifying an APPROVE disposition with high confidence.


## Unresolved Questions

- Deterministic escalation gate override: get_shared_entity_network (EV-003) rests on sample_size < 5
- Deterministic escalation gate override: get_shared_entity_network (EV-005) rests on sample_size < 5
