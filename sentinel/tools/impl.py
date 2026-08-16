"""The six evidence-retrieval tools. Every tool returns facts only — never a
judgement word like "suspicious" — and every rate-returning tool reports
sample_size so the agent can learn to discount small-n evidence.
"""
from datetime import datetime, timedelta, timezone

import networkx as nx

from sentinel.data.store import conn
from sentinel.tools.registry import tool
from sentinel.tools.digest import truncate_to_budget


def _empty(msg: str) -> dict:
    return {"_digest": truncate_to_budget(msg), "sample_size": 0, "empty": True}


@tool
def get_entity_profile(user_id: str) -> dict:
    """Account age, event count, lifetime value, first/last seen, verification status for a user."""
    c = conn()
    row = c.execute(
        "SELECT MIN(timestamp) AS first_seen, MAX(timestamp) AS last_seen, "
        "COUNT(*) AS n_events, COALESCE(SUM(amount), 0) AS lifetime_value "
        "FROM events WHERE actor_user_id = ?",
        [user_id],
    ).fetchone()
    if row is None or row[2] == 0:
        return _empty(f"No events found for user {user_id}. Insufficient evidence.")

    first_seen, last_seen, n_events, lifetime_value = row
    now = datetime.now(timezone.utc)
    first_dt = first_seen if isinstance(first_seen, datetime) else datetime.fromisoformat(str(first_seen))
    if first_dt.tzinfo is None:
        first_dt = first_dt.replace(tzinfo=timezone.utc)
    account_age_days = max((now - first_dt).days, 0)

    # Deterministic proxy for KYC/verification status: neither source dataset
    # carries a real verification field, so this is a documented modeling
    # assumption (tenure + activity), not inferred judgement about fraud.
    if account_age_days >= 30 and n_events >= 3:
        verification_status = "VERIFIED"
    elif account_age_days < 7:
        verification_status = "UNVERIFIED"
    else:
        verification_status = "PARTIAL"

    digest = (
        f"user={user_id} age_days={account_age_days} events={n_events} "
        f"ltv={lifetime_value:.2f} verification={verification_status}"
    )
    return {
        "_digest": truncate_to_budget(digest),
        "user_id": user_id,
        "account_age_days": account_age_days,
        "n_events": n_events,
        "lifetime_value": float(lifetime_value),
        "first_seen": str(first_seen),
        "last_seen": str(last_seen),
        "verification_status": verification_status,
        "sample_size": n_events,
    }


@tool
def get_event_history(user_id: str, lookback_days: int = 90, limit: int = 30) -> dict:
    """Chronological events for a user with amount, type, and outcome."""
    c = conn()
    rows = c.execute(
        "SELECT event_id, event_type, timestamp, amount, domain, raw_ref FROM events "
        "WHERE actor_user_id = ? AND timestamp >= (SELECT MAX(timestamp) FROM events) - INTERVAL (?) DAY "
        "ORDER BY timestamp DESC LIMIT ?",
        [user_id, lookback_days, limit],
    ).fetchall()
    if not rows:
        return _empty(f"No events in last {lookback_days}d for user {user_id}. Insufficient evidence.")

    events = []
    for r in rows:
        event_id, event_type, ts, amount, domain, raw_ref = r
        outcome = "UNKNOWN"
        if raw_ref:
            import json as _json
            try:
                outcome = _json.loads(raw_ref).get("outcome", "UNKNOWN")
            except Exception:
                pass
        events.append({
            "event_id": event_id, "event_type": event_type, "timestamp": str(ts),
            "amount": float(amount) if amount is not None else None,
            "domain": domain, "outcome": outcome,
        })

    type_counts = {}
    for e in events:
        type_counts[e["event_type"]] = type_counts.get(e["event_type"], 0) + 1
    top_types = ", ".join(f"{k}:{v}" for k, v in sorted(type_counts.items(), key=lambda x: -x[1])[:3])
    digest = f"user={user_id} n={len(events)} lookback={lookback_days}d types=[{top_types}]"
    return {
        "_digest": truncate_to_budget(digest),
        "user_id": user_id,
        "events": events,
        "sample_size": len(events),
    }


@tool
def get_shared_entity_network(user_id: str, hops: int = 2, entity_types: str | None = None) -> dict:
    """Subgraph of users sharing device/payment/address/IP entities with this user, up to N hops."""
    c = conn()
    type_filter = ""
    params = [user_id]
    if entity_types:
        types = [t.strip() for t in entity_types.split(",")]
        placeholders = ",".join("?" for _ in types)
        type_filter = f" AND ent.entity_type IN ({placeholders})"
        params.extend(types)

    seed_entities = c.execute(
        f"SELECT DISTINCT el.entity_id, ent.entity_type FROM entity_links el "
        f"JOIN events e ON e.event_id = el.event_id "
        f"JOIN entities ent ON ent.entity_id = el.entity_id "
        f"WHERE e.actor_user_id = ? AND ent.entity_type != 'USER'{type_filter}",
        params,
    ).fetchall()

    if not seed_entities:
        return _empty(f"No linked shared entities for user {user_id}. Insufficient evidence.")

    entity_ids = [e[0] for e in seed_entities]
    placeholders = ",".join("?" for _ in entity_ids)
    co_users = c.execute(
        f"SELECT DISTINCT e.actor_user_id, el.entity_id FROM entity_links el "
        f"JOIN events e ON e.event_id = el.event_id "
        f"WHERE el.entity_id IN ({placeholders})",
        entity_ids,
    ).fetchall()

    g = nx.Graph()
    g.add_node(user_id, kind="USER")
    for other_user, entity_id in co_users:
        g.add_node(other_user, kind="USER")
        g.add_node(entity_id, kind="ENTITY")
        g.add_edge(other_user, entity_id)
    for entity_id in entity_ids:
        g.add_edge(user_id, entity_id)

    user_nodes = [n for n, d in g.nodes(data=True) if d["kind"] == "USER"]
    cluster_size = len(user_nodes)
    cohesion = nx.density(g) if g.number_of_nodes() > 1 else 0.0

    nodes = [{"id": n, "kind": d["kind"]} for n, d in g.nodes(data=True)]
    edges = [{"source": u, "target": v} for u, v in g.edges()]

    digest = (
        f"user={user_id} cluster_size={cluster_size} shared_entities={len(entity_ids)} "
        f"cohesion={cohesion:.3f}"
    )
    return {
        "_digest": truncate_to_budget(digest),
        "user_id": user_id,
        "nodes": nodes,
        "edges": edges,
        "cluster_size": cluster_size,
        "cohesion_score": round(cohesion, 4),
        "sample_size": cluster_size,
    }


