"""分支（时间线）相关接口：推进模拟、读取状态与事件、派生分支。"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from ..app_factory import get_db
from ..engine import SimulationEngine
from ..engine.ending import evaluate_ending
from ..engine.end_tang import evaluate_tang_ending
from ..engine.history import history_status
from ..engine.loyalty import loyalty_overview
from ..engine.military import all_powers, candidates_for_command, side_strength
from ..engine.decisions import (
    DecisionError,
    decision_history,
    describe_relation,
    pending_decisions,
    resolve_decision,
)
from ..models import (
    ArmyState,
    CharacterState,
    Decision,
    FactionState,
    RegionState,
    SimEvent,
    Snapshot,
    World,
)
from ..utils import format_date
from ..services import (
    aggregate_by_scale,
    apply_action,
    build_event_chain,
    compare_branches,
    faction_meta,
    fork_branch,
    get_branch,
    region_geo_map,
)

bp = Blueprint("branches", __name__, url_prefix="/api/branches")


#: 事件范围对应的最小展示层级（越大越宏观）
SCOPE_ORDER = {"local": 1, "region": 2, "nation": 3, "world": 4}


@bp.get("/<int:branch_id>/decisions")
def decisions_route(branch_id: int):
    """当前待决的问题；带 history=1 时返回全部历史。"""
    include_history = request.args.get("history") == "1"
    with get_db().session() as session:
        get_branch(session, branch_id)
        rows = (
            decision_history(session, branch_id)
            if include_history
            else pending_decisions(session, branch_id)
        )
        return jsonify([d.to_dict() for d in rows])


@bp.post("/<int:branch_id>/decisions/<int:decision_id>/resolve")
def resolve_decision_route(branch_id: int, decision_id: int):
    payload = request.get_json(silent=True) or {}
    option = payload.get("option", "")
    with get_db().session() as session:
        branch = get_branch(session, branch_id)
        decision = session.get(Decision, decision_id)
        if decision is None or decision.branch_id != branch_id:
            raise LookupError("决策不存在")
        event = resolve_decision(session, branch, decision, option)
        return jsonify({"decision": decision.to_dict(), "event": event.to_dict()})


@bp.get("/<int:branch_id>/loyalty")
def loyalty_route(branch_id: int):
    """人物忠诚一览：谁在带兵、功高到何种程度、谁在离心。"""
    with get_db().session() as session:
        get_branch(session, branch_id)
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
        return jsonify(loyalty_overview(characters, armies))


@bp.get("/<int:branch_id>/armies")
def armies_route(branch_id: int):
    """各军现状与战力，以及可用的主帅人选。"""
    with get_db().session() as session:
        get_branch(session, branch_id)
        armies = list(
            session.scalars(select(ArmyState).where(ArmyState.branch_id == branch_id))
        )
        characters = {
            c.character_key: c
            for c in session.scalars(
                select(CharacterState).where(CharacterState.branch_id == branch_id)
            )
        }
        return jsonify(
            {
                "armies": [p.to_dict() for p in all_powers(armies, characters)],
                "tang_total": round(side_strength(armies, characters, "tang")),
                "yan_total": round(side_strength(armies, characters, "yan")),
                "candidates": [
                    {
                        "key": c.character_key,
                        "name": c.name,
                        "office": c.office,
                        "ability": round(c.ability, 3),
                    }
                    for c in candidates_for_command(characters, "tang")
                ],
            }
        )


@bp.get("/<int:branch_id>/relations")
def relations_route(branch_id: int):
    with get_db().session() as session:
        get_branch(session, branch_id)
        return jsonify(describe_relation(session, branch_id))


@bp.get("/<int:branch_id>/history")
def history_route(branch_id: int):
    """这条时间线上，哪些史实应验、哪些改道。"""
    with get_db().session() as session:
        get_branch(session, branch_id)
        return jsonify(history_status(session, branch_id))


@bp.get("/<int:branch_id>/ending")
def ending_route(branch_id: int):
    """五年结局评估；未满五年返回 204。"""
    with get_db().session() as session:
        branch = get_branch(session, branch_id)
        world = session.get(World, branch.world_id)
        # 唐朝切片有自己的成败标准（两京、乱平、河北归属），不用通用五年评分
        if world is not None and world.key == "tang_755":
            result = evaluate_tang_ending(session, branch)
        else:
            result = evaluate_ending(session, branch)
        if result is None:
            return ("", 204)
        return jsonify(result)


@bp.get("/<int:branch_id>/view")
def view_route(branch_id: int):
    """按观察尺度返回聚合后的世界状态。

    缩放地图时前端只要换一个 scale，后端不做任何数据增减，只换聚合方式。
    """
    scale = request.args.get("scale", "region")
    with get_db().session() as session:
        branch = get_branch(session, branch_id)
        return jsonify(aggregate_by_scale(session, branch, scale))


@bp.get("/compare")
def compare_route():
    """对比两条时间线：状态差异、分叉点、各自独有的事件。"""
    left_id = request.args.get("left", type=int)
    right_id = request.args.get("right", type=int)
    if not left_id or not right_id:
        raise ValueError("需要 left 与 right 两个分支 id")

    with get_db().session() as session:
        left = get_branch(session, left_id)
        right = get_branch(session, right_id)
        return jsonify(compare_branches(session, left, right))


@bp.get("/<int:branch_id>")
def detail(branch_id: int):
    with get_db().session() as session:
        branch = get_branch(session, branch_id)
        return jsonify(branch.to_dict())


@bp.post("/<int:branch_id>/advance")
def advance(branch_id: int):
    payload = request.get_json(silent=True) or {}
    months = int(payload.get("months", 1))
    precision = payload.get("precision")

    with get_db().session() as session:
        branch = get_branch(session, branch_id)
        engine = SimulationEngine(session)
        report = engine.advance(branch, months=months, precision=precision)
        return jsonify(report.to_dict())


@bp.get("/<int:branch_id>/state")
def state(branch_id: int):
    with get_db().session() as session:
        branch = get_branch(session, branch_id)
        regions = list(
            session.scalars(
                select(RegionState).where(RegionState.branch_id == branch_id)
            )
        )
        factions = list(
            session.scalars(
                select(FactionState).where(FactionState.branch_id == branch_id)
            )
        )
        geo = region_geo_map(session, branch.world_id)
        fmeta = faction_meta(session, branch.world_id)

        return jsonify(
            {
                "branch": branch.to_dict(),
                "regions": [
                    {
                        **r.snapshot(),
                        **{k: geo.get(r.region_key, {}).get(k) for k in ("lat", "lon", "geo", "data_quality", "level")},
                    }
                    for r in regions
                ],
                "factions": [
                    {
                        "faction_key": f.faction_key,
                        "name": f.name,
                        "treasury": round(f.treasury, 2),
                        "legitimacy": round(f.legitimacy, 4),
                        "military": round(f.military, 2),
                        **fmeta.get(f.faction_key, {}),
                    }
                    for f in factions
                ],
            }
        )


@bp.get("/<int:branch_id>/events")
def events(branch_id: int):
    """按观察尺度筛选事件。

    ``min_scope``：只看该层级及以上（local < region < nation < world）。
    ``min_severity``：只看不低于该程度的事件。
    """
    min_scope = request.args.get("min_scope", "local")
    min_severity = int(request.args.get("min_severity", 1))
    limit = min(int(request.args.get("limit", 100)), 500)
    kinds = request.args.getlist("kind")

    threshold = SCOPE_ORDER.get(min_scope, 1)

    with get_db().session() as session:
        get_branch(session, branch_id)
        stmt = (
            select(SimEvent)
            .where(
                SimEvent.branch_id == branch_id,
                SimEvent.severity >= min_severity,
            )
            .order_by(SimEvent.tick_index.desc(), SimEvent.severity.desc())
            .limit(limit)
        )
        if kinds:
            stmt = stmt.where(SimEvent.kind.in_(kinds))
        rows = [
            e
            for e in session.scalars(stmt)
            if SCOPE_ORDER.get(e.scope, 1) >= threshold
        ]
        return jsonify([e.to_dict() for e in rows])


@bp.post("/<int:branch_id>/actions")
def apply_action_route(branch_id: int):
    """用户干预：制造歉收、开仓赈济、调整税率。

    干预是因果链的起点——它之后引发的粮荒、调运都能追溯到这条事件。
    """
    payload = request.get_json(silent=True) or {}
    kind = payload.get("kind", "")
    region_key = payload.get("region_key", "")
    params = payload.get("params") or {}

    with get_db().session() as session:
        branch = get_branch(session, branch_id)
        event = apply_action(session, branch, kind, region_key, params)
        return jsonify(event.to_dict()), 201


@bp.get("/<int:branch_id>/events/<int:event_id>/chain")
def event_chain(branch_id: int, event_id: int):
    """回溯某个事件的上游因果链（谁导致了它，再往上是谁）。"""
    depth = min(int(request.args.get("depth", 6)), 12)
    with get_db().session() as session:
        get_branch(session, branch_id)
        return jsonify(build_event_chain(session, branch_id, event_id, max_depth=depth))


@bp.get("/<int:branch_id>/snapshots")
def snapshots(branch_id: int):
    limit = min(int(request.args.get("limit", 60)), 500)
    with get_db().session() as session:
        get_branch(session, branch_id)
        rows = list(
            session.scalars(
                select(Snapshot)
                .where(Snapshot.branch_id == branch_id)
                .order_by(Snapshot.tick_index.desc())
                .limit(limit)
            )
        )
        return jsonify(
            [
                {
                    "tick_index": s.tick_index,
                    "game_date": format_date(s.game_date),
                    "state": s.state,
                }
                for s in rows
            ]
        )


@bp.post("/<int:branch_id>/fork")
def fork(branch_id: int):
    payload = request.get_json(silent=True) or {}
    with get_db().session() as session:
        source = get_branch(session, branch_id)
        branch = fork_branch(
            session,
            source,
            name=payload.get("name"),
            seed=payload.get("seed"),
        )
        return jsonify(branch.to_dict()), 201