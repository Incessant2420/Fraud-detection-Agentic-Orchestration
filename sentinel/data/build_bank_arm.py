"""Bank arm: IEEE-CIS Fraud Detection -> canonical schema.

Scale note (documented reduction, not an architectural simplification):
the full IEEE-CIS train_transaction.csv is ~590K rows / 683MB. We use the
first N rows in TransactionDT (time) order, which is enough to produce
~120 flagged cases with real SHAP-driven LightGBM scoring and real DuckDB
tool queries, without multi-hour pipeline runtimes. Full-scale processing
would use the entire file unchanged -- no code path here assumes the
sample.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from sentinel.data.canonical import CanonicalBuilder

RAW_DIR_DEFAULT = "data/raw/ieee-cis"
KEEP_TXN_COLS = [
    "TransactionID", "TransactionDT", "TransactionAmt", "ProductCD", "isFraud",
    "card1", "card2", "card3", "card4", "card5", "card6",
    "addr1", "addr2", "P_emaildomain",
] + [f"C{i}" for i in range(1, 15)] + [f"D{i}" for i in range(1, 16)]
KEEP_ID_COLS = ["TransactionID", "DeviceType", "DeviceInfo", "id_30", "id_31", "id_32", "id_33"]

EPOCH = datetime(2017, 12, 1, tzinfo=timezone.utc)  # IEEE-CIS TransactionDT reference (documented convention)


def _hash_id(*parts: str, prefix: str) -> str:
    key = "|".join(str(p) for p in parts if p is not None and str(p) != "nan")
    h = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"{prefix}-{h}"


def build_bank_arm(raw_dir: str = RAW_DIR_DEFAULT, n_rows: int | None = 120_000) -> CanonicalBuilder:
    txn = pd.read_csv(f"{raw_dir}/train_transaction.csv", usecols=lambda c: c in KEEP_TXN_COLS)
    ident = pd.read_csv(f"{raw_dir}/train_identity.csv", usecols=lambda c: c in KEEP_ID_COLS)

    txn = txn.sort_values("TransactionDT")
    if n_rows is not None:
        txn = txn.head(n_rows)

    df = txn.merge(ident, on="TransactionID", how="left")

    b = CanonicalBuilder()
    for row in df.itertuples(index=False):
        r = row._asdict()

        # Pseudo-user construction: IEEE-CIS has no user ID. Hash
        # card1 + addr1 + P_emaildomain (stated modeling assumption; see README).
        user_id = _hash_id(r.get("card1"), r.get("addr1"), r.get("P_emaildomain"), prefix="U")
        b.add_entity(user_id, "USER")

        event_id = f"BANK-{int(r['TransactionID'])}"
        ts = EPOCH + timedelta(seconds=int(r["TransactionDT"]))

        # No decline/outcome field exists in IEEE-CIS transaction records;
        # every row is a recorded (completed) transaction. Documented assumption.
        raw_ref = json.dumps({"outcome": "COMPLETED", "product_cd": r.get("ProductCD")})

        b.add_event(
            event_id=event_id, actor_user_id=user_id, event_type="TRANSACTION",
            timestamp=ts, amount=float(r["TransactionAmt"]), domain="BANK", raw_ref=raw_ref,
        )
        b.add_link(event_id, user_id, "ACTOR")

        if pd.notna(r.get("DeviceType")) or pd.notna(r.get("DeviceInfo")):
            device_id = _hash_id(r.get("DeviceType"), r.get("DeviceInfo"), r.get("id_30"), r.get("id_31"), prefix="D")
            b.add_entity(device_id, "DEVICE")
            b.add_link(event_id, device_id, "DEVICE")

        card_parts = [r.get(f"card{i}") for i in range(1, 7)]
        if any(pd.notna(p) for p in card_parts):
            pay_id = _hash_id(*card_parts, prefix="PAY")
            b.add_entity(pay_id, "PAYMENT_INSTRUMENT")
            b.add_link(event_id, pay_id, "PAYMENT")

        if pd.notna(r.get("addr1")):
            addr_id = _hash_id(r.get("addr1"), r.get("addr2"), prefix="ADDR")
            b.add_entity(addr_id, "ADDRESS")
            b.add_link(event_id, addr_id, "ADDRESS")

        b.add_label(event_id, bool(r["isFraud"]), "CARD_FRAUD" if r["isFraud"] else None, "GROUND_TRUTH")

    return b


if __name__ == "__main__":
    builder = build_bank_arm()
    e, v, l, lb = builder.to_frames()
    print(f"bank arm: {len(v)} events, {len(e)} entities, fraud_rate={lb['is_fraud'].mean():.4f}")
