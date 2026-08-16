"""Commerce arm: Olist real orders (clean background population) + synthetic
abuse-pattern injection (Patterns A-D per spec section 5.2).

Olist carries no fraud label at all, so every commerce-arm Label has
source=INJECTED: real orders default to abuse_type=None/is_fraud=False
(an explicit modeling assumption — see README limitations), and the
synthetic rings/hard-negatives carry their pattern label.

Device/IP data does not exist in the real Olist dataset (Olist does not
capture it), so real background orders never get a DEVICE entity link.
Patterns A/B/C/D are fully synthetic per the original spec's own
"synthesize" language, so this gap does not affect the injection patterns.
"""
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yaml

from sentinel.data.canonical import CanonicalBuilder

RAW_DIR_DEFAULT = "data/raw/olist"
CONFIG_PATH = "config/injection.yaml"


def _hash_id(*parts, prefix: str) -> str:
    key = "|".join(str(p) for p in parts if p is not None and str(p) != "nan")
    h = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"{prefix}-{h}"


def _geohash_bucket(zip_prefix: str, precision: int = 6) -> str:
    # Deterministic coarse spatial bucket from the zip prefix, standing in
    # for a real geohash since Olist's geolocation table is zip->lat/lng
    # many-to-many and noisy; documented as a proxy in the README.
    return f"GEO-{str(zip_prefix)[:precision]}"


def _load_real_background(raw_dir: str, n_orders: int) -> CanonicalBuilder:
    orders = pd.read_csv(f"{raw_dir}/olist_orders_dataset.csv",
                          parse_dates=["order_purchase_timestamp"])
    customers = pd.read_csv(f"{raw_dir}/olist_customers_dataset.csv")
    payments = pd.read_csv(f"{raw_dir}/olist_order_payments_dataset.csv")

    orders = orders.sort_values("order_purchase_timestamp").head(n_orders)
    pay_agg = payments.groupby("order_id").agg(
        amount=("payment_value", "sum"),
        payment_type=("payment_type", "first"),
        installments=("payment_installments", "max"),
    ).reset_index()

    df = orders.merge(customers, on="customer_id", how="left").merge(pay_agg, on="order_id", how="left")

    b = CanonicalBuilder()
    for row in df.itertuples(index=False):
        r = row._asdict()
        user_id = f"U-{r['customer_unique_id']}"
        b.add_entity(user_id, "USER")

        event_id = f"COMM-{r['order_id']}"
        ts = r["order_purchase_timestamp"]
        if pd.isna(ts):
            continue
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts

        raw_ref = json.dumps({"outcome": r.get("order_status", "unknown"), "injected": False})
        amount = float(r["amount"]) if pd.notna(r.get("amount")) else 0.0

        b.add_event(event_id, user_id, "ORDER", ts, amount, "COMMERCE", raw_ref)
        b.add_link(event_id, user_id, "ACTOR")

        zip_prefix = r.get("customer_zip_code_prefix")
        if pd.notna(zip_prefix):
            addr_id = _geohash_bucket(zip_prefix, precision=6)
            b.add_entity(addr_id, "ADDRESS")
            b.add_link(event_id, addr_id, "ADDRESS")

        if pd.notna(r.get("payment_type")):
            pay_id = _hash_id(r.get("payment_type"), int(r.get("installments") or 0), prefix="PAY-REAL")
            b.add_entity(pay_id, "PAYMENT_INSTRUMENT")
            b.add_link(event_id, pay_id, "PAYMENT")

        b.add_label(event_id, False, None, "INJECTED")

    return b


