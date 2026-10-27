"""内置世界的数据包。"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Faction, Region, World
from . import tang_750

WORLD_SEEDERS = {
    "tang_750": tang_750.seed,
}


def seed_all(session: Session) -> list[World]:
    """幂等地写入所有内置世界。"""
    created: list[World] = []
    for key, seeder in WORLD_SEEDERS.items():
        exists = session.scalar(select(World).where(World.key == key))
        if exists is not None:
            created.append(exists)
            continue
        created.append(seeder(session))
    session.flush()
    return created


def seed_tang(session: Session) -> World:
    """单独写入唐朝世界（测试与命令行用）。"""
    exists = session.scalar(select(World).where(World.key == tang_750.WORLD_KEY))
    if exists is not None:
        return exists
    world = tang_750.seed(session)
    session.flush()
    return world


__all__ = ["WORLD_SEEDERS", "seed_all", "seed_tang", "tang_750", "Faction", "Region", "World", "dt"]