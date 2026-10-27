"""结局评估的测试。"""

from __future__ import annotations

from app.engine import SimulationEngine
from app.engine.ending import HORIZON_MONTHS, evaluate_ending
from app.services import create_branch, get_world_by_key


def _branch(session):
    world = get_world_by_key(session, "tang_750")
    return create_branch(session, world, name="结局测试", seed=3)


def test_no_ending_before_horizon(db_session):
    branch = _branch(db_session)
    SimulationEngine(db_session).advance(branch, months=12)
    assert evaluate_ending(db_session, branch) is None


def test_ending_after_horizon(db_session):
    branch = _branch(db_session)
    SimulationEngine(db_session).advance(branch, months=HORIZON_MONTHS)
    ending = evaluate_ending(db_session, branch)

    assert ending is not None
    assert ending["reached"] is True
    assert 0 <= ending["score"] <= 100
    assert ending["grade"]
    assert ending["verdict"]
    assert ending["months"] >= HORIZON_MONTHS
    assert set(ending["scores"]) == {"府库", "民心", "粮价", "藩镇", "威望"}


def test_ending_reflects_bad_state(db_session):
    branch = _branch(db_session)
    SimulationEngine(db_session).advance(branch, months=HORIZON_MONTHS)

    healthy = evaluate_ending(db_session, branch)

    # 人为把局势弄坏，再评估一次，分数必须下降
    from app.models import FactionState, RegionState
    from sqlalchemy import select

    tang = db_session.scalar(
        select(FactionState).where(
            FactionState.branch_id == branch.id, FactionState.faction_key == "tang"
        )
    )
    tang.treasury = -2_000_000
    tang.legitimacy = 0.1
    for region in db_session.scalars(
        select(RegionState).where(RegionState.branch_id == branch.id)
    ):
        region.unrest = 0.9
        region.price_index = 3.5
    db_session.flush()

    broken = evaluate_ending(db_session, branch)
    assert broken["score"] < healthy["score"]
    assert broken["grade"] in {"倾危", "崩坏"}


def test_ending_api(client):
    branch = client.post(
        "/api/worlds/tang_750/branches", json={"seed": 3, "precision": "macro"}
    ).get_json()
    bid = branch["id"]

    early = client.get(f"/api/branches/{bid}/ending")
    assert early.status_code == 204

    client.post(f"/api/branches/{bid}/advance", json={"months": HORIZON_MONTHS})
    late = client.get(f"/api/branches/{bid}/ending")
    assert late.status_code == 200
    body = late.get_json()
    assert body["reached"] is True
    assert body["grade"]