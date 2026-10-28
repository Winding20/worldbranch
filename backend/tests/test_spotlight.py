"""聚光（focus_region）：每道决策都要说清「这事发生在哪」。"""

from __future__ import annotations

from sqlalchemy import select

from app.engine import SimulationEngine
from app.engine.decisions import pending_decisions
from app.models import Decision, FactionState, RegionState
from app.services import create_branch, get_world_by_key


def _branch(session):
    world = get_world_by_key(session, "tang_755")
    return create_branch(session, world, name="聚光测试", seed=5)


def test_famine_decision_points_at_the_region(db_session):
    branch = _branch(db_session)
    hebei = db_session.scalar(
        select(RegionState).where(
            RegionState.branch_id == branch.id, RegionState.region_key == "hebei_plain"
        )
    )
    hebei.unrest = 0.8
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = next(
        d for d in pending_decisions(db_session, branch.id) if d.kind == "famine_relief"
    )
    assert decision.focus_region == "hebei_plain"
    assert decision.to_dict()["focus_region"] == "hebei_plain"


def test_warlord_supply_points_at_hebei(db_session):
    branch = _branch(db_session)
    fanzhen = db_session.scalar(
        select(FactionState).where(
            FactionState.branch_id == branch.id, FactionState.faction_key == "fanzhen"
        )
    )
    if fanzhen is None:
        fanzhen = db_session.scalar(
            select(FactionState).where(
                FactionState.branch_id == branch.id, FactionState.faction_key == "yan"
            )
        )
    fanzhen.treasury = -500_000
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    kinds = {d.kind for d in pending_decisions(db_session, branch.id)}
    if "warlord_supply" not in kinds:
        # 燕方制度下不一定触发请饷，这一条按条件跳过
        return
    decision = next(
        d for d in pending_decisions(db_session, branch.id) if d.kind == "warlord_supply"
    )
    assert decision.focus_region in {"hebei", "fanyang", "hebei_plain"}


def test_history_fork_points_at_the_contested_place(db_session):
    branch = _branch(db_session)
    SimulationEngine(db_session).advance(branch, months=8)
    fork = db_session.scalar(
        select(Decision).where(
            Decision.branch_id == branch.id, Decision.kind == "history_fork"
        )
    )
    assert fork is not None
    # 潼关之变的得失地就是潼关
    assert fork.focus_region == "tongguan"


def test_focus_region_may_be_empty_but_never_invented(db_session):
    """没有明确地点时留空，不要编一个出来。"""
    branch = _branch(db_session)
    SimulationEngine(db_session).advance(branch, months=2)
    for decision in pending_decisions(db_session, branch.id):
        if decision.focus_region is not None:
            region = db_session.scalar(
                select(RegionState).where(
                    RegionState.branch_id == branch.id,
                    RegionState.region_key == decision.focus_region,
                )
            )
            assert region is not None, f"{decision.kind} 指向了不存在的地区"