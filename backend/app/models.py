"""领域模型。

设计要点（对应设计文档）：
- ``World`` 是「世界模板」：地区、势力、初始数据、规则参数。
- ``Branch`` 是「时间线分支」：从某个起始时间开始独立推进，互不影响。
- 分支的实际状态保存在 ``RegionState`` / ``FactionState``，
  与模板分离，保证 fork 之后互不污染，也保证结果可保存、可复现。
- ``SimEvent`` 记录模拟中真实发生的变化，带范围、程度、时长、涉及对象与因果；
  事件没有固定的「大事/小事」标签，由这些字段推导展示层级。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .utils import format_date


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------------------- #
# 世界模板
# --------------------------------------------------------------------------- #
class World(Base):
    """一个可模拟的世界。第一版只内置，不允许用户从零创建。"""

    __tablename__ = "worlds"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    era: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[dt.date] = mapped_column(Date)
    #: 资料与可信度标注：{"sources": [...], "notes": [...]}
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    regions: Mapped[list["Region"]] = relationship(
        back_populates="world", cascade="all, delete-orphan"
    )
    factions: Mapped[list["Faction"]] = relationship(
        back_populates="world", cascade="all, delete-orphan"
    )
    trade_links: Mapped[list["TradeLink"]] = relationship(
        back_populates="world", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "era": self.era,
            "description": self.description,
            "start_date": format_date(self.start_date),
            "region_count": len(self.regions),
            "faction_count": len(self.factions),
            "provenance": self.provenance or {},
        }


class Region(Base):
    """世界模板中的一个地理单元：道 / 州 / 城市。

    ``geo`` 保存 GeoJSON 几何，用于地图绘制；初期为近似轮廓，
    设计文档要求这类近似值必须可标注，因此 ``data_quality`` 记录其可信度。
    """

    __tablename__ = "regions"
    __table_args__ = (UniqueConstraint("world_id", "key", name="uq_region_world_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    level: Mapped[str] = mapped_column(String(16), default="region")  # 世界/国家/地区/局部
    parent_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lat: Mapped[float] = mapped_column(Float, default=0.0)
    lon: Mapped[float] = mapped_column(Float, default=0.0)
    geo: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    #: 初始模拟数据
    population: Mapped[int] = mapped_column(Integer, default=0)
    grain_stock: Mapped[float] = mapped_column(Float, default=0.0)
    farmland: Mapped[float] = mapped_column(Float, default=0.0)  # 折算的产出基数
    tax_rate: Mapped[float] = mapped_column(Float, default=0.1)
    price_index: Mapped[float] = mapped_column(Float, default=1.0)
    unrest: Mapped[float] = mapped_column(Float, default=0.0)

    #: 数值可信度：{"population": "estimate", "grain_stock": "unknown", ...}
    data_quality: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    faction_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    world: Mapped[World] = relationship(back_populates="regions")


class Faction(Base):
    """势力：朝廷、藩镇、部族等。"""

    __tablename__ = "factions"
    __table_args__ = (UniqueConstraint("world_id", "key", name="uq_faction_world_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16), default="state")  # state/warlord/tribe
    capital_region_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    treasury: Mapped[float] = mapped_column(Float, default=0.0)
    legitimacy: Mapped[float] = mapped_column(Float, default=0.5)
    military: Mapped[float] = mapped_column(Float, default=0.0)

    world: Mapped[World] = relationship(back_populates="factions")


class TradeLink(Base):
    """两个地区之间的转运通道（粮食等物资流动的载体）。

    「一地道歉收会影响到邻道」这件事，必须先有一条真实存在的通道，
    否则 AI 讲出来的连锁反应就没有数据支撑。设计文档要求影响必须
    由规则和数据支持，不能仅凭叙述认定因果。
    """

    __tablename__ = "trade_links"
    __table_args__ = (
        UniqueConstraint("world_id", "from_key", "to_key", name="uq_tradelink_world_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    from_key: Mapped[str] = mapped_column(String(64), index=True)
    to_key: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="grain")
    #: 每月最多可调运的粮量（石）
    capacity: Mapped[float] = mapped_column(Float, default=0.0)
    #: 途耗比例
    loss: Mapped[float] = mapped_column(Float, default=0.08)

    world: Mapped[World] = relationship(back_populates="trade_links")


# --------------------------------------------------------------------------- #
# 时间线分支与状态
# --------------------------------------------------------------------------- #
class Branch(Base):
    """一条独立推进的时间线。"""

    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    seed: Mapped[int] = mapped_column(Integer, default=1)
    precision: Mapped[str] = mapped_column(String(16), default="standard")
    current_date: Mapped[dt.date] = mapped_column(Date)
    tick_index: Mapped[int] = mapped_column(Integer, default=0)

    parent_branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("branches.id", ondelete="SET NULL"), nullable=True
    )
    forked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    world: Mapped[World] = relationship()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "world_id": self.world_id,
            "name": self.name,
            "seed": self.seed,
            "precision": self.precision,
            "current_date": format_date(self.current_date),
            "tick_index": self.tick_index,
            "parent_branch_id": self.parent_branch_id,
        }


class RegionState(Base):
    """分支内的地区状态（世界模板只提供初值）。"""

    __tablename__ = "region_states"
    __table_args__ = (
        UniqueConstraint("branch_id", "region_key", name="uq_regionstate_branch_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), index=True
    )
    region_key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))

    population: Mapped[int] = mapped_column(Integer, default=0)
    grain_stock: Mapped[float] = mapped_column(Float, default=0.0)
    farmland: Mapped[float] = mapped_column(Float, default=0.0)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.1)
    price_index: Mapped[float] = mapped_column(Float, default=1.0)
    unrest: Mapped[float] = mapped_column(Float, default=0.0)
    faction_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def snapshot(self) -> dict[str, Any]:
        return {
            "region_key": self.region_key,
            "name": self.name,
            "population": self.population,
            "grain_stock": round(self.grain_stock, 2),
            "farmland": round(self.farmland, 2),
            "tax_rate": self.tax_rate,
            "price_index": round(self.price_index, 4),
            "unrest": round(self.unrest, 4),
            "faction_key": self.faction_key,
        }


class FactionState(Base):
    """分支内的势力状态。"""

    __tablename__ = "faction_states"
    __table_args__ = (
        UniqueConstraint("branch_id", "faction_key", name="uq_factionstate_branch_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), index=True
    )
    faction_key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    treasury: Mapped[float] = mapped_column(Float, default=0.0)
    legitimacy: Mapped[float] = mapped_column(Float, default=0.5)
    military: Mapped[float] = mapped_column(Float, default=0.0)


# --------------------------------------------------------------------------- #
# 事件与快照
# --------------------------------------------------------------------------- #
class SimEvent(Base):
    """模拟中真实发生的变化。

    scope 对应设计文档的四级观察尺度；severity/impact 用于推导展示层级，
    而不是给事件贴死「大事/小事」标签。
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), index=True
    )
    game_date: Mapped[dt.date] = mapped_column(Date, index=True)
    tick_index: Mapped[int] = mapped_column(Integer, default=0)

    #: world / nation / region / local
    scope: Mapped[str] = mapped_column(String(16), default="region")
    kind: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[int] = mapped_column(Integer, default=1)  # 1..5
    duration_months: Mapped[int] = mapped_column(Integer, default=1)

    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")

    region_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    faction_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: 因果：触发它的上游事件 id 或规则说明
    causes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game_date": format_date(self.game_date),
            "scope": self.scope,
            "kind": self.kind,
            "severity": self.severity,
            "duration_months": self.duration_months,
            "title": self.title,
            "summary": self.summary,
            "region_keys": self.region_keys or [],
            "faction_keys": self.faction_keys or [],
            "causes": self.causes or [],
            "metrics": self.metrics or {},
        }


class Snapshot(Base):
    """某一时刻的世界状态快照，用于复现、对比与分支。"""

    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), index=True
    )
    game_date: Mapped[dt.date] = mapped_column(Date)
    tick_index: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("branch_id", "tick_index", name="uq_snapshot_branch_tick"),
    )