"""唐朝切片的结局：八年之后，天下成了什么样。

通用 ending.py 是按"五年"算的；这一段历史有自己的问题：
叛乱平了没有？两京在谁手里？藩镇是不是已经尾大不掉？

评分只用引擎记录的事实。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Branch, CharacterState, FactionState, RegionState
from ..utils import format_date

#: 从开局算起多少个月算"八年"
TANG_HORIZON_MONTHS = 96

#: 两京
CAPITALS = {"changan": "京兆", "luoyang": "河南府"}

#: 评分门槛
GRADES = (
    # 门槛刻意偏高：史实上唐朝是"打赢了但空心化"，
    # 若把那种结局判成中兴，这个模拟器就没有判断力了。
    (85, "中兴", "两京无恙，河北未失，天下犹可为。"),
    (60, "克复", "叛乱虽平，然师老兵疲、府库空虚，河北已非朝廷所有。"),
    (42, "苟安", "乱虽止而权已移，河北自此听调不听宣。"),
    (25, "大乱初定", "烽火暂息，然天下已非旧日之天下。"),
    (0, "崩坏", "乱事未平，藩镇自立，唐廷号令不出关中。"),
)


def _hebei_score(*regions) -> float:
    """河北的实际归属：直辖 100 / 名义归附而自专 40 / 沦于叛军 0。"""
    if not regions or any(r is None for r in regions):
        return 0.0
    if any(r.faction_key != "tang" for r in regions):
        return 0.0
    if any(r.autonomous for r in regions):
        return 40.0
    return 100.0


def _grade(score: float) -> tuple[str, str]:
    for threshold, name, verdict in GRADES:
        if score >= threshold:
            return name, verdict
    return GRADES[-1][1], GRADES[-1][2]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


def evaluate_tang_ending(session: Session, branch: Branch) -> dict[str, Any] | None:
    """八年之后的局势。未到时限返回 None。"""
    if branch.tick_index < TANG_HORIZON_MONTHS:
        return None

    regions = list(
        session.scalars(select(RegionState).where(RegionState.branch_id == branch.id))
    )
    by_key = {r.region_key: r for r in regions}
    factions = {
        f.faction_key: f
        for f in session.scalars(
            select(FactionState).where(FactionState.branch_id == branch.id)
        )
    }
    characters = {
        c.character_key: c
        for c in session.scalars(
            select(CharacterState).where(CharacterState.branch_id == branch.id)
        )
    }

    tang = factions.get("tang")
    capitals_held = sum(
        1 for key in CAPITALS if by_key.get(key) and by_key[key].faction_key == "tang"
    )
    rebel_regions = [r.name for r in regions if r.faction_key != "tang"]
    # 名义归附、实则自专的州郡不算叛军所据，但也不算朝廷真正掌握
    autonomous_regions = [
        r.name for r in regions if r.faction_key == "tang" and r.autonomous
    ]
    rebellion_over = not rebel_regions

    placed = characters.get("shi_chaoyi")
    rebel_leader_gone = placed is not None and not placed.alive

    raw = {
        # 两京在谁手里，是这八年最直观的成败
        "两京": capitals_held / len(CAPITALS) * 100,
        "乱平": 100.0 if rebellion_over else (60.0 if rebel_leader_gone else 20.0),
        "府库": _clamp(((tang.treasury if tang else 0) + 500_000) / 8_000_000) * 100,
        "威望": _clamp(tang.legitimacy if tang else 0.5) * 100,
        "民心": (1 - _clamp(max((r.unrest for r in regions), default=0.0) / 0.7)) * 100,
        # 河北的实际控制权——这是百年割据的起点：
        # 朝廷直辖 100，名义归附而藩镇自专 40，仍为叛军所据 0
        "河北": _hebei_score(by_key.get("hebei_plain"), by_key.get("fanyang")),
    }
    # 河北的实际归属权重最高：这正是安史之乱真正的后果所在
    weights = {"两京": 0.20, "乱平": 0.20, "府库": 0.12, "威望": 0.15, "民心": 0.13, "河北": 0.20}
    total = round(sum(raw[k] * weights[k] for k in raw), 1)
    grade, verdict = _grade(total)

    return {
        "reached": True,
        "date": format_date(branch.current_date),
        "months": branch.tick_index,
        "score": total,
        "grade": grade,
        "verdict": verdict,
        "scores": {k: round(v, 1) for k, v in raw.items()},
        "metrics": {
            "treasury": round(tang.treasury) if tang else 0,
            "legitimacy": round(tang.legitimacy, 3) if tang else 0,
            "capitals_held": capitals_held,
            "rebellion_over": rebellion_over,
            "rebel_regions": rebel_regions,
            "autonomous_regions": autonomous_regions,
            "rebel_leader_alive": bool(placed.alive) if placed else False,
        },
    }