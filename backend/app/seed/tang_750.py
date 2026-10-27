"""唐朝世界（天宝九年，公元 750 年）内置数据包。

数据说明（务必保留）：
- 人口、耕地、存粮为**量级估算**，用于让引擎跑通结构，不代表史实精确数值；
  每个地区用 ``data_quality`` 标注哪些字段是估算/未知。
- 地理轮廓由 `tools/build_geo.py` 生成：用**现代省级行政区边界近似唐代各道辖境**，
  只用于地图展示与尺度演示，不是历史行政区划复原。
- 势力关系与财政为**示意数据**，后续应由史实资料与可信来源逐步替换。

设计文档要求：缺数据就标未知或估算，绝不编造看似精确的数字。
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..engine.rules import GRAIN_PER_CAPITA_MONTH, SEASON_FACTOR
from ..models import Faction, FactionRelation, Region, TradeLink, World

WORLD_KEY = "tang_750"
START_DATE = dt.date(750, 1, 1)

GEO_FILE = Path(__file__).resolve().parent / "data" / "tang_750_geo.json"
GEO_DATA: dict[str, Any] = json.loads(GEO_FILE.read_text(encoding="utf-8")) if GEO_FILE.exists() else {"dao": {}}

SOURCE_NOTES: dict[str, Any] = {
    "sources": [
        "《旧唐书·地理志》（行政区划框架）",
        "《新唐书·食货志》（税制与财政结构参考）",
        "《通典》（人口与仓储量级参考）",
        "阿里云 DataV 中国省级行政区边界（地理轮廓数据来源）",
    ],
    "notes": [
        "人口与耕地为量级估算，按天宝年间各道相对规模缩放，非逐道精确统计。",
        "存粮、粮价指数、民变指数为模拟初始假设，无史料直接对应。",
        "地理轮廓用现代省级行政区边界近似唐代各道辖境，仅用于展示，不代表真实疆界。",
        "河北道的军政独立性在数值上体现为独立势力，但具体军额与财赋为示意。",
    ],
}


def _geo(key: str) -> dict[str, Any]:
    """取该道的 MultiPolygon 几何；数据缺失时回退为一个空的占位。"""
    dao = GEO_DATA.get("dao", {}).get(key)
    if not dao:
        return {"type": "MultiPolygon", "coordinates": []}
    return {"type": dao["type"], "coordinates": dao["coordinates"]}


def _seat(key: str) -> tuple[float, float]:
    """治所坐标，用作标签定位与地图中心。"""
    dao = GEO_DATA.get("dao", {}).get(key) or {}
    seat = dao.get("seat") or [0.0, 0.0]
    return float(seat[1]), float(seat[0])  # (lat, lon)


# 每道的数据口径：
# - population：量级估算（天宝年间各道相对规模）
# - fertility：相对丰度，1.0 表示全年产出刚好覆盖本道口粮
# - stock_months：初始存粮相当于几个月的口粮消耗
# 月产粮基数与初始存粮由人口推导，避免手填数字自相矛盾。
# 地理轮廓来自 data/tang_750_geo.json（tools/build_geo.py 生成）。
REGIONS: list[dict[str, Any]] = [
    {"key": "guannei", "name": "关内道", "population": 2_800_000, "fertility": 1.02, "stock_months": 5, "faction_key": "tang"},
    {"key": "henan",   "name": "河南道", "population": 5_200_000, "fertility": 1.08, "stock_months": 6, "faction_key": "tang"},
    {"key": "hebei",   "name": "河北道", "population": 4_800_000, "fertility": 1.02, "stock_months": 5, "faction_key": "fanzhen"},
    {"key": "hedong",  "name": "河东道", "population": 2_100_000, "fertility": 1.00, "stock_months": 5, "faction_key": "tang"},
    {"key": "huainan", "name": "淮南道", "population": 1_600_000, "fertility": 1.10, "stock_months": 6, "faction_key": "tang"},
    {"key": "jiangnan","name": "江南道", "population": 3_600_000, "fertility": 1.15, "stock_months": 7, "faction_key": "tang"},
    {"key": "longyou", "name": "陇右道", "population": 900_000,   "fertility": 0.97, "stock_months": 4, "faction_key": "tang"},
]

FACTIONS: list[dict[str, Any]] = [
    {
        "key": "tang",
        "name": "唐廷",
        "kind": "state",
        "capital_region_key": "guannei",
        "treasury": 3_000_000.0,
        "legitimacy": 0.62,
        "military": 120_000.0,
    },
    {
        "key": "fanzhen",
        "name": "河北藩镇",
        "kind": "warlord",
        "capital_region_key": "hebei",
        "treasury": 1_200_000.0,
        "legitimacy": 0.45,
        "military": 180_000.0,
    },
]

DEFAULT_DATA_QUALITY = {
    "population": "estimate",
    "farmland": "estimate",
    "grain_stock": "assumption",
    "tax_rate": "assumption",
    "price_index": "assumption",
    "geo": "approximate",
}

#: 各道之间的转运通道（双向各存一条）。
#: capacity 是每月可调运上限（石），按道的规模与地理邻近程度给量级估算。
TRADE_PAIRS: list[tuple[str, str, float]] = [
    ("guannei", "henan", 200_000),   # 关中与中原之间的干道
    ("guannei", "hedong", 120_000),
    ("guannei", "longyou", 80_000),
    ("henan", "hebei", 260_000),     # 河北粮道，安史之乱前最繁忙的一条
    ("henan", "huainan", 150_000),
    ("henan", "hedong", 90_000),
    ("hebei", "hedong", 100_000),
    ("huainan", "jiangnan", 180_000),
]

#: 全年 12 个月的农事强度之和，用于把「年产能力」换算成「月产基数」
SEASON_SUM = sum(SEASON_FACTOR)

#: 势力关系：以唐廷为中心的臣属关系。value 越高越听话。
RELATIONS: list[dict[str, Any]] = [
    {"from_key": "fanzhen", "to_key": "tang", "kind": "allegiance", "value": 0.34},
]

#: 开局情境：用户扮演唐廷，这是"我在干什么"的答案。
SCENARIO: dict[str, Any] = {
    "role": "唐廷 · 天宝九年",
    "goal": "撑过未来五年：不让藩镇坐大，不让府库见底，不让民变成势。",
    "briefing": (
        "天宝九年（750 年），唐朝表面承平，内里三处吃紧。"
        "河北三镇拥兵自重、赋税自留；朝廷府库看似充裕，边军粮饷却占去大半；"
        "江淮一旦水旱，漕粮就会断。五年之后，天下人都知道发生了什么——"
        "而这一次，你可以选择不重蹈覆辙。"
    ),
    "pressures": [
        "河北藩镇听调不听宣，军饷仍要朝廷供给",
        "边军粮饷占去朝廷岁入的大半",
        "江淮水旱直接威胁漕粮命脉",
    ],
    "watch": ["河北道民变指数", "河北藩镇臣属度", "朝廷府库", "河北道粮价指数"],
}


def derive_region_values(item: dict[str, Any]) -> dict[str, float]:
    """由人口、丰度与存粮月数推导引擎所需的两个量。

    这样改人口时不会留下自相矛盾的耕地/存粮数字，
    也避免手填出「所有人都立刻饿死」这类明显不合理的初值。
    """
    annual_need = item["population"] * GRAIN_PER_CAPITA_MONTH * 12
    farmland = annual_need * item["fertility"] / SEASON_SUM
    grain_stock = item["population"] * GRAIN_PER_CAPITA_MONTH * item["stock_months"]
    return {"farmland": round(farmland, 1), "grain_stock": round(grain_stock, 1)}


def seed(session: Session) -> World:
    world = World(
        key=WORLD_KEY,
        name="唐朝",
        era="天宝九年（750 年）",
        description=(
            "以唐朝天宝年间为背景的内置世界，覆盖关内、河南、河北、河东、淮南、江南、陇右七道。"
            "用于验证多地区同步模拟、势力交互、跨区域影响与时间推进。"
        ),
        start_date=START_DATE,
        provenance=SOURCE_NOTES,
        scenario=SCENARIO,
    )
    session.add(world)
    session.flush()

    for item in REGIONS:
        derived = derive_region_values(item)
        lat, lon = _seat(item["key"])
        session.add(
            Region(
                world_id=world.id,
                key=item["key"],
                name=item["name"],
                level="region",
                lat=lat,
                lon=lon,
                geo=_geo(item["key"]),
                population=item["population"],
                farmland=derived["farmland"],
                grain_stock=derived["grain_stock"],
                tax_rate=0.08,
                price_index=1.0,
                unrest=0.0,
                faction_key=item["faction_key"],
                data_quality={
                    **DEFAULT_DATA_QUALITY,
                    "fertility": "assumption",
                    "stock_months": "assumption",
                },
            )
        )

    for item in FACTIONS:
        session.add(
            Faction(
                world_id=world.id,
                key=item["key"],
                name=item["name"],
                kind=item["kind"],
                capital_region_key=item["capital_region_key"],
                treasury=item["treasury"],
                legitimacy=item["legitimacy"],
                military=item["military"],
            )
        )

    # 转运通道：双向各存一条，途耗按地形给个统一量级
    for a_key, b_key, capacity in TRADE_PAIRS:
        for src, dst in ((a_key, b_key), (b_key, a_key)):
            session.add(
                TradeLink(
                    world_id=world.id,
                    from_key=src,
                    to_key=dst,
                    kind="grain",
                    capacity=capacity,
                    loss=0.08,
                )
            )

    # 势力关系：藩镇对朝廷的臣属度
    for item in RELATIONS:
        session.add(
            FactionRelation(
                world_id=world.id,
                from_key=item["from_key"],
                to_key=item["to_key"],
                kind=item["kind"],
                value=item["value"],
            )
        )

    session.flush()
    return world


# --------------------------------------------------------------------------- #
# 知识库
# --------------------------------------------------------------------------- #
#: 内置资料。均为**概述性文字**（非原文摘录），用于给 AI 提供背景；
#: 每条都标注来源与可信度，避免读者把概述当成史料原文。
KNOWLEDGE: list[dict[str, Any]] = [
    {
        "slug": "tang-tax-system",
        "title": "唐代前期的赋税与转运",
        "source": "《新唐书·食货志》概述",
        "reliability": "secondary",
        "content": (
            "唐前期以租庸调为主，按丁授田、按丁征课，另以户税、地税补充。"
            "安史之乱以后，均田制瓦解、户籍散乱，租庸调难以为继。\n\n"
            "建中元年（780）杨炎推行两税法，改按资产与田亩征税，分夏、秋两次征收，"
            "税基从人丁转向财产。这一转变的背景，正是战乱后人口流散、"
            "土地兼并加剧、原有税制无法维持。\n\n"
            "漕运是把江淮粮米运往关中与北方的重要手段。粮食转运依赖运河与陆路，"
            "运距长、损耗大，遇到战乱或水旱，运路中断会迅速影响京师与边军供给。"
        ),
    },
    {
        "slug": "tang-military",
        "title": "从府兵到藩镇：唐代军事结构的变化",
        "source": "《旧唐书·职官志》《新唐书·兵志》概述",
        "reliability": "secondary",
        "content": (
            "唐前期实行府兵制，兵农合一，折冲府分布于各地，府兵定期番上宿卫，"
            "军费负担相对较低。随着均田制破坏与战事延长，府兵逃亡、兵源不足，"
            "逐渐转向募兵。\n\n"
            "开元、天宝年间，边镇节度使掌握募兵、财赋与地方行政，"
            "形成军政合一的权力结构。河北一带的节度使实力尤强，"
            "中央对地方的直接控制随之削弱。\n\n"
            "这类结构的风险在于：边军的给养高度依赖中央调拨与本地征敛，"
            "一旦中央财赋不足或调拨中断，边镇倾向于自行截留赋税，"
            "中央与藩镇的关系随之紧张。"
        ),
    },
    {
        "slug": "tang-famine-relief",
        "title": "唐代的灾荒与赈济",
        "source": "《通典》《新唐书·食货志》概述",
        "reliability": "secondary",
        "content": (
            "唐代应对灾荒的常规手段包括：蠲免赋税、开仓放粮、平粜（官府平价售粮）、"
            "以及组织流民就食他州。仓廪体系以正仓、义仓、常平仓为主，"
            "常平仓的职能是丰年收籴、荒年出粜以平抑粮价。\n\n"
            "赈济的难点在于：灾情往往先在地方显现，等奏报抵达朝廷、批复下达、"
            "粮米调运到位，已有时间差；运输能力也限制了一次能调拨的规模。\n\n"
            "当本地仓储不足时，常见的做法是从邻道调粮。但调出方也有自身的存粮安全线，"
            "过度调出会把粮价压力转移到调出地，形成「救一处、紧一处」的连锁反应。"
        ),
    },
    {
        "slug": "tang-geography",
        "title": "天宝年间的行政区划概况",
        "source": "《旧唐书·地理志》概述",
        "reliability": "secondary",
        "content": (
            "唐前期实行州（郡）、县两级，其上设道作为监察区。"
            "天宝年间分天下为十五道，其中关内、河南、河东、河北、陇右、淮南、江南诸道"
            "在经济与军事上最为关键。\n\n"
            "关内道为京畿所在，政治地位最高但粮食供给依赖外运；"
            "河南道地处中原，人口稠密、农业发达，是粮赋重地；"
            "河北道人口众多、仓储充实，同时边军集中；"
            "江南道与淮南道水网密布，是漕粮的主要来源；"
            "陇右道地接西北，承担边防与通西域的通道职能。"
        ),
    },
    {
        "slug": "worldbranch-model-notes",
        "title": "本模拟的建模假设与局限",
        "source": "WorldBranch 项目设定",
        "reliability": "assumption",
        "content": (
            "本世界的数值为量级估算与模拟假设，不是史实统计。"
            "各道人口按天宝年间的相对规模缩放；耕地、存粮、粮价指数与民变指数"
            "均为模型内部量，没有直接的史料对应值。\n\n"
            "模拟只覆盖粮食、财政、民变与调运这一条主干链路，"
            "不包含气候系统、货币制度、人口迁移、技术与文化传播等机制。"
            "因此它适合观察「某一冲击如何沿粮食与财政关系传导」，"
            "不适合用于估算真实历史中的具体数值。\n\n"
            "地图轮廓使用现代省级行政区边界近似唐代各道辖境，仅用于展示，"
            "不代表真实历史疆界。"
        ),
    },
]


def seed_knowledge(session: Session, world: World) -> int:
    """写入内置资料（幂等）。返回写入条数。"""
    from ..ai.knowledge import upsert_doc

    count = 0
    for item in KNOWLEDGE:
        upsert_doc(
            session,
            world,
            slug=item["slug"],
            title=item["title"],
            content=item["content"],
            source=item["source"],
            reliability=item["reliability"],
        )
        count += 1
    return count
