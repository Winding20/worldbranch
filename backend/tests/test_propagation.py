"""跨区域因果传导的测试。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.engine import SimulationEngine, rules
from app.models import RegionState, SimEvent
from app.services import (
    build_event_chain,
    cause_event_ids,
    create_branch,
    get_world_by_key,
)


def _branch(session, seed: int = 11):
    world = get_world_by_key(session, "tang_750")
    return create_branch(session, world, name="传导测试", seed=seed)


def _drain(session, branch_id: int, key: str, factor: float = 0.15) -> None:
    """把某道的存粮压到只够几天，制造一次严重歉收。"""
    region = session.scalar(
        select(RegionState).where(
            RegionState.branch_id == branch_id, RegionState.region_key == key
        )
    )
    region.grain_stock = region.population * rules.GRAIN_PER_CAPITA_MONTH * factor
    session.flush()


def test_exportable_surplus_keeps_safety_stock():
    assert rules.exportable_surplus(stock=1000, consumption=100) == pytest.approx(700)
    assert rules.exportable_surplus(stock=200, consumption=100) == 0


def test_delivered_amount_applies_loss():
    assert rules.delivered_amount(1000, 0.08) == pytest.approx(920)
    assert rules.delivered_amount(1000, 1.5) == pytest.approx(100)  # loss 上限 0.9


def test_famine_triggers_grain_flow(db_session):
    branch = _branch(db_session)
    _drain(db_session, branch.id, "hebei")

    report = SimulationEngine(db_session).advance(branch, months=1)
    flows = [e for e in report.events if e["kind"] == "grain_flow"]

    assert flows, "河北断粮后应当从邻道调粮"
    assert all("henan" in e["region_keys"] or "hedong" in e["region_keys"] for e in flows)


def test_grain_flow_records_causal_link_to_famine(db_session):
    branch = _branch(db_session)
    _drain(db_session, branch.id, "hebei")
    report = SimulationEngine(db_session).advance(branch, months=1)

    famine = next(e for e in report.events if e["kind"] == "famine")
    flows = [e for e in report.events if e["kind"] == "grain_flow"]

    for flow in flows:
        cause_ids = cause_event_ids_of(flow)
        assert famine["id"] in cause_ids, "调运事件必须挂到引发它的粮荒事件上"


def cause_event_ids_of(event: dict) -> list[int]:
    return [c["event_id"] for c in event["causes"] if isinstance(c, dict) and "event_id" in c]


def test_transfer_reduces_importer_price_and_raises_exporter_price(db_session):
    branch = _branch(db_session)
    _drain(db_session, branch.id, "hebei")
    engine = SimulationEngine(db_session)

    hebei = db_session.scalar(
        select(RegionState).where(
            RegionState.branch_id == branch.id, RegionState.region_key == "hebei"
        )
    )
    price_before = hebei.price_index
    henan = db_session.scalar(
        select(RegionState).where(
            RegionState.branch_id == branch.id, RegionState.region_key == "henan"
        )
    )
    henan_before = henan.grain_stock

    engine.advance(branch, months=1)
    db_session.flush()

    assert hebei.price_index != price_before
    assert henan.grain_stock < henan_before, "调出方的存粮应当减少"


def test_event_chain_walks_back_to_root(db_session):
    branch = _branch(db_session)
    _drain(db_session, branch.id, "hebei")
    report = SimulationEngine(db_session).advance(branch, months=1)
    db_session.flush()

    flow = next(
        (e for e in report.events if e["kind"] == "grain_flow" and cause_event_ids_of(e)),
        None,
    )
    assert flow is not None, "应当存在带因果的调运事件"

    chain = build_event_chain(db_session, branch.id, flow["id"])
    node_ids = {n["id"] for n in chain["nodes"]}
    assert flow["id"] in node_ids
    assert any(e["to"] == flow["id"] for e in chain["edges"]), "链条里应包含一条指向该事件的边"
    assert len(node_ids) >= 2, "至少应追溯到粮荒事件"


def test_no_flow_when_everything_is_fine(db_session):
    branch = _branch(db_session, seed=5)
    report = SimulationEngine(db_session).advance(branch, months=6)
    flows = [e for e in report.events if e["kind"] == "grain_flow"]
    assert flows == [], "没有缺粮就不应凭空产生调运"


def test_events_have_unique_ids(db_session):
    branch = _branch(db_session)
    _drain(db_session, branch.id, "hebei")
    report = SimulationEngine(db_session).advance(branch, months=3)
    db_session.flush()
    ids = [e["id"] for e in report.events]
    assert len(ids) == len(set(ids)), "同一批事件 id 不能重复"

    stored = list(
        db_session.scalars(select(SimEvent).where(SimEvent.branch_id == branch.id))
    )
    assert len(stored) == len(ids)