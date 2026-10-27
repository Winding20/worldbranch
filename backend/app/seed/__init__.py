"""内置世界的数据包。"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Faction, Region, World
from . import anlushan_755, tang_750

WORLD_SEEDERS = {
    "tang_750": tang_750.seed,
    "tang_755": anlushan_755.seed,
}

#: 各世界的知识库资料
KNOWLEDGE_PACKS = {
    "tang_750": tang_750.KNOWLEDGE,
    "tang_755": anlushan_755.KNOWLEDGE,
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


def seed_knowledge(session: Session) -> int:
    """为内置世界写入知识库资料（幂等）。"""
    total = 0
    for key, pack in KNOWLEDGE_PACKS.items():
        world = session.scalar(select(World).where(World.key == key))
        if world is None:
            raise LookupError("请先执行 seed 写入世界")
        total += _seed_pack(session, world, pack)
    session.flush()
    return total


def _seed_pack(session: Session, world: World, pack: list[dict]) -> int:
    from ..ai.knowledge import upsert_doc

    count = 0
    for doc in pack:
        upsert_doc(
            session,
            world,
            title=doc["title"],
            content=doc["content"],
            source=doc["source"],
            reliability=doc["reliability"],
            slug=doc["slug"],
        )
        count += 1
    return count


__all__ = [
    "WORLD_SEEDERS",
    "KNOWLEDGE_PACKS",
    "seed_all",
    "seed_knowledge",
    "seed_tang",
    "tang_750",
    "anlushan_755",
    "Faction",
    "Region",
    "World",
    "dt",
]