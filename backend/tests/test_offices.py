"""官职机制测试：品级、统兵资格、迁转后果。"""

from __future__ import annotations

from sqlalchemy import select

from app.engine import SimulationEngine
from app.engine.decisions import pending_decisions, resolve_decision
from app.engine.loyalty import DEFECT_LOYALTY, WARNING_LOYALTY, loyalty_overview
from app.engine.offices import (
    CHANCELLOR,
    SINECURE,
    apply_office,
    can_command,
    kind_label,
    rank_label,
)
from app.models import ArmyState, CharacterState
from app.services import create_branch, get_world_by_key


def _branch(session):
    world = get_world_by_key(session, "tang_755")
    return create_branch(session, world, name="官职测试", seed=5)


def _char(session, branch_id, key):
    return session.scalar(
        select(CharacterState).where(
            CharacterState.branch_id == branch_id,
            CharacterState.character_key == key,
        )
    )


def test_characters_have_rank_and_kind(db_session):
    branch = _branch(db_session)
    guo = _char(db_session, branch.id, "guo_ziyi")
    assert guo.office_rank == 3
    assert guo.office_kind == "military"
    assert can_command(guo)

    yu = _char(db_session, branch.id, "yu_chaoen")
    assert yu.office_kind == "envoy"
    assert can_command(yu)

    yang = _char(db_session, branch.id, "yang_guozhong")
    assert yang.office_kind == "civil"
    assert not can_command(yang), "文职不统兵"


def test_sinecure_cannot_command(db_session):
    branch = _branch(db_session)
    geshu = _char(db_session, branch.id, "geshu_han")
    assert can_command(geshu)

    change = apply_office(geshu, **SINECURE)
    db_session.flush()

    assert geshu.office == SINECURE["title"]
    assert geshu.office_kind == "sinecure"
    assert not can_command(geshu)
    assert change.before != change.after
    assert change.rank_after == 2


def test_rank_and_kind_labels():
    assert rank_label(2) == "二品"
    assert kind_label("sinecure") == "闲职"
    assert CHANCELLOR["kind"] == "civil"


def test_stripping_command_changes_office(db_session):
    branch = _branch(db_session)
    guo = _char(db_session, branch.id, "guo_ziyi")
    guo.loyalty = (DEFECT_LOYALTY + WARNING_LOYALTY) / 2
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = next(
        d for d in pending_decisions(db_session, branch.id)
        if d.kind == "reward_general"
    )
    resolve_decision(db_session, branch, decision, "strip_command")
    db_session.flush()

    assert guo.office == SINECURE["title"]
    assert guo.office_kind == "sinecure"
    assert not can_command(guo)

    army = db_session.scalar(
        select(ArmyState).where(
            ArmyState.branch_id == branch.id, ArmyState.army_key == "shuofang_army"
        )
    )
    assert army.commander_key is None


def test_reward_promotes_to_chancellor(db_session):
    branch = _branch(db_session)
    guo = _char(db_session, branch.id, "guo_ziyi")
    guo.loyalty = (DEFECT_LOYALTY + WARNING_LOYALTY) / 2
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = next(
        d for d in pending_decisions(db_session, branch.id)
        if d.kind == "reward_general"
    )
    before_rank = guo.office_rank
    resolve_decision(db_session, branch, decision, "reward")
    db_session.flush()

    assert guo.office == "同中书门下平章事"
    assert guo.office_rank <= before_rank
    # 加官后仍是文职，兵权在名义上已被转走
    assert guo.office_kind == "civil"


def test_office_change_appears_in_applied(db_session):
    branch = _branch(db_session)
    guo = _char(db_session, branch.id, "guo_ziyi")
    guo.loyalty = (DEFECT_LOYALTY + WARNING_LOYALTY) / 2
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = next(
        d for d in pending_decisions(db_session, branch.id)
        if d.kind == "reward_general"
    )
    event = resolve_decision(db_session, branch, decision, "strip_command")
    labels = {item["label"] for item in event.metrics["applied"]}
    assert "郭子仪官职" in labels


def test_overview_includes_office_meta(db_session):
    branch = _branch(db_session)
    armies = {
        a.army_key: a
        for a in db_session.scalars(
            select(ArmyState).where(ArmyState.branch_id == branch.id)
        )
    }
    chars = {
        c.character_key: c
        for c in db_session.scalars(
            select(CharacterState).where(CharacterState.branch_id == branch.id)
        )
    }
    rows = {r["key"]: r for r in loyalty_overview(chars, armies)}
    assert rows["guo_ziyi"]["office_rank"] == 3
    assert rows["guo_ziyi"]["office_kind"] == "military"


def test_loyalty_api_exposes_office(client):
    branch = client.post("/api/worlds/tang_755/branches", json={"seed": 5}).get_json()
    rows = client.get(f"/api/branches/{branch['id']}/loyalty").get_json()
    assert rows[0]["office_rank"] >= 1
    assert rows[0]["office_kind"]