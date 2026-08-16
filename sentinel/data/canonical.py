"""Canonical schema writer: Entity / Event / EntityLink / Label tables,
shared by both the bank and commerce arms, persisted as Parquet.
"""
from pathlib import Path
import pandas as pd

PROCESSED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "processed"

ENTITY_COLUMNS = ["entity_id", "entity_type"]
EVENT_COLUMNS = ["event_id", "actor_user_id", "event_type", "timestamp", "amount", "domain", "raw_ref"]
LINK_COLUMNS = ["event_id", "entity_id", "role"]
LABEL_COLUMNS = ["event_id", "is_fraud", "abuse_type", "source"]


class CanonicalBuilder:
    def __init__(self):
        self.entities = {}   # entity_id -> entity_type (dedup)
        self.events = []
        self.links = []
        self.labels = []

    def add_entity(self, entity_id: str, entity_type: str):
        self.entities[entity_id] = entity_type

    def add_event(self, event_id, actor_user_id, event_type, timestamp, amount, domain, raw_ref):
        self.events.append({
            "event_id": event_id, "actor_user_id": actor_user_id, "event_type": event_type,
            "timestamp": timestamp, "amount": amount, "domain": domain, "raw_ref": raw_ref,
        })

    def add_link(self, event_id, entity_id, role):
        self.links.append({"event_id": event_id, "entity_id": entity_id, "role": role})

    def add_label(self, event_id, is_fraud, abuse_type, source):
        self.labels.append({"event_id": event_id, "is_fraud": is_fraud, "abuse_type": abuse_type, "source": source})

    def to_frames(self):
        ent_df = pd.DataFrame(
            [{"entity_id": k, "entity_type": v} for k, v in self.entities.items()],
            columns=ENTITY_COLUMNS,
        )
        evt_df = pd.DataFrame(self.events, columns=EVENT_COLUMNS)
        link_df = pd.DataFrame(self.links, columns=LINK_COLUMNS)
        lbl_df = pd.DataFrame(self.labels, columns=LABEL_COLUMNS)
        return ent_df, evt_df, link_df, lbl_df


def write_combined(builders: list[CanonicalBuilder]):
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    ent_frames, evt_frames, link_frames, lbl_frames = [], [], [], []
    for b in builders:
        e, v, l, lb = b.to_frames()
        ent_frames.append(e)
        evt_frames.append(v)
        link_frames.append(l)
        lbl_frames.append(lb)

    entities = pd.concat(ent_frames, ignore_index=True).drop_duplicates(subset=["entity_id"])
    events = pd.concat(evt_frames, ignore_index=True)
    links = pd.concat(link_frames, ignore_index=True)
    labels = pd.concat(lbl_frames, ignore_index=True)

    events["timestamp"] = pd.to_datetime(events["timestamp"], utc=True)

    entities.to_parquet(PROCESSED_DIR / "entities.parquet", index=False)
    events.to_parquet(PROCESSED_DIR / "events.parquet", index=False)
    links.to_parquet(PROCESSED_DIR / "entity_links.parquet", index=False)
    labels.to_parquet(PROCESSED_DIR / "labels.parquet", index=False)

    return {
        "entities": len(entities), "events": len(events),
        "entity_links": len(links), "labels": len(labels),
    }
