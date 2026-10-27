"""引擎层测试：时间推进、确定性、分支隔离、快照。"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.engine import SimulationEngine
from app.engine.simulation import add_months
from app.models import RegionState, SimEvent, Snapshot
from app.services import create_branch, fork_branch, get_world_by_key


def _tang_branch(session, *, seed: int = 1, precision: str = "standard"):
    world = get_world_by_key(session, "tang_750")
    return create_branch(session, world, precision=precision, seed=seed)


def test_add_months_handles_year_boundary():
    assert add_months(dt.date(750, 1, 1), 1) == dt.date(750, 2, 1)
    assert add_months(dt.date(750, 12, 1), 1) == dt.date(751, 1, 1)
    assert add_months(dt.date(750, 1, 31), 1) == dt.date(750, 2, 28)


def test_advance_moves_date_and_tick(db_session):
    branch = _tang_branch(db_session)
    assert branch.tick_index == 0
    report = SimulationEngine(db_session).advance(branch, months=3)
    assert branch.tick_index == 3
    assert report.from_date == dt.date(750, 1, 1)
    assert report.to_date == dt.date(750, 4, 1)
    assert len(report.region_states) == 7


def test_advance_updates_region_state(db_session):
    branch = _tang_branch(db_session)
    before = {
        r.region_key: r.grain_stock
        for r in db_session.scalars(
            select(RegionState).where(RegionState.branch_id == branch.id)
        )
    }
    SimulationEngine(db_session).advance(branch, months=1)
    db_session.flush()
    after = {
        r.region_key: r.grain_stock
        for r in db_session.scalars(
            select(RegionState).where(RegionState.branch_id == branch.id)
        )
    }
    # 1 月是青黄不接的月份，存粮应有变化
    assert after != before


def test_snapshot_saved_per_tick(db_session):
    branch = _tang_branch(db_session)
    SimulationEngine(db_session).advance(branch, months=2)
    db_session.flush()
    snaps = list(
        db_session.scalars(
            select(Snapshot).where(Snapshot.branch_id == branch.id)
        )
    )
    assert len(snaps) == 2
    assert {s.tick_index for s in snaps} == {1, 2}


def test_same_seed_is_reproducible(db_session):
    a = _tang_branch(db_session, seed=42)
    b = _tang_branch(db_session, seed=42)
    engine = SimulationEngine(db_session)
    ra = engine.advance(a, months=12)
    rb = engine.advance(b, months=12)

    key = lambda e: (e["game_date"], e["kind"], e["title"])  # noqa: E731
    assert [key(e) for e in ra.events] == [key(e) for e in rb.events]


def test_different_seed_diverges(db_session):
    a = _tang_branch(db_session, seed=1)
    b = _tang_branch(db_session, seed=999)
    engine = SimulationEngine(db_session)
    ra = engine.advance(a, months=24)
    rb = engine.advance(b, months=24)
    key = lambda e: (e["game_date"], e["kind"], e["title"])  # noqa: E731
    assert [key(e) for e in ra.events] != [key(e) for e in rb.events]


def test_fork_is_isolated(db_session):
    source = _tang_branch(db_session, seed=7)
    engine = SimulationEngine(db_session)
    engine.advance(source, months=6)

    fork = fork_branch(db_session, source, name="对照分支")
    assert fork.current_date == source.current_date
    fork_stock = {
        r.region_key: r.grain_stock
        for r in db_session.scalars(
            select(RegionState).where(RegionState.branch_id == fork.id)
        )
    }

    engine.advance(source, months=6)

    db_session.flush()
    fork_stock_after = {
        r.region_key: r.grain_stock
        for r in db_session.scalars(
            select(RegionState).where(RegionState.branch_id == fork.id)
        )
    }
    assert fork_stock_after == fork_stock, "推进源分支不应改变派生分支"
    assert fork.current_date != source.current_date


def test_fork_inherits_history_up_to_fork_point(db_session):
    source = _tang_branch(db_session, seed=11)
    engine = SimulationEngine(db_session)
    engine.advance(source, months=12)
    db_session.flush()

    source_events = list(
        db_session.scalars(select(SimEvent).where(SimEvent.branch_id == source.id))
    )
    fork = fork_branch(db_session, source)
    db_session.flush()

    fork_events = list(
        db_session.scalars(select(SimEvent).where(SimEvent.branch_id == fork.id))
    )
    assert len(fork_events) == len(source_events)
    assert {e.tick_index for e in fork_events} == {e.tick_index for e in source_events}

    # 派生之后各自新增的事件互不影响
    engine.advance(fork, months=6)
    db_session.flush()
    fork_after = list(
        db_session.scalars(select(SimEvent).where(SimEvent.branch_id == fork.id))
    )
    source_after = list(
        db_session.scalars(select(SimEvent).where(SimEvent.branch_id == source.id))
    )
    assert len(source_after) == len(source_events)
    assert len(fork_after) >= len(fork_events)


def test_precision_filters_event_detail(db_session):
    macro = _tang_branch(db_session, seed=5, precision="macro")
    deep = _tang_branch(db_session, seed=5, precision="deep")
    engine = SimulationEngine(db_session)
    engine.advance(macro, months=12)
    engine.advance(deep, months=12)
    db_session.flush()

    macro_events = list(
        db_session.scalars(select(SimEvent).where(SimEvent.branch_id == macro.id))
    )
    deep_events = list(
        db_session.scalars(select(SimEvent).where(SimEvent.branch_id == deep.id))
    )
    assert len(deep_events) >= len(macro_events)
    assert all(e.severity >= 3 for e in macro_events)


def test_events_carry_causes_and_scope(db_session):
    branch = _tang_branch(db_session, seed=3)
    SimulationEngine(db_session).advance(branch, months=24)
    db_session.flush()
    events = list(
        db_session.scalars(select(SimEvent).where(SimEvent.branch_id == branch.id))
    )
    assert events, "24 个月内应产生事件"
    for e in events:
        assert e.scope in {"local", "region", "nation", "world"}
        assert 1 <= e.severity <= 5
        assert isinstance(e.causes, list) and e.causes