_WINDOW_TO_TIMEDELTA = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}


@tool
def get_velocity_features(user_id: str, windows: str = "1h,24h,7d") -> dict:
    """Event counts, distinct-entity counts, amount sums per time window, with population percentile."""
    c = conn()
    window_list = [w.strip() for w in windows.split(",")]
    max_ts_row = c.execute("SELECT MAX(timestamp) FROM events").fetchone()
    if max_ts_row is None or max_ts_row[0] is None:
        return _empty("No event data available. Insufficient evidence.")
    now = max_ts_row[0]

    result_windows = {}
    for w in window_list:
        delta = _WINDOW_TO_TIMEDELTA.get(w)
        if delta is None:
            continue
        row = c.execute(
            "SELECT COUNT(*), COUNT(DISTINCT el.entity_id), COALESCE(SUM(e.amount), 0) "
            "FROM events e LEFT JOIN entity_links el ON el.event_id = e.event_id "
            "WHERE e.actor_user_id = ? AND e.timestamp >= CAST(? AS TIMESTAMP) - INTERVAL '{}' HOUR".format(
                int(delta.total_seconds() // 3600) or 1
            ),
            [user_id, now],
        ).fetchone()
        n_events, n_entities, amount_sum = row
        # population percentile of this user's event count in this window vs all users
        pct_row = c.execute(
            "WITH per_user AS (SELECT actor_user_id, COUNT(*) AS n FROM events "
            "WHERE timestamp >= CAST(? AS TIMESTAMP) - INTERVAL '{}' HOUR GROUP BY actor_user_id) "
            "SELECT AVG(CASE WHEN n <= ? THEN 1.0 ELSE 0.0 END) FROM per_user".format(
                int(delta.total_seconds() // 3600) or 1
            ),
            [now, n_events],
        ).fetchone()
        percentile = float(pct_row[0]) if pct_row and pct_row[0] is not None else None
        result_windows[w] = {
            "n_events": n_events, "n_distinct_entities": n_entities,
            "amount_sum": float(amount_sum), "population_percentile": percentile,
        }

    if all(v["n_events"] == 0 for v in result_windows.values()):
        return _empty(f"No recent activity for user {user_id} in any window. Insufficient evidence.")

    parts = ", ".join(f"{w}:n={v['n_events']}/p{round((v['population_percentile'] or 0) * 100)}"
                       for w, v in result_windows.items())
    digest = f"user={user_id} velocity[{parts}]"
    sample_size = sum(v["n_events"] for v in result_windows.values())
    return {
        "_digest": truncate_to_budget(digest),
        "user_id": user_id,
        "windows": result_windows,
        "sample_size": sample_size,
    }


@tool
def get_geo_risk(address_id: str = "", pincode: str = "") -> dict:
    """Historical fraud rate and order density at a geo unit (address or pincode), with sample_size."""
    if not address_id and not pincode:
        return _empty("No geo identifier provided. Insufficient evidence.")
    c = conn()
    if address_id:
        rows = c.execute(
            "SELECT l.is_fraud FROM entity_links el "
            "JOIN events e ON e.event_id = el.event_id "
            "JOIN labels l ON l.event_id = e.event_id "
            "WHERE el.entity_id = ?",
            [address_id],
        ).fetchall()
        geo_key = address_id
    else:
        rows = c.execute(
            "SELECT l.is_fraud FROM entities ent "
            "JOIN entity_links el ON el.entity_id = ent.entity_id "
            "JOIN events e ON e.event_id = el.event_id "
            "JOIN labels l ON l.event_id = e.event_id "
            "WHERE ent.entity_type = 'ADDRESS' AND ent.entity_id LIKE ?",
            [f"%{pincode}%"],
        ).fetchall()
        geo_key = pincode

    sample_size = len(rows)
    if sample_size == 0:
        return _empty(f"No historical order/transaction data for geo unit {geo_key}. Insufficient evidence.")

    fraud_rate = sum(1 for r in rows if r[0]) / sample_size
    digest = f"geo={geo_key} fraud_rate={fraud_rate:.3f} sample_size={sample_size}"
    return {
        "_digest": truncate_to_budget(digest),
        "geo_key": geo_key,
        "historical_fraud_rate": round(fraud_rate, 4),
        "order_density": sample_size,
        "sample_size": sample_size,
    }


@tool
def search_policy(query: str, k: int = 3) -> dict:
    """Top-k policy chunks matching a query, with stable policy IDs."""
    from sentinel.tools.policy_rag import query_policies
    hits = query_policies(query, k=k)
    if not hits:
        return _empty(f"No policy match for query '{query}'.")
    ids = ", ".join(h["policy_id"] for h in hits)
    digest = f"query='{query[:40]}' top_policies=[{ids}]"
    return {
        "_digest": truncate_to_budget(digest),
        "query": query,
        "hits": hits,
        "sample_size": len(hits),
    }
