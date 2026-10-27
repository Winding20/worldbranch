"""世界与分支的服务层：创建、派生、查询。

放在引擎之外，避免引擎直接依赖 HTTP 或命令行。
"""

from __future__ import annotations

import datetime as dt
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Branch,
    Faction,
    FactionState,
    Region,
    RegionState,
    World,
)


class WorldNotFound(LookupError):
    pass


class BranchNotFound(LookupError):
    pass


def get_world_by_key(session: Session, key: str) -> World:
    world = session.scalar(select(World).where(World.key == key))
    if world is None:
        raise WorldNotFound(f"世界不存在: {key}")
    return world


def list_worlds(session: Session) -> Sequence[World]:
    return list(session.scalars(select(World).order_by(World.id)))


def create_branch(
    session: Session,
    world: World,
    *,
    name: str | None = None,
    precision: str = "standard",
    seed: int = 1,
    start_date: dt.date | None = None,
) -> Branch:
    """从世界模板开出一条新分支，并复制初始状态。"""
    branch = Branch(
        world_id=world.id,
        name=name or f"{world.name}·{world.start_date.isoformat()}",
        seed=seed,
        precision=precision,
        current_date=start_date or world.start_date,
        tick_index=0,
    )
    session.add(branch)
    session.flush()

    for region in world.regions:
        session.add(
            RegionState(
                branch_id=branch.id,
                region_key=region.key,
                name=region.name,
                population=region.population,
                grain_stock=region.grain_stock,
                farmland=region.farmland,
                tax_rate=region.tax_rate,
                price_index=region.price_index,
                unrest=region.unrest,
                faction_key=region.faction_key,
            )
        )
    for faction in world.factions:
        session.add(
            FactionState(
                branch_id=branch.id,
                faction_key=faction.key,
                name=faction.name,
                treasury=faction.treasury,
                legitimacy=faction.legitimacy,
                military=faction.military,
            )
        )
    session.flush()
    return branch


def fork_branch(
    session: Session,
    source: Branch,
    *,
    name: str | None = None,
    seed: int | None = None,
) -> Branch:
    """从当前时刻复制一条独立分支。

    设计文档要求：分支隔离、可复现。因此复制的是「此刻的状态」，
    而不是重新从世界模板开始，历史事件也留在原分支。
    """
    branch = Branch(
        world_id=source.world_id,
        name=name or f"{source.name}·分支{source.id}",
        seed=seed if seed is not None else source.seed + 1,
        precision=source.precision,
        current_date=source.current_date,
        tick_index=source.tick_index,
        parent_branch_id=source.id,
        forked_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(branch)
    session.flush()

    for state in session.scalars(
        select(RegionState).where(RegionState.branch_id == source.id)
    ):
        session.add(
            RegionState(
                branch_id=branch.id,
                region_key=state.region_key,
                name=state.name,
                population=state.population,
                grain_stock=state.grain_stock,
                farmland=state.farmland,
                tax_rate=state.tax_rate,
                price_index=state.price_index,
                unrest=state.unrest,
                faction_key=state.faction_key,
            )
        )
    for state in session.scalars(
        select(FactionState).where(FactionState.branch_id == source.id)
    ):
        session.add(
            FactionState(
                branch_id=branch.id,
                faction_key=state.faction_key,
                name=state.name,
                treasury=state.treasury,
                legitimacy=state.legitimacy,
                military=state.military,
            )
        )
    session.flush()
    return branch


def get_branch(session: Session, branch_id: int) -> Branch:
    branch = session.get(Branch, branch_id)
    if branch is None:
        raise BranchNotFound(f"分支不存在: {branch_id}")
    return branch


def region_geo_map(session: Session, world_id: int) -> dict[str, dict]:
    """地区 key -> 地理信息，供地图渲染。"""
    out: dict[str, dict] = {}
    for region in session.scalars(select(Region).where(Region.world_id == world_id)):
        out[region.key] = {
            "name": region.name,
            "level": region.level,
            "lat": region.lat,
            "lon": region.lon,
            "geo": region.geo,
            "data_quality": region.data_quality or {},
        }
    return out


def faction_meta(session: Session, world_id: int) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for faction in session.scalars(
        select(Faction).where(Faction.world_id == world_id)
    ):
        out[faction.key] = {
            "name": faction.name,
            "kind": faction.kind,
            "capital_region_key": faction.capital_region_key,
        }
    return out