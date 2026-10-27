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
from ..models import Faction, Region, World

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

#: 全年 12 个月的农事强度之和，用于把「年产能力」换算成「月产基数」
SEASON_SUM = sum(SEASON_FACTOR)


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

    session.flush()
    return world
