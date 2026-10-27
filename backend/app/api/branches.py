"""分支（时间线）相关接口：推进模拟、读取状态与事件、派生分支。"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from ..app_factory import get_db
from ..engine import SimulationEngine
from ..models import FactionState, RegionState, SimEvent, Snapshot
from ..utils import format_date
from ..services import (
    faction_meta,
    fork_branch,
    get_branch,
    region_geo_map,
)

bp = Blueprint("branches", __name__, url_prefix="/api/branches")


#: 事件范围对应的最小展示层级（越大越宏观）
SCOPE_ORDER = {"local": 1, "region": 2, "nation": 3, "world": 4}


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