"""结局评估：五年之后，这个天下成了什么样。

用户的目标是"撑过五年"，所以必须有一个终点来回答"我做得怎么样"。
评分只用引擎已经记录的事实，不做任何叙事性发挥。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Branch,
    Decision,
    FactionState,
    RegionState,
    RelationState,
    SimEvent,
)
from ..utils import format_date

#: 从开局算起多少个月算"五年"
HORIZON_MONTHS = 60

#: 评级门槛（总分 0–100）
GRADES = (
    (80, "大治", "仓廪充实，藩镇敛手，民无离散。"),
    (65, "中兴", "虽有小乱，根基未动，天下可期。"),
    (45, "苟安", "勉强维持，隐患仍在，只待时日。"),
    (25, "倾危", "府库见底，人心浮动，已在崩坏的边缘。"),
    (0, "崩坏", "藩镇坐大，民变四起，朝廷号令不出关中。"),
)


def _grade(score: float) -> tuple[str, str]:
    for threshold, name, label in GRADES:
        if score >= threshold:
            return name, label
    return GRADES[-1][1], GRADES[-1][2]


def evaluate_ending(session: Session, branch: Branch) -> dict[str, Any] | None:
    """返回结局；未到五年则返回 None。"""
    if branch.tick_index < HORIZON_MONTHS:
        return None

    regions = list(
        session.scalars(
            select(RegionState).where(RegionState.branch_id == branch.id)
        )
    )
    factions = {
        f.faction_key: f
        for f in session.scalars(
            select(FactionState).where(FactionState.branch_id == branch.id)
        )
    }
    relation = session.scalar(
        select(RelationState).where(
            RelationState.branch_id == branch.id,
            RelationState.from_key == "fanzhen",
        )
    )
    tang = factions.get("tang")

    avg_price = sum(r.price_index for r in regions) / max(len(regions), 1)
    max_unrest = max((r.unrest for r in regions), default=0.0)
    avg_unrest = sum(r.unrest for r in regions) / max(len(regions), 1)
    treasury = tang.treasury if tang else 0.0
    legitimacy = tang.legitimacy if tang else 0.5
    allegiance = relation.value if relation else 0.5

    # 每项先算 0–100 的自身得分，再按权重合成总分。
    # 民心同时看平均与峰值：一个道烧起来，不能靠其它道平均掉。
    unrest_pressure = avg_unrest * 0.6 + max_unrest * 0.4
    raw = {
        "府库": _norm(treasury, 0, 8_000_000) * 100,
        "民心": (1 - _clamp(unrest_pressure / 0.6)) * 100,
        "粮价": (1 - _clamp((avg_price - 0.8) / 2.2)) * 100,
        "藩镇": _clamp(allegiance / 0.7) * 100,
        "威望": _clamp(legitimacy) * 100,
    }
    weights = {"府库": 0.30, "民心": 0.25, "粮价": 0.15, "藩镇": 0.20, "威望": 0.10}
    total = round(sum(raw[k] * weights[k] for k in raw), 1)
    grade, label = _grade(total)

    decisions = list(
        session.scalars(
            select(Decision).where(
                Decision.branch_id == branch.id, Decision.status == "resolved"
            )
        )
    )
    event_count = len(
        list(
            session.scalars(
                select(SimEvent.id).where(SimEvent.branch_id == branch.id)
            )
        )
    )

    return {
        "reached": True,
        "date": format_date(branch.current_date),
        "months": branch.tick_index,
        "score": total,
        "grade": grade,
        "verdict": label,
        "scores": {k: round(v, 1) for k, v in raw.items()},
        "metrics": {
            "treasury": round(treasury, 0),
            "legitimacy": round(legitimacy, 3),
            "allegiance": round(allegiance, 3),
            "avg_price": round(avg_price, 3),
            "max_unrest": round(max_unrest, 3),
            "decisions_made": len(decisions),
            "events": event_count,
        },
    }


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


def _norm(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return _clamp((value - low) / (high - low))