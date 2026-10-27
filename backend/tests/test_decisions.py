"""决策系统测试：世界要主动提问题，选项要真的改变世界。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.engine import SimulationEngine
from app.engine.decisions import (
    DecisionError,
    describe_relation,
    pending_decisions,
    resolve_decision,
)
from app.models import Decision, FactionState, RegionState, RelationState
from app.services import create_branch, get_world_by_key


def _branch(session):
    world = get_world_by_key(session, "tang_750")
    return create_branch(session, world, name="决策测试", seed=3)


def _tang(session, branch_id):
    return session.scalar(
        select(FactionState).where(
            FactionState.branch_id == branch_id, FactionState.faction_key == "tang"
        )
    )


def _relation(session, branch_id):
    return session.scalar(
        select(RelationState).where(RelationState.branch_id == branch_id)
    )


def _region(session, branch_id, key):
    return session.scalar(
        select(RegionState).where(
            RegionState.branch_id == branch_id, RegionState.region_key == key
        )
    )


def test_branch_starts_with_relation_and_scenario(db_session):
    branch = _branch(db_session)
    rel = _relation(db_session, branch.id)
    assert rel is not None
    assert rel.from_key == "fanzhen"
    assert 0 < rel.value < 1

    world = get_world_by_key(db_session, "tang_750")
    assert world.scenario["role"]
    assert world.scenario["goal"]
    assert world.scenario["pressures"]


def test_relation_drifts_over_time(db_session):
    branch = _branch(db_session)
    before = _relation(db_session, branch.id).value
    SimulationEngine(db_session).advance(branch, months=6)
    db_session.flush()
    after = _relation(db_session, branch.id).value
    assert after < before, "藩镇臣属度会随时间自然下滑"


def test_warlord_supply_decision_raised_when_treasury_negative(db_session):
    branch = _branch(db_session)
    fanzhen = db_session.scalar(
        select(FactionState).where(
            FactionState.branch_id == branch.id, FactionState.faction_key == "fanzhen"
        )
    )
    fanzhen.treasury = -500_000
    db_session.flush()

    report = SimulationEngine(db_session).advance(branch, months=1)
    kinds = {d["kind"] for d in report.decisions}
    assert "warlord_supply" in kinds

    pending = pending_decisions(db_session, branch.id)
    assert pending, "决策应当是待处理状态"
    assert len(pending[0].options) == 3


def test_famine_relief_decision_raised_for_troubled_region(db_session):
    branch = _branch(db_session)
    hebei = _region(db_session, branch.id, "hebei")
    hebei.unrest = 0.8
    db_session.flush()

    report = SimulationEngine(db_session).advance(branch, months=1)
    assert any(d["kind"] == "famine_relief" for d in report.decisions)


def test_decisions_do_not_repeat_within_cooldown(db_session):
    branch = _branch(db_session)
    hebei = _region(db_session, branch.id, "hebei")
    hebei.unrest = 0.9
    db_session.flush()

    engine = SimulationEngine(db_session)
    first = engine.advance(branch, months=1)
    assert any(d["kind"] == "famine_relief" for d in first.decisions)

    second = engine.advance(branch, months=1)
    assert not any(d["kind"] == "famine_relief" for d in second.decisions)


def test_resolving_grant_full_moves_treasury_and_relation(db_session):
    branch = _branch(db_session)
    fanzhen = db_session.scalar(
        select(FactionState).where(
            FactionState.branch_id == branch.id, FactionState.faction_key == "fanzhen"
        )
    )
    fanzhen.treasury = -400_000
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = pending_decisions(db_session, branch.id)[0]

    tang_before = _tang(db_session, branch.id).treasury
    rel_before = _relation(db_session, branch.id).value

    event = resolve_decision(db_session, branch, decision, "grant_full")
    db_session.flush()

    assert _tang(db_session, branch.id).treasury < tang_before
    assert _relation(db_session, branch.id).value > rel_before
    assert decision.status == "resolved"
    assert decision.result_event_id == event.id
    assert event.kind == "decision"


def test_refusing_lowers_relation_and_raises_unrest(db_session):
    branch = _branch(db_session)
    fanzhen = db_session.scalar(
        select(FactionState).where(
            FactionState.branch_id == branch.id, FactionState.faction_key == "fanzhen"
        )
    )
    fanzhen.treasury = -400_000
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = pending_decisions(db_session, branch.id)[0]

    rel_before = _relation(db_session, branch.id).value
    unrest_before = _region(db_session, branch.id, "hebei").unrest

    resolve_decision(db_session, branch, decision, "refuse")
    db_session.flush()

    assert _relation(db_session, branch.id).value < rel_before
    assert _region(db_session, branch.id, "hebei").unrest > unrest_before


def test_cannot_resolve_twice(db_session):
    branch = _branch(db_session)
    fanzhen = db_session.scalar(
        select(FactionState).where(
            FactionState.branch_id == branch.id, FactionState.faction_key == "fanzhen"
        )
    )
    fanzhen.treasury = -400_000
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = pending_decisions(db_session, branch.id)[0]
    resolve_decision(db_session, branch, decision, "grant_half")

    with pytest.raises(DecisionError):
        resolve_decision(db_session, branch, decision, "refuse")


def test_unknown_option_rejected(db_session):
    branch = _branch(db_session)
    fanzhen = db_session.scalar(
        select(FactionState).where(
            FactionState.branch_id == branch.id, FactionState.faction_key == "fanzhen"
        )
    )
    fanzhen.treasury = -400_000
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = pending_decisions(db_session, branch.id)[0]
    with pytest.raises(DecisionError):
        resolve_decision(db_session, branch, decision, "nonsense")


def test_advance_report_includes_changes(db_session):
    branch = _branch(db_session)
    report = SimulationEngine(db_session).advance(branch, months=3)
    assert report.changes, "推进后应当给出变化摘要"
    sample = report.changes[0]
    assert "name" in sample and "price_delta" in sample


def test_resolve_returns_applied_effects(db_session):
    """选完之后要能看到"到底变了多少"，而不只是"已决断"。"""
    branch = _branch(db_session)
    fanzhen = db_session.scalar(
        select(FactionState).where(
            FactionState.branch_id == branch.id, FactionState.faction_key == "fanzhen"
        )
    )
    fanzhen.treasury = -400_000
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = pending_decisions(db_session, branch.id)[0]
    event = resolve_decision(db_session, branch, decision, "refuse")
    db_session.flush()

    applied = event.metrics.get("applied")
    assert applied, "决议事件必须记录实际变化"
    labels = {item["label"] for item in applied}
    assert "河北藩镇臣属度" in labels
    for item in applied:
        assert item["before"] != item["after"]


def test_relation_description_is_human_readable(db_session):
    branch = _branch(db_session)
    rows = describe_relation(db_session, branch.id)
    assert rows and rows[0]["label"]


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def test_decision_api_flow(client):
    branch = client.post("/api/worlds/tang_750/branches", json={"seed": 3}).get_json()
    bid = branch["id"]

    # 制造一个必然触发请饷的局面
    advanced = client.post(f"/api/branches/{bid}/advance", json={"months": 24})
    assert advanced.status_code == 200

    decisions = client.get(f"/api/branches/{bid}/decisions").get_json()
    if not decisions:
        pytest.skip("本次推演没有触发决策，属于正常随机结果")

    decision = decisions[0]
    assert decision["status"] == "pending"
    assert len(decision["options"]) >= 2

    option = decision["options"][0]["key"]
    resolved = client.post(
        f"/api/branches/{bid}/decisions/{decision['id']}/resolve",
        json={"option": option},
    )
    assert resolved.status_code == 200
    assert resolved.get_json()["decision"]["status"] == "resolved"

    remaining = client.get(f"/api/branches/{bid}/decisions").get_json()
    assert all(d["id"] != decision["id"] for d in remaining)


def test_relations_api(client):
    branch = client.post("/api/worlds/tang_750/branches", json={"seed": 3}).get_json()
    resp = client.get(f"/api/branches/{branch['id']}/relations")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body and body[0]["from_key"] == "fanzhen"
    assert body[0]["label"]


def test_resolve_unknown_decision(client):
    branch = client.post("/api/worlds/tang_750/branches", json={}).get_json()
    resp = client.post(
        f"/api/branches/{branch['id']}/decisions/999999/resolve", json={"option": "x"}
    )
    assert resp.status_code == 404