"""用户干预的测试。"""

from __future__ import annotations

import pytest

from app.models import RegionState
from app.services import ActionError, apply_action, create_branch, get_world_by_key
from sqlalchemy import select


def _branch(session):
    world = get_world_by_key(session, "tang_750")
    return create_branch(session, world, name="干预测试", seed=3)


def _region(session, branch_id, key):
    return session.scalar(
        select(RegionState).where(
            RegionState.branch_id == branch_id, RegionState.region_key == key
        )
    )


def test_shock_reduces_stock_and_writes_event(db_session):
    branch = _branch(db_session)
    before = _region(db_session, branch.id, "hebei").grain_stock

    event = apply_action(db_session, branch, "shock", "hebei", {"damage_ratio": 0.5})
    db_session.flush()

    after = _region(db_session, branch.id, "hebei").grain_stock
    assert after == pytest.approx(before * 0.5, rel=1e-6)
    assert event.kind == "user_shock"
    assert event.region_keys == ["hebei"]
    assert event.id is not None


def test_relief_adds_grain_and_costs_treasury(db_session):
    branch = _branch(db_session)
    before = _region(db_session, branch.id, "hebei").grain_stock

    apply_action(db_session, branch, "relief", "hebei", {"amount": 100_000})
    db_session.flush()

    assert _region(db_session, branch.id, "hebei").grain_stock == pytest.approx(
        before + 100_000
    )


def test_tax_change_is_applied(db_session):
    branch = _branch(db_session)
    event = apply_action(db_session, branch, "tax", "henan", {"rate": 0.15})
    db_session.flush()
    assert _region(db_session, branch.id, "henan").tax_rate == pytest.approx(0.15)
    assert event.kind == "user_tax"


def test_invalid_actions_are_rejected(db_session):
    branch = _branch(db_session)
    with pytest.raises(ActionError):
        apply_action(db_session, branch, "nuke", "hebei", {})
    with pytest.raises(ActionError):
        apply_action(db_session, branch, "shock", "hebei", {"damage_ratio": 2})
    with pytest.raises(ActionError):
        apply_action(db_session, branch, "relief", "hebei", {"amount": 0})
    with pytest.raises(LookupError):
        apply_action(db_session, branch, "shock", "not-exist", {"damage_ratio": 0.3})


def test_action_api_and_chain_reaches_intervention(client):
    branch = client.post("/api/worlds/tang_750/branches", json={"seed": 3}).get_json()
    bid = branch["id"]

    resp = client.post(
        f"/api/branches/{bid}/actions",
        json={"kind": "shock", "region_key": "hebei", "params": {"damage_ratio": 0.85}},
    )
    assert resp.status_code == 201
    shock = resp.get_json()
    assert shock["kind"] == "user_shock"

    client.post(f"/api/branches/{bid}/advance", json={"months": 2})

    events = client.get(f"/api/branches/{bid}/events?limit=100").get_json()
    flow = next((e for e in events if e["kind"] == "grain_flow"), None)
    assert flow is not None, "严重歉收后应触发跨道调运"

    chain = client.get(f"/api/branches/{bid}/events/{flow['id']}/chain").get_json()
    kinds = {node["kind"] for node in chain["nodes"]}
    assert "user_shock" in kinds, "因果链应一路追溯到用户干预"
    assert "famine" in kinds


def test_action_api_rejects_bad_payload(client):
    branch = client.post("/api/worlds/tang_750/branches", json={}).get_json()
    resp = client.post(
        f"/api/branches/{branch['id']}/actions",
        json={"kind": "shock", "region_key": "hebei", "params": {"damage_ratio": 9}},
    )
    assert resp.status_code == 400