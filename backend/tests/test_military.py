"""军事与人物参与推演的测试。"""

from __future__ import annotations

from sqlalchemy import select

from app.engine import SimulationEngine
from app.engine.decisions import pending_decisions, resolve_decision
from app.engine.military import (
    all_powers,
    army_power,
    candidates_for_command,
    odds,
    side_strength,
)
from app.models import ArmyState, CharacterState
from app.services import create_branch, get_world_by_key


def _branch(session):
    world = get_world_by_key(session, "tang_755")
    return create_branch(session, world, name="军力测试", seed=5)


def _army(session, branch_id, key):
    return session.scalar(
        select(ArmyState).where(
            ArmyState.branch_id == branch_id, ArmyState.army_key == key
        )
    )


def _char(session, branch_id, key):
    return session.scalar(
        select(CharacterState).where(
            CharacterState.branch_id == branch_id, CharacterState.character_key == key
        )
    )


def test_army_power_scales_with_commander_ability(db_session):
    branch = _branch(db_session)
    army = _army(db_session, branch.id, "shuofang_army")

    guo = _char(db_session, branch.id, "guo_ziyi")  # 能力 0.85
    bad = _char(db_session, branch.id, "yang_guozhong")  # 能力 0.30

    strong = army_power(army, guo)
    weak = army_power(army, bad)
    assert strong.power > weak.power

    # 无主帅时最弱
    none = army_power(army, None)
    assert none.power < weak.power
    assert none.commander_name == "无主帅"


def test_dead_commander_counts_as_no_commander(db_session):
    branch = _branch(db_session)
    army = _army(db_session, branch.id, "tongguan_army")
    geshu = _char(db_session, branch.id, "geshu_han")

    alive = army_power(army, geshu)
    geshu.alive = False
    db_session.flush()
    dead = army_power(army, geshu)

    assert dead.power < alive.power
    assert dead.commander_name == "无主帅"


def test_side_strength_and_odds(db_session):
    branch = _branch(db_session)
    armies = list(
        db_session.scalars(select(ArmyState).where(ArmyState.branch_id == branch.id))
    )
    characters = {
        c.character_key: c
        for c in db_session.scalars(
            select(CharacterState).where(CharacterState.branch_id == branch.id)
        )
    }
    tang = side_strength(armies, characters, "tang")
    yan = side_strength(armies, characters, "yan")
    assert tang > 0 and yan > 0

    assert odds(tang, tang) == 0.5
    assert odds(tang * 3, tang) > 0.85
    assert odds(tang / 3, tang) < 0.15


def test_candidates_sorted_by_ability(db_session):
    branch = _branch(db_session)
    characters = {
        c.character_key: c
        for c in db_session.scalars(
            select(CharacterState).where(CharacterState.branch_id == branch.id)
        )
    }
    pool = candidates_for_command(characters, "tang", limit=3)
    assert pool
    abilities = [c.ability for c in pool]
    assert abilities == sorted(abilities, reverse=True)
    assert all(c.faction_key == "tang" for c in pool)


def test_vacant_command_raises_appointment_decision(db_session):
    branch = _branch(db_session)
    # 让潼关守军失去主帅
    geshu = _char(db_session, branch.id, "geshu_han")
    geshu.alive = False
    db_session.flush()

    report = SimulationEngine(db_session).advance(branch, months=1)
    kinds = {d["kind"] for d in report.decisions}
    assert "appoint_commander" in kinds

    decision = next(
        d for d in pending_decisions(db_session, branch.id)
        if d.kind == "appoint_commander"
    )
    assert decision.ref_key == "tongguan_army"
    # 三个候选人 + 一个「暂不遣帅」
    assert len(decision.options) == 4
    assert decision.options[-1]["key"] == "appoint_none"


def test_appointing_changes_commander_and_power(db_session):
    branch = _branch(db_session)
    geshu = _char(db_session, branch.id, "geshu_han")
    geshu.alive = False
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = next(
        d for d in pending_decisions(db_session, branch.id)
        if d.kind == "appoint_commander"
    )

    army = _army(db_session, branch.id, "tongguan_army")
    characters = {
        c.character_key: c
        for c in db_session.scalars(
            select(CharacterState).where(CharacterState.branch_id == branch.id)
        )
    }
    before = army_power(army, characters.get(army.commander_key or "")).power

    target = decision.options[0]  # 能力最高的那位
    event = resolve_decision(db_session, branch, decision, target["key"])
    db_session.flush()

    assert army.commander_key is not None
    assert army.commander_key != "geshu_han"
    after = army_power(army, characters.get(army.commander_key or "")).power
    assert after > before

    labels = {item["label"] for item in event.metrics["applied"]}
    assert any("主帅" in label for label in labels)


