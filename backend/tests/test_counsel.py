"""进谏系统的测试。

要点：建议必须可解释（带依据）、可复现（同状态同结果）、
并且不能凭空出现（没有可用人物时留空）。
"""

from __future__ import annotations

from sqlalchemy import select

from app.engine import SimulationEngine
from app.engine.counsel import advise, attach_advice
from app.engine.decisions import pending_decisions, resolve_decision
from app.models import CharacterState, Decision
from app.services import create_branch, get_world_by_key


def _branch(session):
    world = get_world_by_key(session, "tang_755")
    return create_branch(session, world, name="进谏测试", seed=5)


def _characters(session, branch_id):
    return {
        c.character_key: c
        for c in session.scalars(
            select(CharacterState).where(CharacterState.branch_id == branch_id)
        )
    }


def _simple_decision(options):
    decision = Decision(
        kind="test",
        title="测试",
        description="",
        options=options,
        tick_index=0,
    )
    return decision


def test_advice_has_evidence_fields(db_session):
    branch = _branch(db_session)
    characters = _characters(db_session, branch.id)
    decision = _simple_decision(
        [
            {"key": "a", "label": "甲案", "detail": "", "effects": {"treasury": -100_000}},
            {"key": "b", "label": "乙案", "detail": "", "effects": {"legitimacy": 0.05}},
        ]
    )
    advice = advise(decision, characters)
    assert advice
    for item in advice:
        assert item["name"]
        assert item["option_key"] in {"a", "b"}
        assert 0 <= item["ability"] <= 1
        assert 0 <= item["loyalty"] <= 1
        assert item["text"]


def test_no_advice_without_characters():
    decision = _simple_decision([{"key": "a", "label": "甲案", "detail": "", "effects": {}}])
    assert advise(decision, {}) == []


def test_dead_characters_do_not_advise(db_session):
    branch = _branch(db_session)
    characters = _characters(db_session, branch.id)
    decision = _simple_decision(
        [{"key": "a", "label": "甲案", "detail": "", "effects": {"legitimacy": 0.05}}]
    )
    before = {a["character_key"] for a in advise(decision, characters)}

    for key in before:
        characters[key].alive = False
    db_session.flush()

    after = {a["character_key"] for a in advise(decision, characters)}
    assert not (before & after)


def test_generals_and_ministers_prefer_different_options(db_session):
    """武将看图军心，文臣看度支名分，两者应能给出不同选择。"""
    branch = _branch(db_session)
    characters = _characters(db_session, branch.id)

    decision = _simple_decision(
        [
            {
                "key": "spend_for_morale",
                "label": "厚赏以励军",
                "detail": "",
                "effects": {"treasury": -800_000, "morale": {"shuofang_army": 0.15}},
            },
            {
                "key": "save_money",
                "label": "省费以充府库",
                "detail": "",
                "effects": {"treasury": 300_000, "legitimacy": 0.03},
            },
        ]
    )
    advice = advise(decision, characters)
    by_role = {}
    for item in advice:
        by_role.setdefault(item["role"], set()).add(item["option_key"])

    assert by_role.get("general") == {"spend_for_morale"}
    assert by_role.get("minister") == {"save_money"}


def test_advice_is_deterministic(db_session):
    branch = _branch(db_session)
    characters = _characters(db_session, branch.id)
    decision = _simple_decision(
        [
            {"key": "a", "label": "甲案", "detail": "", "effects": {"treasury": -100_000}},
            {"key": "b", "label": "乙案", "detail": "", "effects": {"legitimacy": 0.05}},
        ]
    )
    first = advise(decision, characters)
    second = advise(decision, characters)
    assert first == second


def test_advice_attached_to_raised_decisions(db_session):
    """引擎抛出的决策应当带上朝臣意见。"""
    branch = _branch(db_session)
    geshu = db_session.scalar(
        select(CharacterState).where(
            CharacterState.branch_id == branch.id,
            CharacterState.character_key == "geshu_han",
        )
    )
    geshu.alive = False
    db_session.flush()

    SimulationEngine(db_session).advance(branch, months=1)
    decision = next(
        d for d in pending_decisions(db_session, branch.id)
        if d.kind == "appoint_commander"
    )
    assert decision.advice, "任命主帅的决策应当有人进言"
    for item in decision.advice:
        assert item["option_key"] in {o["key"] for o in decision.options}


