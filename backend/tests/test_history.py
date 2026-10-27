"""唐史切片（755–763）的数据与史实事件测试。"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from app.engine import SimulationEngine
from app.engine.history import check_conditions, run_historical_events
from app.models import (
    ArmyState,
    CharacterState,
    HistoricalEvent,
    HistoricalFire,
    RegionState,
)
from app.services import create_branch, get_world_by_key


def _world(session):
    world = get_world_by_key(session, "tang_755")
    if world is None:
        from app.seed import anlushan_755

        world = anlushan_755.seed(session)
        session.flush()
    return world


def _branch(session, **kw):
    world = _world(session)
    return create_branch(session, world, name="安史之乱测试", seed=5, **kw)


def test_world_has_characters_armies_events(db_session):
    world = _world(db_session)
    assert len(world.characters) >= 10
    assert len(world.armies) >= 5
    assert len(world.historical_events) >= 8
    assert world.scenario["role"]


def test_branch_copies_character_and_army_state(db_session):
    branch = _branch(db_session)
    people = list(
        db_session.scalars(
            select(CharacterState).where(CharacterState.branch_id == branch.id)
        )
    )
    armies = list(
        db_session.scalars(select(ArmyState).where(ArmyState.branch_id == branch.id))
    )
    world = _world(db_session)
    assert len(people) == len(world.characters)
    assert len(armies) == len(world.armies)

    an = next(p for p in people if p.character_key == "an_lushan")
    assert an.alive is True
    assert an.faction_key == "yan"


def test_character_death_in_one_branch_does_not_affect_another(db_session):
    world = _world(db_session)
    a = create_branch(db_session, world, name="A", seed=1)
    b = create_branch(db_session, world, name="B", seed=1)

    an_a = db_session.scalar(
        select(CharacterState).where(
            CharacterState.branch_id == a.id,
            CharacterState.character_key == "an_lushan",
        )
    )
    an_a.alive = False
    db_session.flush()

    an_b = db_session.scalar(
        select(CharacterState).where(
            CharacterState.branch_id == b.id,
            CharacterState.character_key == "an_lushan",
        )
    )
    assert an_b.alive is True


def test_start_date_is_november_755(db_session):
    branch = _branch(db_session)
    assert branch.current_date == dt.date(755, 11, 1)
    world = _world(db_session)
    assert world.name == "安史之乱"


def test_first_event_fires_when_reaching_its_month(db_session):
    branch = _branch(db_session)
    SimulationEngine(db_session).advance(branch, months=1)

    fires = list(
        db_session.scalars(
            select(HistoricalFire).where(HistoricalFire.branch_id == branch.id)
        )
    )
    keys = {f.event_key for f in fires}
    assert "uprising_fanyang" in keys
    assert any(f.status == "fired" for f in fires)


def test_event_diverges_when_condition_unmet(db_session):
    branch = _branch(db_session)
    # 安禄山提前死掉，范阳起兵就不该发生
    an = db_session.scalar(
        select(CharacterState).where(
            CharacterState.branch_id == branch.id,
            CharacterState.character_key == "an_lushan",
        )
    )
    an.alive = False
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)

    fire = db_session.scalar(
        select(HistoricalFire).where(
            HistoricalFire.branch_id == branch.id,
            HistoricalFire.event_key == "uprising_fanyang",
        )
    )
    assert fire is not None
    assert fire.status == "diverged"
    assert "安禄山" in fire.note


def test_condition_helpers():
    class R:
        def __init__(self, key, name, faction):
            self.region_key, self.name, self.faction_key = key, name, faction

    class C:
        def __init__(self, alive, name="安禄山"):
            self.alive = alive
            self.name = name

    regions = {"luoyang": R("luoyang", "河南府", "tang")}
    ok, reason = check_conditions(
        {"region_held": "luoyang"}, regions=regions, characters={}, armies={}
    )
    assert ok and reason == ""

    regions["luoyang"].faction_key = "yan"
    ok, reason = check_conditions(
        {"region_held": "luoyang"}, regions=regions, characters={}, armies={}
    )
    assert not ok and "已失" in reason

    ok, reason = check_conditions(
        {"character_alive": "an_lushan"},
        regions=regions,
        characters={"an_lushan": C(False)},
        armies={},
    )
    assert not ok


def test_events_do_not_repeat(db_session):
    branch = _branch(db_session)
    engine = SimulationEngine(db_session)
    engine.advance(branch, months=1)
    first = len(
        list(
            db_session.scalars(
                select(HistoricalFire).where(HistoricalFire.branch_id == branch.id)
            )
        )
    )
    engine.advance(branch, months=1)
    second = len(
        list(
            db_session.scalars(
                select(HistoricalFire).where(HistoricalFire.branch_id == branch.id)
            )
        )
    )
    # 已发生的事件不会重复记录
    keys = [
        f.event_key
        for f in db_session.scalars(
            select(HistoricalFire).where(HistoricalFire.branch_id == branch.id)
        )
    ]
    assert len(keys) == len(set(keys))
    assert second >= first


def test_historical_events_template_all_have_conditions_and_source(db_session):
    world = _world(db_session)
    for event in world.historical_events:
        assert event.source, f"{event.key} 缺少出处"
        assert event.conditions is not None, f"{event.key} 缺少触发条件"
        assert event.divergence_note, f"{event.key} 缺少改道说明"


def test_history_api(client):
    branch = client.post("/api/worlds/tang_755/branches", json={"seed": 5}).get_json()
    bid = branch["id"]
    client.post(f"/api/branches/{bid}/advance", json={"months": 1})
    resp = client.get(f"/api/branches/{bid}/history")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "fired" in body and "diverged" in body
    assert any(item["key"] == "uprising_fanyang" for item in body["fired"])