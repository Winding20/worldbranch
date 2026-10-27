"""唐朝切片的结局与新增岔路口测试。"""

from __future__ import annotations

from sqlalchemy import select

from app.engine import SimulationEngine
from app.engine.decisions import resolve_decision
from app.engine.end_tang import TANG_HORIZON_MONTHS, evaluate_tang_ending
from app.models import Decision, RegionState
from app.services import create_branch, get_world_by_key


def _branch(session):
    world = get_world_by_key(session, "tang_755")
    return create_branch(session, world, name="唐结局测试", seed=5)


def _play(session, branch, *, fork_choice="historical", months=200):
    """一路推进，岔路口按指定策略选。fork_choice: historical / diverge"""
    from app.seed import anlushan_755

    expected = {e["key"] for e in anlushan_755.HISTORICAL_EVENTS}
    engine = SimulationEngine(session)
    for _ in range(24):
        report = engine.advance(branch, months=12)
        for item in report.history_forks:
            decision = session.get(Decision, item["id"])
            if decision is None or decision.status != "pending":
                continue
            want = "historical" if fork_choice == "historical" else None
            if want:
                option = next(
                    (o for o in decision.options if o.get("outcome") == "historical"),
                    decision.options[0],
                )
            else:
                option = next(
                    (o for o in decision.options if o.get("outcome") != "historical"),
                    decision.options[0],
                )
            resolve_decision(session, branch, decision, option["key"])
            session.flush()
        if branch.current_date.year >= 764:
            break
    return expected


def test_seven_forks_exist(db_session):
    world = get_world_by_key(db_session, "tang_755")
    forks = [e for e in world.historical_events if e.fork]
    assert len(forks) >= 6
    keys = {e.key for e in forks}
    assert {"tongguan_falls", "pursue_qingxu", "strip_guo_ziyi", "reward_warlords"} <= keys


def test_no_ending_before_horizon(db_session):
    branch = _branch(db_session)
    assert evaluate_tang_ending(db_session, branch) is None


def test_ending_after_eight_years(db_session):
    branch = _branch(db_session)
    _play(db_session, branch)
    ending = evaluate_tang_ending(db_session, branch)
    assert ending is not None
    assert 0 <= ending["score"] <= 100
    assert ending["grade"]
    assert set(ending["scores"]) == {"两京", "乱平", "府库", "威望", "民心", "河北"}


def test_following_history_ends_with_hebei_autonomous(db_session):
    """一路按史载走：乱平了，但河北成了藩镇，朝廷并未真正掌握。"""
    branch = _branch(db_session)
    _play(db_session, branch)
    ending = evaluate_tang_ending(db_session, branch)
    assert ending["metrics"]["rebellion_over"] is True
    assert ending["scores"]["河北"] == 40.0, "河北应为「名义归附而自专」"
    assert ending["metrics"]["autonomous_regions"], "应记录哪些州郡已成藩镇"
    assert ending["grade"] in {"克复", "苟安", "中兴"}


def test_diverging_improves_capital_score(db_session):
    """改道（不催战）保住潼关，两京分数应当更高。"""
    baseline = _branch(db_session)
    _play(db_session, baseline)
    base = evaluate_tang_ending(db_session, baseline)

    changed = _branch(db_session)
    _play(db_session, changed, fork_choice="diverge")
    alt = evaluate_tang_ending(db_session, changed)

    assert alt["scores"]["两京"] >= base["scores"]["两京"]


def test_reward_warlords_fork_appears(db_session):
    branch = _branch(db_session)
    _play(db_session, branch)
    fires = {
        f.ref_key
        for f in db_session.scalars(
            select(Decision).where(Decision.branch_id == branch.id)
        )
        if f.kind == "history_fork"
    }
    assert "reward_warlords" in fires, "平乱之后应当出现安置河北降将的抉择"


def test_character_dead_condition(db_session):
    from app.engine.history import check_conditions

    class P:
        def __init__(self, alive, name):
            self.alive = alive
            self.name = name

    ok, reason = check_conditions(
        {"character_dead": "shi_chaoyi"},
        regions={},
        characters={"shi_chaoyi": P(True, "史朝义")},
        armies={},
    )
    assert not ok and "尚在" in reason

    ok, _ = check_conditions(
        {"character_dead": "shi_chaoyi"},
        regions={},
        characters={"shi_chaoyi": P(False, "史朝义")},
        armies={},
    )
    assert ok


def test_ending_api_uses_tang_rules(client):
    branch = client.post(
        "/api/worlds/tang_755/branches", json={"seed": 5, "precision": "macro"}
    ).get_json()
    bid = branch["id"]

    early = client.get(f"/api/branches/{bid}/ending")
    assert early.status_code == 204

    for _ in range(40):
        body = client.post(f"/api/branches/{bid}/advance", json={"months": 12}).get_json()
        for item in body.get("history_forks", []):
            decision = client.get(f"/api/branches/{bid}/decisions").get_json()
            target = next((d for d in decision if d["id"] == item["id"]), None)
            if not target:
                continue
            option = next(
                (o for o in target["options"] if o.get("outcome") == "historical"),
                target["options"][0],
            )
            client.post(
                f"/api/branches/{bid}/decisions/{item['id']}/resolve",
                json={"option": option["key"]},
            )
        # 岔路口会打断推进，剩下的待决项也要处理掉，否则时间不会继续走
        leftovers = [
            d
            for d in client.get(f"/api/branches/{bid}/decisions").get_json()
            if d["kind"] == "history_fork"
        ]
        for target in leftovers:
            option = next(
                (o for o in target["options"] if o.get("outcome") == "historical"),
                target["options"][0],
            )
            client.post(
                f"/api/branches/{bid}/decisions/{target['id']}/resolve",
                json={"option": option["key"]},
            )
        if body["to_date"][:4] >= "764":
            break

    ending = client.get(f"/api/branches/{bid}/ending")
    assert ending.status_code == 200
    data = ending.get_json()
    assert "两京" in data["scores"]
    assert "rebellion_over" in data["metrics"]