def test_advice_attached_to_history_forks(db_session):
    branch = _branch(db_session)
    SimulationEngine(db_session).advance(branch, months=8)
    decision = db_session.scalar(
        select(Decision).where(
            Decision.branch_id == branch.id,
            Decision.kind == "history_fork",
        )
    )
    assert decision is not None
    assert decision.advice, "潼关岔路口应当有人进言"
    # 建议必须指向真实存在的选项
    valid = {o["key"] for o in decision.options}
    assert all(item["option_key"] in valid for item in decision.advice)


def test_advice_survives_resolution(db_session):
    branch = _branch(db_session)
    SimulationEngine(db_session).advance(branch, months=8)
    decision = db_session.scalar(
        select(Decision).where(
            Decision.branch_id == branch.id,
            Decision.kind == "history_fork",
        )
    )
    saved = list(decision.advice)
    resolve_decision(db_session, branch, decision, "hold_position")
    db_session.flush()
    assert decision.advice == saved, "决断之后建议仍应留存，供事后复盘"


def test_historical_option_uses_event_effects(db_session):
    """按史载的选项要按史实事件的效果来评判，不能当成"不花代价"。"""
    from app.engine.counsel import effective_effects
    from app.models import HistoricalEvent

    event = HistoricalEvent(
        key="x",
        date=None,
        title="失守",
        effects={"treasury": -250_000, "lose_region": "tongguan", "legitimacy": -0.1},
    )
    hist = {"key": "go", "label": "出战", "outcome": "historical"}
    other = {"key": "stay", "label": "坚守", "effects": {"treasury": -400_000}}
    assert effective_effects(hist, event)["treasury"] == -250_000
    assert effective_effects(other, event)["treasury"] == -400_000


def test_generals_oppose_losing_a_fortress(db_session):
    """武将不应推荐"弃守"——这条是潼关那次的实际教训。"""
    from app.engine.counsel import advise
    from app.models import HistoricalEvent

    branch = _branch(db_session)
    characters = _characters(db_session, branch.id)

    event = HistoricalEvent(
        key="tongguan_falls",
        date=None,
        title="潼关失守",
        effects={"lose_region": "tongguan", "treasury": -250_000, "legitimacy": -0.10},
    )
    decision = _simple_decision(
        [
            {"key": "order_attack", "label": "遣使催战", "outcome": "historical"},
            {
                "key": "hold_position",
                "label": "令其坚守",
                "effects": {
                    "treasury": -400_000,
                    "legitimacy": 0.04,
                    "morale": {"tongguan_army": -0.05},
                },
            },
        ]
    )
    advice = advise(decision, characters, event=event)
    generals = [a for a in advice if a["role"] == "general"]
    assert generals
    assert all(a["option_key"] == "hold_position" for a in generals)


def test_ambitious_character_may_diverge(db_session):
    """野心大的人可以和老成持重者意见相左。"""
    from app.engine.counsel import _utility
    from app.models import CharacterState

    effects_gain_morale = {"treasury": -500_000, "morale": {"shuofang_army": 0.2}}

    loyal = CharacterState(
        character_key="a", name="忠将", role="general", ability=0.8,
        loyalty=0.95, ambition=0.1, faction_key="tang",
    )
    ambitious = CharacterState(
        character_key="b", name="枭将", role="general", ability=0.8,
        loyalty=0.45, ambition=0.9, faction_key="tang",
    )
    # 同样一件事：军心上涨。忠将乐见，枭将未必。
    assert _utility(loyal, effects_gain_morale) > _utility(ambitious, effects_gain_morale)


def test_consensus_flag():
    import datetime as dt

    from app.models import Decision

    same = Decision(
        game_date=dt.date(756, 6, 1),
        options=[{"key": "a"}, {"key": "b"}],
        advice=[{"option_key": "a"}, {"option_key": "a"}],
    )
    split = Decision(
        game_date=dt.date(756, 6, 1),
        options=[{"key": "a"}, {"key": "b"}],
        advice=[{"option_key": "a"}, {"option_key": "b"}],
    )
    assert same.to_dict()["advice_consensus"] is True
    assert split.to_dict()["advice_consensus"] is False


def test_advice_api_shape(client):
    branch = client.post("/api/worlds/tang_755/branches", json={"seed": 5}).get_json()
    bid = branch["id"]
    client.post(f"/api/branches/{bid}/advance", json={"months": 8})
    decisions = client.get(f"/api/branches/{bid}/decisions").get_json()
    forks = [d for d in decisions if d["kind"] == "history_fork"]
    assert forks, "应当有岔路口决策"
    advice = forks[0]["advice"]
    assert advice
    assert {"name", "option_key", "text", "ability", "loyalty"} <= set(advice[0])