def test_refusing_to_appoint_weakens_morale(db_session):
    branch = _branch(db_session)
    geshu = _char(db_session, branch.id, "geshu_han")
    geshu.alive = False
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = next(
        d for d in pending_decisions(db_session, branch.id)
        if d.kind == "appoint_commander"
    )
    army = _army(db_session, branch.id, "tongguan_army")
    before = army.morale

    resolve_decision(db_session, branch, decision, "appoint_none")
    db_session.flush()
    assert army.morale < before


def test_armies_api(client):
    branch = client.post("/api/worlds/tang_755/branches", json={"seed": 5}).get_json()
    resp = client.get(f"/api/branches/{branch['id']}/armies")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["armies"]
    assert body["tang_total"] > 0
    assert body["yan_total"] > 0
    sample = body["armies"][0]
    assert {"power", "commander_name", "troops"} <= set(sample)
    assert body["candidates"]


def test_power_ordering_matches_history(db_session):
    """同一支军队，郭子仪带出来的单位战力应高于仆固怀恩。"""
    branch = _branch(db_session)

    # 九节度之师要到 758 年才成军，这里直接补足兵额做对比
    yecheng = _army(db_session, branch.id, "yecheng_army")
    yecheng.raised = True
    yecheng.troops = 200_000
    shuofang = _army(db_session, branch.id, "shuofang_army")
    shuofang.raised = True
    db_session.flush()

    armies = [shuofang, yecheng]
    characters = {
        c.character_key: c
        for c in db_session.scalars(
            select(CharacterState).where(CharacterState.branch_id == branch.id)
        )
    }
    powers = {p.army_key: p for p in all_powers(armies, characters)}

    # 朔方军（郭子仪 0.85）单位兵力战力应高于九节度（仆固怀恩 0.72）
    assert (
        powers["shuofang_army"].power / powers["shuofang_army"].troops
        > powers["yecheng_army"].power / powers["yecheng_army"].troops
    )


def test_unraised_armies_have_no_power(db_session):
    """755 年开局时，回纥骑兵与九节度之师还不存在。"""
    branch = _branch(db_session)
    armies = list(
        db_session.scalars(select(ArmyState).where(ArmyState.branch_id == branch.id))
    )
    characters = {
        c.character_key: c
        for c in db_session.scalars(
            select(CharacterState).where(CharacterState.branch_id == branch.id)
        )
    }
    powers = {p.army_key: p for p in all_powers(armies, characters)}

    for key in ("huihu_cavalry", "yecheng_army"):
        army = next(a for a in armies if a.army_key == key)
        assert army.raised is False
        assert army.troops == 0
        assert powers[key].power == 0

    # 开局唐军战力不该把这两支算进去
    tang = side_strength(armies, characters, "tang")
    without = sum(
        p.power for k, p in powers.items() if k in {"tongguan_army", "shuofang_army",
                                                     "hedong_army", "suiyang_army"}
    )
    assert abs(tang - without) < 1


def test_armies_are_raised_on_schedule(db_session):
    """推进到 758 年，九节度之师应自动成军。"""
    from app.engine.decisions import resolve_decision
    from app.models import Decision

    branch = _branch(db_session)
    engine = SimulationEngine(db_session)

    # 途中有史实岔路口，会暂停推进；这里一路按史载走
    for _ in range(12):
        report = engine.advance(branch, months=12)
        for item in report.history_forks:
            decision = db_session.get(Decision, item["id"])
            if decision is None or decision.status != "pending":
                continue
            option = next(
                (o for o in decision.options if o.get("outcome") == "historical"),
                decision.options[0],
            )
            resolve_decision(db_session, branch, decision, option["key"])
            db_session.flush()
        if branch.current_date.year >= 758 and branch.current_date.month >= 10:
            break

    db_session.flush()
    yecheng = _army(db_session, branch.id, "yecheng_army")
    assert branch.current_date.year >= 758
    assert yecheng.raised is True
    assert yecheng.troops == 200_000