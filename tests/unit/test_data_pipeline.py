import pandas as pd

PROCESSED = "data/processed"


def test_canonical_tables_exist_and_link():
    entities = pd.read_parquet(f"{PROCESSED}/entities.parquet")
    events = pd.read_parquet(f"{PROCESSED}/events.parquet")
    links = pd.read_parquet(f"{PROCESSED}/entity_links.parquet")
    labels = pd.read_parquet(f"{PROCESSED}/labels.parquet")

    assert len(entities) > 0 and len(events) > 0 and len(links) > 0 and len(labels) > 0
    assert set(entities.columns) == {"entity_id", "entity_type"}
    assert set(events.columns) == {"event_id", "actor_user_id", "event_type", "timestamp",
                                    "amount", "domain", "raw_ref"}

    # every entity_link's event_id must resolve to a real event (referential integrity)
    assert links["event_id"].isin(events["event_id"]).all()
    # every label's event_id must resolve to a real event
    assert labels["event_id"].isin(events["event_id"]).all()


def test_both_domains_present_with_hard_negatives():
    events = pd.read_parquet(f"{PROCESSED}/events.parquet")
    labels = pd.read_parquet(f"{PROCESSED}/labels.parquet")
    merged = labels.merge(events[["event_id", "domain"]], on="event_id")

    assert set(merged["domain"].unique()) >= {"BANK", "COMMERCE"}
    commerce = merged[merged["domain"] == "COMMERCE"]
    assert (commerce["abuse_type"] == "NONE").sum() > 0, "hard negatives must be present"
    true_rings = commerce["abuse_type"].isin(["PROMO_RING", "COLLUSION", "ADDRESS_FARM"]).sum()
    hard_negs = (commerce["abuse_type"] == "NONE").sum()
    assert hard_negs >= true_rings, "hard negatives should be at least as large as true-ring volume"
