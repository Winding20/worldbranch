"""忠诚与离心的测试。"""

from __future__ import annotations

from sqlalchemy import select

from app.engine import SimulationEngine
from app.engine.decisions import pending_decisions, resolve_decision
from app.engine.loyalty import (
    DEFECT_LOYALTY,
    WARNING_LOYALTY,
    check_defection,
    loyalty_overview,
    monthly_drift,
)
from app.models import ArmyState, CharacterState, FactionState
from app.services import create_branch, get_world_by_key


def _branch(session):
    world = get_world_by_key(session, "tang_755")
    return create_branch(session, world, name="离心测试", seed=5)


def _maps(session, branch_id):
    armies = {
        a.army_key: a
        for a in session.scalars(
            select(ArmyState).where(ArmyState.branch_id == branch_id)
        )
    }
    characters = {
        c.character_key: c
        for c in session.scalars(
            select(CharacterState).where(CharacterState.branch_id == branch_id)
        )
    }
    tang = session.scalar(
        select(FactionState).where(
            FactionState.branch_id == branch_id, FactionState.faction_key == "tang"
        )
    )
    return armies, characters, tang


def test_drift_makes_loyalty_fall_over_time(db_session):
    branch = _branch(db_session)
    armies, characters, tang = _maps(db_session, branch.id)
    guo = characters["guo_ziyi"]
    before = guo.loyalty

    for _ in range(12):
        monthly_drift(characters, armies, tang)
    assert guo.loyalty < before


def test_high_power_share_accelerates_loss(db_session):
    """功高者流失得更快：给两支军队换主帅再比较。"""
    branch = _branch(db_session)
    armies, characters, tang = _maps(db_session, branch.id)

    # 让李光弼同时统两支大军
    armies["shuofang_army"].commander_key = "li_guangbi"
    li = characters["li_guangbi"]
    guo = characters["guo_ziyi"]
    del guo

    start = li.loyalty
    for _ in range(12):
        monthly_drift(characters, armies, tang)
    with_power = start - li.loyalty

    # 对照：把军队交还，重新跑
    armies["shuofang_army"].commander_key = "guo_ziyi"
    li.loyalty = start
    for _ in range(12):
        monthly_drift(characters, armies, tang)
    without_power = start - li.loyalty

    assert with_power > without_power


def test_defection_requires_low_loyalty_and_ambition(db_session):
    branch = _branch(db_session)
    armies, characters, _ = _maps(db_session, branch.id)

    guo = characters["guo_ziyi"]
    guo.loyalty = 0.05  # 极低，但野心只有 0.10
    assert check_defection(db_session, branch, characters, armies) == []

    guo.ambition = 0.9
    results = check_defection(db_session, branch, characters, armies)
    # 郭子仪虽统兵，但 loyalty 已低于阈值、ambition 上去了 → 会叛
    assert results
    assert results[0]["character_key"] == "guo_ziyi"


def test_defection_moves_army_and_region(db_session):
    branch = _branch(db_session)
    armies, characters, _ = _maps(db_session, branch.id)

    pugu = characters["pugu_huai_en"]
    pugu.loyalty = 0.05
    pugu.ambition = 0.9
    pugu.location_region_key = "lingwu"
    # 九节度之师 758 年才成军，这里先补足兵额
    armies["yecheng_army"].raised = True
    armies["yecheng_army"].troops = armies["yecheng_army"].troops_max or 200_000

    results = check_defection(db_session, branch, characters, armies)
    assert results
    item = results[0]
    assert item["troops"] > 0
    assert armies["yecheng_army"].faction_key == "yan"
    assert pugu.faction_key == "yan"


def test_defector_leaves_tang_pool(db_session):
    branch = _branch(db_session)
    armies, characters, _ = _maps(db_session, branch.id)
    pugu = characters["pugu_huai_en"]
    pugu.loyalty = 0.05
    pugu.ambition = 0.9
    armies["yecheng_army"].raised = True
    armies["yecheng_army"].troops = armies["yecheng_army"].troops_max or 200_000

    check_defection(db_session, branch, characters, armies)
    rows = loyalty_overview(characters, armies)
    row = next(r for r in rows if r["key"] == "pugu_huai_en")
    assert row["status"] == "已叛"


def test_overview_status_labels(db_session):
    branch = _branch(db_session)
    armies, characters, _ = _maps(db_session, branch.id)

    characters["guo_ziyi"].loyalty = 0.10
    characters["li_guangbi"].loyalty = 0.40
    rows = {r["key"]: r for r in loyalty_overview(characters, armies)}

    assert rows["guo_ziyi"]["status"] == "将叛"
    assert rows["li_guangbi"]["status"] == "拥兵自重"
    assert rows["zhang_xun"]["status"] in {"恭顺", "功高"}


def test_reward_decision_raised_for_wavering_general(db_session):
    branch = _branch(db_session)
    armies, characters, _ = _maps(db_session, branch.id)
    characters["guo_ziyi"].loyalty = (DEFECT_LOYALTY + WARNING_LOYALTY) / 2
    db_session.flush()

    report = SimulationEngine(db_session).advance(branch, months=1)
    kinds = {d["kind"] for d in report.decisions}
    assert "reward_general" in kinds


def test_reward_raises_loyalty_but_costs(db_session):
    branch = _branch(db_session)
    armies, characters, tang = _maps(db_session, branch.id)
    characters["guo_ziyi"].loyalty = (DEFECT_LOYALTY + WARNING_LOYALTY) / 2
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = next(
        d for d in pending_decisions(db_session, branch.id)
        if d.kind == "reward_general"
    )
    before_loyalty = characters["guo_ziyi"].loyalty
    before_treasury = tang.treasury

    resolve_decision(db_session, branch, decision, "reward")
    db_session.flush()

    assert characters["guo_ziyi"].loyalty > before_loyalty
    assert tang.treasury < before_treasury


def test_stripping_command_disarms_army(db_session):
    branch = _branch(db_session)
    armies, characters, _ = _maps(db_session, branch.id)
    characters["guo_ziyi"].loyalty = (DEFECT_LOYALTY + WARNING_LOYALTY) / 2
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = next(
        d for d in pending_decisions(db_session, branch.id)
        if d.kind == "reward_general"
    )
    army = armies["shuofang_army"]
    before_troops = army.troops
    before_loyalty = characters["guo_ziyi"].loyalty

    resolve_decision(db_session, branch, decision, "strip_command")
    db_session.flush()

    assert army.commander_key is None
    assert army.troops < before_troops
    assert characters["guo_ziyi"].loyalty < before_loyalty


def test_loyalty_api(client):
    branch = client.post("/api/worlds/tang_755/branches", json={"seed": 5}).get_json()
    resp = client.get(f"/api/branches/{branch['id']}/loyalty")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert rows
    assert {"name", "loyalty", "status", "troops", "share"} <= set(rows[0])