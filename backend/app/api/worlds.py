"""世界相关接口。"""

from __future__ import annotations

import datetime as dt

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from ..app_factory import get_db
from ..models import Branch
from ..services import (
    create_branch,
    get_world_by_key,
    list_worlds,
    region_geo_map,
    faction_meta,
)

bp = Blueprint("worlds", __name__, url_prefix="/api/worlds")


@bp.get("")
def index():
    with get_db().session() as session:
        return jsonify([w.to_dict() for w in list_worlds(session)])


@bp.get("/<key>")
def detail(key: str):
    with get_db().session() as session:
        world = get_world_by_key(session, key)
        return jsonify(
            {
                **world.to_dict(),
                "regions": [
                    {
                        "key": r.key,
                        "name": r.name,
                        "lat": r.lat,
                        "lon": r.lon,
                        "geo": r.geo,
                        "faction_key": r.faction_key,
                        "population": r.population,
                        "data_quality": r.data_quality or {},
                    }
                    for r in world.regions
                ],
                "factions": [
                    {
                        "key": f.key,
                        "name": f.name,
                        "kind": f.kind,
                        "capital_region_key": f.capital_region_key,
                    }
                    for f in world.factions
                ],
            }
        )


@bp.post("/<key>/branches")
def create_branch_route(key: str):
    payload = request.get_json(silent=True) or {}
    precision = payload.get("precision", "standard")
    seed = int(payload.get("seed", 1))
    name = payload.get("name")
    start_date = payload.get("start_date")
    parsed_start = dt.date.fromisoformat(start_date) if start_date else None

    with get_db().session() as session:
        world = get_world_by_key(session, key)
        branch = create_branch(
            session,
            world,
            name=name,
            precision=precision,
            seed=seed,
            start_date=parsed_start,
        )
        return jsonify(branch.to_dict()), 201


@bp.get("/<key>/branches")
def list_branches_route(key: str):
    """列出该世界已有的分支，最新的在前。"""
    with get_db().session() as session:
        world = get_world_by_key(session, key)
        rows = session.scalars(
            select(Branch)
            .where(Branch.world_id == world.id)
            .order_by(Branch.id.desc())
        )
        return jsonify([b.to_dict() for b in rows])


@bp.get("/<key>/map")
def map_route(key: str):
    """世界模板地图：几何为主，不含分支状态。"""
    with get_db().session() as session:
        world = get_world_by_key(session, key)
        return jsonify(
            {
                "world": world.to_dict(),
                "regions": region_geo_map(session, world.id),
                "factions": faction_meta(session, world.id),
            }
        )