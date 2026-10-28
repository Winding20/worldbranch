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
    #: 开局情境：{"role": "...", "goal": "...", "briefing": "...", "pressures": [...]}
    scenario: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
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
    relations: Mapped[list["FactionRelation"]] = relationship(
        back_populates="world", cascade="all, delete-orphan"
    )
    characters: Mapped[list["Character"]] = relationship(
        back_populates="world", cascade="all, delete-orphan"
    )
    armies: Mapped[list["Army"]] = relationship(
        back_populates="world", cascade="all, delete-orphan"
    )
    historical_events: Mapped[list["HistoricalEvent"]] = relationship(
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
            "scenario": self.scenario or {},
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


# --------------------------------------------------------------------------- #
# 唐史推演：人物、军队、史实事件
# --------------------------------------------------------------------------- #
class Character(Base):
    """历史人物模板。

    安史之乱模拟器的核心资产是"人"：谁在什么位置、手里有多少兵、
    对朝廷有几分忠、有多大野心。这些决定了同一道诏书在不同时期的效果。
    """

    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("world_id", "key", name="uq_character_world_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64))
    #: 字/别名，用于显示
    alias: Mapped[str | None] = mapped_column(String(64), nullable=True)

    faction_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: emperor / minister / general / eunuch / rebel
    role: Mapped[str] = mapped_column(String(24), default="general")
    office: Mapped[str] = mapped_column(String(96), default="")
    #: 品级与性质：见 CharacterState 同名字段
    office_rank: Mapped[int] = mapped_column(Integer, default=5)
    office_kind: Mapped[str] = mapped_column(String(16), default="civil")

    born: Mapped[int | None] = mapped_column(Integer, nullable=True)
    died: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: 0–1：军事/行政综合能力
    ability: Mapped[float] = mapped_column(Float, default=0.5)
    #: 0–1：对朝廷的忠诚
    loyalty: Mapped[float] = mapped_column(Float, default=0.5)
    #: 0–1：自立倾向
    ambition: Mapped[float] = mapped_column(Float, default=0.2)

    location_region_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    alive: Mapped[bool] = mapped_column(default=True)
    #: 是否曾由唐廷叛出。用来把"叛将"和"本就是燕军的人"区分开
    defected: Mapped[bool] = mapped_column(default=False)
    bio: Mapped[str] = mapped_column(Text, default="")
    #: 出处，例如《旧唐书·安禄山传》
    source: Mapped[str] = mapped_column(String(200), default="")

    world: Mapped[World] = relationship(back_populates="characters")


class Army(Base):
    """军队模板：在哪、谁带、多少人、士气如何。"""

    __tablename__ = "armies"
    __table_args__ = (UniqueConstraint("world_id", "key", name="uq_army_world_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(96))
    faction_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    commander_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region_key: Mapped[str] = mapped_column(String(64), default="")

    troops: Mapped[int] = mapped_column(Integer, default=0)
    #: 0–1
    morale: Mapped[float] = mapped_column(Float, default=0.6)
    #: 0–1：粮饷充足程度
    supply: Mapped[float] = mapped_column(Float, default=0.6)
    #: 成军之日。晚于此日才存在的军队（如回纥骑兵、九节度之师）
    #: 不能算进开局的战力，否则 755 年的局势会被算错。
    raises_at: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    world: Mapped[World] = relationship(back_populates="armies")


class HistoricalEvent(Base):
    """史实事件模板。

    每个事件带有"触发条件"：条件满足才会发生。用户如果改变了前提，
    历史就不会按原样走——这正是推演器要展示的东西。
    """

    __tablename__ = "historical_events"
    __table_args__ = (
        UniqueConstraint("world_id", "key", name="uq_histevent_world_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64), index=True)
    #: 史实发生的年月
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    #: 分类：rebellion / battle / politics / court / disaster
    category: Mapped[str] = mapped_column(String(24), default="politics")
    #: 发生所需条件，例如 {"army_at": ["fanyang", "luoyang"], "region_lost": "luoyang"}
    conditions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: 发生后的效果，例如 {"lose_region": "luoyang", "treasury": -200000}
    effects: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: 若条件不成立，用这段文字说明"历史在这里改道了"
    divergence_note: Mapped[str] = mapped_column(Text, default="")
    #: 岔路口：到这一天时把决定权交给用户，而不是直接按史实发生。
    #: 形如 {"title": "...", "description": "...", "options": [{...}]}
    fork: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(200), default="")

    world: Mapped[World] = relationship(back_populates="historical_events")


class CharacterState(Base):
    """分支内的人物状态。"""

    __tablename__ = "character_states"
    __table_args__ = (
        UniqueConstraint("branch_id", "character_key", name="uq_charstate_branch_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), index=True
    )
    character_key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(64))
    faction_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(24), default="general")
    office: Mapped[str] = mapped_column(String(96), default="")
    #: 品级：1 最高（三公），9 最低。用于判断迁转与威望。
    office_rank: Mapped[int] = mapped_column(Integer, default=5)
    #: 官职性质：military（统兵）/ civil（文职）/ envoy（使职）/ sinecure（闲职）
    office_kind: Mapped[str] = mapped_column(String(16), default="civil")
    loyalty: Mapped[float] = mapped_column(Float, default=0.5)
    ambition: Mapped[float] = mapped_column(Float, default=0.2)
    ability: Mapped[float] = mapped_column(Float, default=0.5)
    location_region_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    alive: Mapped[bool] = mapped_column(default=True)
    #: 是否曾由唐廷叛出。用来把"叛将"和"本就是燕军的人"区分开
    defected: Mapped[bool] = mapped_column(default=False)


class ArmyState(Base):
    """分支内的军队状态。"""

    __tablename__ = "army_states"
    __table_args__ = (
        UniqueConstraint("branch_id", "army_key", name="uq_armystate_branch_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), index=True
    )
    army_key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(96))
    faction_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    commander_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region_key: Mapped[str] = mapped_column(String(64), default="")
    troops: Mapped[int] = mapped_column(Integer, default=0)
    morale: Mapped[float] = mapped_column(Float, default=0.6)
    supply: Mapped[float] = mapped_column(Float, default=0.6)
    #: 满编兵额，成军时按此补足
    troops_max: Mapped[int] = mapped_column(Integer, default=0)
    raises_at: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    raised: Mapped[bool] = mapped_column(default=True)


class HistoricalFire(Base):
    """记录某个史实事件在某条分支上是否已经发生（或已改道）。"""

    __tablename__ = "historical_fires"
    __table_args__ = (
        UniqueConstraint("branch_id", "event_key", name="uq_histfire_branch_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), index=True
    )
    event_key: Mapped[str] = mapped_column(String(64), index=True)
    game_date: Mapped[dt.date] = mapped_column(Date)
    #: fired（按史实发生）/ diverged（条件不成立，历史改道）
    status: Mapped[str] = mapped_column(String(16), default="fired")
    note: Mapped[str] = mapped_column(Text, default="")


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


class FactionRelation(Base):
    """势力之间的关系模板（-1 敌对 … 0 中立 … +1 同盟）。

    设计文档要求"国家之间应有真实的数据关系"：这里是政治关系的数据落点，
    决策的后果会改变它，它又会反过来影响后续事件的触发。
    """

    __tablename__ = "faction_relations"
    __table_args__ = (
        UniqueConstraint(
            "world_id", "from_key", "to_key", "kind", name="uq_relation_world_pair"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    from_key: Mapped[str] = mapped_column(String(64), index=True)
    to_key: Mapped[str] = mapped_column(String(64), index=True)
    #: 关系类型：allegiance（臣属）/ hostility（敌对）/ alliance（同盟）
    kind: Mapped[str] = mapped_column(String(24), default="allegiance")
    value: Mapped[float] = mapped_column(Float, default=0.0)

    world: Mapped[World] = relationship(back_populates="relations")


class RelationState(Base):
    """分支内的关系当前值。"""

    __tablename__ = "relation_states"
    __table_args__ = (
        UniqueConstraint(
            "branch_id", "from_key", "to_key", "kind", name="uq_relationstate_pair"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), index=True
    )
    from_key: Mapped[str] = mapped_column(String(64), index=True)
    to_key: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="allegiance")
    value: Mapped[float] = mapped_column(Float, default=0.0)

    def snapshot(self) -> dict[str, Any]:
        return {
            "from_key": self.from_key,
            "to_key": self.to_key,
            "kind": self.kind,
            "value": round(self.value, 3),
        }


def _consensus(advice: list[dict[str, Any]]) -> bool:
    keys = {item.get("option_key") for item in advice}
    return len(keys) == 1


class Decision(Base):
    """摆在用户面前的一道抉择。

    这是"世界自己产生问题"的载体：引擎在满足条件时抛出决策，
    用户从带后果的选项里挑一个，选项结果立即写回世界并留下事件。
    """

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), index=True
    )
    game_date: Mapped[dt.date] = mapped_column(Date, index=True)
    tick_index: Mapped[int] = mapped_column(Integer, default=0)

    #: warlord_supply / famine_relief / border_raid / cut_warlord
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    #: 为什么会冒出这道题（通常指向触发它的事件）
    trigger_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: [{"key": "...", "label": "...", "detail": "...", "effects": {...}}]
    options: Mapped[list[Any]] = mapped_column(JSON, default=list)
    #: 人物进谏：[{"name", "option_key", "text", "ability", "loyalty", "tag"}]
    #: 这些是**按建模规则推出来的立场**，不是史料所载奏议原文。
    advice: Mapped[list[Any]] = mapped_column(JSON, default=list)
    #: 关联的键（例如史实事件 key），用于把决策回溯到它所属的历史节点
    ref_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 这件事发生在哪个地区。界面据此把地图「聚光」到出事的地方。
    focus_region: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: pending / resolved / expired
    status: Mapped[str] = mapped_column(String(16), default="pending")
    resolved_option: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    #: 决议产生的事件 id，后续事件可以挂在它下面
    result_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game_date": format_date(self.game_date),
            "tick_index": self.tick_index,
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
            "trigger_event_id": self.trigger_event_id,
            "ref_key": self.ref_key,
            "focus_region": self.focus_region,
            "options": self.options or [],
            "advice": self.advice or [],
            # 朝议是否一致。全票同意时界面可以直接说"朝议一致"
            "advice_consensus": _consensus(self.advice or []),
            "status": self.status,
            "resolved_option": self.resolved_option,
            "result_event_id": self.result_event_id,
        }


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
    #: 名义归朝廷、实则自专（河朔三镇式藩镇）
    autonomous: Mapped[bool] = mapped_column(default=False)

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
            "autonomous": self.autonomous,
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


# --------------------------------------------------------------------------- #
# 知识库
# --------------------------------------------------------------------------- #
class KnowledgeDoc(Base):
    """一篇世界资料（文献摘录、设定文档等）。

    设计文档要求：资料必须记录来源与可信度，AI 才能区分「史实」「估算」「假设」。
    """

    __tablename__ = "knowledge_docs"
    __table_args__ = (UniqueConstraint("world_id", "slug", name="uq_knowledge_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(96), index=True)
    title: Mapped[str] = mapped_column(String(200))
    #: 来源说明，例如《新唐书·食货志》
    source: Mapped[str] = mapped_column(String(200), default="")
    #: 可信度：primary（一手/正史）/ secondary（研究）/ assumption（设定假设）
    reliability: Mapped[str] = mapped_column(String(16), default="secondary")
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="doc", cascade="all, delete-orphan"
    )

    def to_dict(self, *, with_content: bool = False) -> dict[str, Any]:
        data = {
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "source": self.source,
            "reliability": self.reliability,
            "chunk_count": len(self.chunks),
        }
        if with_content:
            data["content"] = self.content
        return data


class KnowledgeChunk(Base):
    """资料切片，检索的最小单位。

    第一版不引入向量库：按字符二元组做重排，规模在几千条以内足够用；
    真到了需要语义检索的量级再换（设计文档第 9 章：按数据规模再选方案）。
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_docs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)

    doc: Mapped[KnowledgeDoc] = relationship(back_populates="chunks")


# --------------------------------------------------------------------------- #
# 模型服务配置（BYOK）
# --------------------------------------------------------------------------- #
class LlmProvider(Base):
    """用户配置的模型服务。

    **不存 API Key**：Key 由浏览器本地保存、随请求头传入，服务端用完即弃。
    这样即使数据库泄露也不会带走用户的额度。
    """

    __tablename__ = "llm_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(96), unique=True)
    #: openai_compatible / anthropic / gemini / mock
    kind: Mapped[str] = mapped_column(String(32), default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(300), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    enabled: Mapped[bool] = mapped_column(default=True)
    #: 是否为默认 Provider
    is_default: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "base_url": self.base_url,
            "model": self.model,
            "enabled": self.enabled,
            "is_default": self.is_default,
            # 永远不返回 key，连脱敏后的也不返回
            "has_key": False,
        }