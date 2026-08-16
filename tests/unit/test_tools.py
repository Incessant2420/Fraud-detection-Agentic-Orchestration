import pandas as pd
import pytest

from sentinel.data.store import conn
from sentinel.tools.digest import estimate_tokens
from sentinel.tools.registry import EvidenceLedger
from sentinel.tools.impl import (
    get_entity_profile, get_event_history, get_shared_entity_network,
    get_velocity_features, get_geo_risk, search_policy,
)


@pytest.fixture(scope="module")
def some_real_user():
    events = pd.read_parquet("data/processed/events.parquet")
    return events["actor_user_id"].iloc[0]


def _assert_digest_ok(digest: str):
    assert estimate_tokens(digest) <= 80


def test_get_entity_profile(some_real_user):
    ledger = EvidenceLedger()
    evidence_id, digest = get_entity_profile(ledger, user_id=some_real_user)
    assert evidence_id == "EV-001"
    _assert_digest_ok(digest)
    record = ledger.all()[0]
    assert record.raw_result["sample_size"] > 0
    assert "suspicious" not in digest.lower()


def test_get_entity_profile_empty_case():
    ledger = EvidenceLedger()
    _, digest = get_entity_profile(ledger, user_id="NONEXISTENT-USER-XYZ")
    _assert_digest_ok(digest)
    assert ledger.all()[0].raw_result["sample_size"] == 0


def test_get_event_history(some_real_user):
    ledger = EvidenceLedger()
    _, digest = get_event_history(ledger, user_id=some_real_user, lookback_days=3650, limit=10)
    _assert_digest_ok(digest)
    assert ledger.all()[0].raw_result["sample_size"] >= 0


def test_get_shared_entity_network(some_real_user):
    ledger = EvidenceLedger()
    _, digest = get_shared_entity_network(ledger, user_id=some_real_user)
    _assert_digest_ok(digest)


def test_get_velocity_features(some_real_user):
    ledger = EvidenceLedger()
    _, digest = get_velocity_features(ledger, user_id=some_real_user)
    _assert_digest_ok(digest)


def test_get_geo_risk_requires_sample_size():
    ledger = EvidenceLedger()
    _, digest = get_geo_risk(ledger, address_id="ADDR-FARM-000-000")
    _assert_digest_ok(digest)
    record = ledger.all()[0]
    assert "sample_size" in record.raw_result


def test_get_geo_risk_empty_case():
    ledger = EvidenceLedger()
    _, digest = get_geo_risk(ledger, address_id="NO-SUCH-ADDRESS")
    assert ledger.all()[0].raw_result["sample_size"] == 0


def test_search_policy_surfaces_correct_policy():
    ledger = EvidenceLedger()
    _, digest = search_policy(ledger, query="shared device cluster", k=3)
    record = ledger.all()[0]
    ids = [h["policy_id"] for h in record.raw_result["hits"]]
    assert "POL-AML-4.2" in ids
    _assert_digest_ok(digest)