def _inject_promo_rings(cfg: dict, rng: np.random.Generator, base_ts: datetime) -> CanonicalBuilder:
    b = CanonicalBuilder()
    ring_cfg = cfg["promo_ring"]
    for ring_i in range(ring_cfg["n_rings"]):
        size = rng.integers(ring_cfg["ring_size_min"], ring_cfg["ring_size_max"] + 1)
        device_id = f"D-RING-{ring_i:03d}"
        pay_prefix = f"PAY-RING-{ring_i:03d}"
        b.add_entity(device_id, "DEVICE")
        window_start = base_ts + timedelta(days=int(rng.integers(0, 700)))
        for member_i in range(size):
            user_id = f"U-RING-{ring_i:03d}-{member_i:03d}"
            b.add_entity(user_id, "USER")
            pay_id = f"{pay_prefix}-{member_i:03d}"
            b.add_entity(pay_id, "PAYMENT_INSTRUMENT")
            addr_id = f"ADDR-RING-{ring_i:03d}-{member_i:03d}"
            b.add_entity(addr_id, "ADDRESS")

            offset_h = float(rng.uniform(0, ring_cfg["first_order_window_hours"]))
            ts = window_start + timedelta(hours=offset_h)
            event_id = f"INJ-PROMO-{ring_i:03d}-{member_i:03d}"
            raw_ref = json.dumps({"outcome": "delivered", "injected": True, "first_order_discount": True})
            b.add_event(event_id, user_id, "ORDER", ts, float(rng.uniform(30, 150)), "COMMERCE", raw_ref)
            b.add_link(event_id, user_id, "ACTOR")
            b.add_link(event_id, device_id, "DEVICE")
            b.add_link(event_id, pay_id, "PAYMENT")
            b.add_link(event_id, addr_id, "ADDRESS")
            b.add_label(event_id, True, "PROMO_RING", "INJECTED")
    return b


def _inject_courier_collusion(cfg: dict, rng: np.random.Generator, base_ts: datetime) -> CanonicalBuilder:
    b = CanonicalBuilder()
    col_cfg = cfg["courier_collusion"]
    for pair_i in range(col_cfg["n_collusive_pairs"]):
        user_id = f"U-COLLUDE-{pair_i:03d}"
        courier_id = f"COURIER-{pair_i:03d}"
        addr_cluster = f"ADDR-COLLUDE-{pair_i:03d}"
        b.add_entity(user_id, "USER")
        b.add_entity(courier_id, "COURIER")
        b.add_entity(addr_cluster, "ADDRESS")

        n_orders = int(rng.integers(col_cfg["min_orders_per_pair"], col_cfg["min_orders_per_pair"] + 6))
        for order_i in range(n_orders):
            ts = base_ts + timedelta(days=int(rng.integers(0, 700)), hours=float(rng.uniform(0, 24)))
            event_id = f"INJ-COLLUDE-{pair_i:03d}-{order_i:03d}"
            is_missing_claim = rng.random() < col_cfg["item_missing_rate_min"] + 0.1
            raw_ref = json.dumps({
                "outcome": "item_missing" if is_missing_claim else "delivered",
                "injected": True, "courier_id": courier_id,
            })
            b.add_event(event_id, user_id, "ORDER", ts, float(rng.uniform(40, 200)), "COMMERCE", raw_ref)
            b.add_link(event_id, user_id, "ACTOR")
            b.add_link(event_id, courier_id, "COURIER")
            b.add_link(event_id, addr_cluster, "ADDRESS")
            if is_missing_claim:
                claim_event_id = f"INJ-COLLUDE-CLAIM-{pair_i:03d}-{order_i:03d}"
                b.add_event(claim_event_id, user_id, "REFUND_CLAIM", ts + timedelta(days=1), 0.0,
                            "COMMERCE", json.dumps({"outcome": "item_missing", "injected": True}))
                b.add_link(claim_event_id, user_id, "ACTOR")
            b.add_label(event_id, True, "COLLUSION", "INJECTED")
    return b


def _inject_address_farms(cfg: dict, rng: np.random.Generator, base_ts: datetime) -> CanonicalBuilder:
    b = CanonicalBuilder()
    farm_cfg = cfg["address_farm"]
    for farm_i in range(farm_cfg["n_farms"]):
        n_addr = int(rng.integers(farm_cfg["addresses_per_farm_min"], farm_cfg["addresses_per_farm_max"] + 1))
        geo_cluster = f"GEO-FARM-{farm_i:03d}"
        for addr_i in range(n_addr):
            user_id = f"U-FARM-{farm_i:03d}-{addr_i:03d}"
            device_id = f"D-FARM-{farm_i:03d}-{addr_i:03d}"  # distinct device per account
            addr_id = f"ADDR-FARM-{farm_i:03d}-{addr_i:03d}"
            b.add_entity(user_id, "USER")
            b.add_entity(device_id, "DEVICE")
            b.add_entity(addr_id, "ADDRESS")

            n_orders = int(rng.integers(2, 6))
            for order_i in range(n_orders):
                ts = base_ts + timedelta(days=int(rng.integers(0, 700)))
                event_id = f"INJ-FARM-{farm_i:03d}-{addr_i:03d}-{order_i:03d}"
                is_refund = rng.random() < farm_cfg["refund_rate_min"] + 0.1
                raw_ref = json.dumps({
                    "outcome": "refunded" if is_refund else "delivered",
                    "injected": True, "geo_cluster": geo_cluster,
                })
                amount = float(rng.uniform(100, 500) * farm_cfg["high_value_multiplier"])
                b.add_event(event_id, user_id, "ORDER", ts, amount, "COMMERCE", raw_ref)
                b.add_link(event_id, user_id, "ACTOR")
                b.add_link(event_id, device_id, "DEVICE")
                b.add_link(event_id, addr_id, "ADDRESS")
                b.add_link(event_id, geo_cluster, "ADDRESS")  # also link the shared geo bucket
                b.add_label(event_id, True, "ADDRESS_FARM", "INJECTED")
            b.add_entity(geo_cluster, "ADDRESS")
    return b


