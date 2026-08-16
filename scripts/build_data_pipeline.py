"""Phase 1 entry point: build both arms into the canonical Parquet schema
and print label balance (the phase gate)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.data.build_bank_arm import build_bank_arm
from sentinel.data.build_commerce_arm import build_commerce_arm
from sentinel.data.canonical import write_combined


def main():
    print("building bank arm (IEEE-CIS)...")
    bank = build_bank_arm()
    print("building commerce arm (Olist + injection)...")
    commerce = build_commerce_arm()

    counts = write_combined([bank, commerce])
    print(f"\nwrote canonical tables: {counts}")

    import pandas as pd
    labels = pd.read_parquet("data/processed/labels.parquet")
    events = pd.read_parquet("data/processed/events.parquet")
    merged = labels.merge(events[["event_id", "domain"]], on="event_id")

    print("\n--- label balance by domain ---")
    for domain, grp in merged.groupby("domain"):
        print(f"{domain}: n={len(grp)} fraud_rate={grp['is_fraud'].mean():.4f}")
        print(grp["abuse_type"].value_counts(dropna=False).to_string())
        print()


if __name__ == "__main__":
    main()