def _inject_hard_negatives(cfg: dict, rng: np.random.Generator, base_ts: datetime) -> CanonicalBuilder:
    b = CanonicalBuilder()
    hn_cfg = cfg["hard_negatives"]

    def _cluster_group(kind: str, n_clusters: int, size_min: int, size_max: int, tight_timing: bool):
        for c_i in range(n_clusters):
            device_id = f"D-{kind}-{c_i:03d}"
            addr_id = f"ADDR-{kind}-{c_i:03d}"
            b.add_entity(device_id, "DEVICE")
            b.add_entity(addr_id, "ADDRESS")
            size = int(rng.integers(size_min, size_max + 1))
            cluster_start = base_ts + timedelta(days=int(rng.integers(0, 700)))
            for m_i in range(size):
                user_id = f"U-{kind}-{c_i:03d}-{m_i:03d}"
                b.add_entity(user_id, "USER")
                n_orders = int(rng.integers(1, 8))
                for order_i in range(n_orders):
                    if tight_timing:
                        ts = cluster_start + timedelta(hours=float(rng.uniform(0, 48)))
                    else:
                        ts = base_ts + timedelta(days=int(rng.integers(0, 700)))
                    event_id = f"INJ-{kind}-{c_i:03d}-{m_i:03d}-{order_i:03d}"
                    is_refund = rng.random() < 0.06  # normal baseline refund rate
                    raw_ref = json.dumps({
                        "outcome": "refunded" if is_refund else "delivered", "injected": True,
                    })
                    b.add_event(event_id, user_id, "ORDER", ts, float(rng.uniform(20, 120)), "COMMERCE", raw_ref)
                    b.add_link(event_id, user_id, "ACTOR")
                    b.add_link(event_id, device_id, "DEVICE")
                    b.add_link(event_id, addr_id, "ADDRESS")
                    b.add_label(event_id, False, "NONE", "INJECTED")

    fam = hn_cfg["family_household"]
    _cluster_group("FAMILY", fam["n_clusters"], fam["members_per_cluster_min"], fam["members_per_cluster_max"], False)
    off = hn_cfg["shared_office"]
    _cluster_group("OFFICE", off["n_clusters"], off["members_per_cluster_min"], off["members_per_cluster_max"], False)
    acc = hn_cfg["shared_accommodation"]
    _cluster_group("HOSTEL", acc["n_clusters"], acc["members_per_cluster_min"], acc["members_per_cluster_max"], False)
    return b


def build_commerce_arm(raw_dir: str = RAW_DIR_DEFAULT, config_path: str = CONFIG_PATH,
                        n_real_orders: int = 40_000) -> CanonicalBuilder:
    cfg = yaml.safe_load(open(config_path))
    rng = np.random.default_rng(cfg["seed"])
    base_ts = datetime(2017, 1, 1, tzinfo=timezone.utc)

    builders = [
        _load_real_background(raw_dir, n_real_orders),
        _inject_promo_rings(cfg, rng, base_ts),
        _inject_courier_collusion(cfg, rng, base_ts),
        _inject_address_farms(cfg, rng, base_ts),
        _inject_hard_negatives(cfg, rng, base_ts),
    ]

    combined = CanonicalBuilder()
    for b in builders:
        combined.entities.update(b.entities)
        combined.events.extend(b.events)
        combined.links.extend(b.links)
        combined.labels.extend(b.labels)
    return combined


if __name__ == "__main__":
    builder = build_commerce_arm()
    e, v, l, lb = builder.to_frames()
    print(f"commerce arm: {len(v)} events, {len(e)} entities")
    print(lb["abuse_type"].value_counts(dropna=False))
