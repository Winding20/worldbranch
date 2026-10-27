"""决策：世界主动向用户提出的问题。

设计目的：让"用户不知道该干什么"变成"世界告诉你要决定什么"。
每道决策都带 2–3 个选项，每个选项写明代价与后果，选完立即生效并留下事件。
"""

from __future__ import annotations

import datetime as dt
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

#: 同一类决策在这段时间内不重复提出（月）
COOLDOWN_TICKS = 12


# --------------------------------------------------------------------------- #
# 触发
# --------------------------------------------------------------------------- #
def _has_recent(session: Session, branch_id: int, kind: str, tick: int) -> bool:
    found = session.scalar(
        select(Decision.id)
        .where(
            Decision.branch_id == branch_id,
            Decision.kind == kind,
            Decision.tick_index >= tick - COOLDOWN_TICKS,
        )
        .limit(1)
    )
    return found is not None


def _get_relation(relations: dict[str, RelationState], key: str) -> RelationState | None:
    return relations.get(key)


def raise_decisions(
    session: Session,
    branch: Branch,
    regions: list[RegionState],
    factions: dict[str, FactionState],
    relations: dict[str, RelationState],
) -> list[Decision]:
    """按当前局势决定要不要向用户提问题。"""
    created: list[Decision] = []
    tick = branch.tick_index
    by_key = {r.region_key: r for r in regions}
    fanzhen = factions.get("fanzhen")
    tang = factions.get("tang")
    allegiance = _get_relation(relations, "fanzhen")

    # 1) 藩镇府库见底，上表请饷
    if (
        fanzhen is not None
        and tang is not None
        and fanzhen.treasury < 0
        and not _has_recent(session, branch.id, "warlord_supply", tick)
    ):
        need = int(min(abs(fanzhen.treasury) + 200_000, 1_500_000))
        created.append(
            _make(
                branch,
                kind="warlord_supply",
                title="河北藩镇上表请饷",
                description=(
                    f"河北藩镇府库已透支 {abs(fanzhen.treasury):,.0f} 贯，"
                    f"节度使上表请求朝廷拨付 {need:,} 贯军饷，言辞恭敬，但边军已在议论。"
                ),
                options=[
                    {
                        "key": "grant_full",
                        "label": "如数拨付",
                        "detail": f"府库 −{need:,} 贯，藩镇臣属度 +0.12，年内不会生事",
                        "effects": {
                            "treasury": -need,
                            "relation": {"fanzhen": 0.12},
                        },
                    },
                    {
                        "key": "grant_half",
                        "label": "折半给付",
                        "detail": f"府库 −{need // 2:,} 贯，臣属度 +0.03，边军或有怨言",
                        "effects": {
                            "treasury": -need // 2,
                            "relation": {"fanzhen": 0.03},
                            "unrest": {"hebei": 0.06},
                        },
                    },
                    {
                        "key": "refuse",
                        "label": "断然拒绝",
                        "detail": "府库不减，臣属度 −0.18，河北民变与兵变风险上升",
                        "effects": {
                            "relation": {"fanzhen": -0.18},
                            "unrest": {"hebei": 0.14},
                            "legitimacy": -0.02,
                        },
                    },
                ],
            )
        )

    # 2) 某道缺粮或民变升高，是否赈济
    troubled = [r for r in regions if r.unrest >= 0.35 or r.grain_stock <= 0]
    if troubled and not _has_recent(session, branch.id, "famine_relief", tick):
        worst = max(troubled, key=lambda r: (r.unrest, r.price_index))
        cost = int(worst.population * 0.42 * 1.2)
        created.append(
            _make(
                branch,
                kind="famine_relief",
                title=f"{worst.name}请求赈济",
                description=(
                    f"{worst.name}粮价指数已达 {worst.price_index:.2f}，"
                    f"民变指数 {worst.unrest:.2f}，地方官员请求朝廷开仓或减免赋税。"
                ),
                options=[
                    {
                        "key": "open_granary",
                        "label": "开仓放粮",
                        "detail": f"府库 −{cost:,} 贯，{worst.name}民变 −0.22，粮价回落",
                        "effects": {
                            "treasury": -cost,
                            "unrest": {worst.region_key: -0.22},
                            "grain": {worst.region_key: int(worst.population * 0.42 * 0.9)},
                            "legitimacy": 0.01,
                        },
                    },
                    {
                        "key": "tax_relief",
                        "label": "减免赋税",
                        "detail": f"{worst.name}民变 −0.12，但来年该道税入下降",
                        "effects": {
                            "unrest": {worst.region_key: -0.12},
                            "tax": {worst.region_key: -0.02},
                        },
                    },
                    {
                        "key": "ignore",
                        "label": "暂不处置",
                        "detail": f"不花钱，{worst.name}民变 +0.10，粮价可能继续走高",
                        "effects": {"unrest": {worst.region_key: 0.1}},
                    },
                ],
            )
        )

    # 3) 藩镇离心，是否削藩
    if (
        allegiance is not None
        and allegiance.value < 0.25
        and tang is not None
        and tang.treasury > 0
        and not _has_recent(session, branch.id, "cut_warlord", tick)
    ):
        created.append(
            _make(
                branch,
                kind="cut_warlord",
                title="朝议：是否削藩",
                description=(
                    f"河北藩镇臣属度已降至 {allegiance.value:.2f}，"
                    "朝中有大臣主张趁其未强先行削夺，也有人认为此举必致兵变。"
                ),
                options=[
                    {
                        "key": "cut",
                        "label": "下诏削藩",
                        "detail": "臣属度 −0.30，河北民变 +0.20，朝廷威望 +0.05（成则大治，败则大乱）",
                        "effects": {
                            "relation": {"fanzhen": -0.3},
                            "unrest": {"hebei": 0.2},
                            "legitimacy": 0.05,
                        },
                    },
                    {
                        "key": "appease",
                        "label": "加官安抚",
                        "detail": "府库 −300,000 贯，臣属度 +0.10",
                        "effects": {
                            "treasury": -300_000,
                            "relation": {"fanzhen": 0.1},
                        },
                    },
                    {
                        "key": "wait",
                        "label": "留待后议",
                        "detail": "什么也不做，但臣属度每月自然下滑",
                        "effects": {"relation": {"fanzhen": -0.02}},
                    },
                ],
            )
        )

    for decision in created:
        session.add(decision)
    if created:
        session.flush()
    return created


def _make(
    branch: Branch,
    *,
    kind: str,
    title: str,
    description: str,
    options: list[dict],
    trigger_event_id: int | None = None,
) -> Decision:
    return Decision(
        branch_id=branch.id,
        game_date=branch.current_date,
        tick_index=branch.tick_index,
        kind=kind,
        title=title,
        description=description,
        trigger_event_id=trigger_event_id,
        options=options,
        status="pending",
    )


# --------------------------------------------------------------------------- #
# 决议
# --------------------------------------------------------------------------- #
class DecisionError(ValueError):
    pass


def resolve_decision(
    session: Session,
    branch: Branch,
    decision: Decision,
    option_key: str,
) -> SimEvent:
    """执行用户的选择，把它写回世界并留下一条事件。"""
    if decision.status != "pending":
        raise DecisionError("这道决策已经处理过了")

    option = next((o for o in (decision.options or []) if o["key"] == option_key), None)
    if option is None:
        raise DecisionError(f"没有这个选项: {option_key}")

    effects: dict[str, Any] = option.get("effects") or {}

    tang = session.scalar(
        select(FactionState).where(
            FactionState.branch_id == branch.id, FactionState.faction_key == "tang"
        )
    )
    if tang is not None:
        if effects.get("treasury"):
            tang.treasury += float(effects["treasury"])
        if effects.get("legitimacy"):
            tang.legitimacy = min(max(tang.legitimacy + float(effects["legitimacy"]), 0.0), 1.0)

    for key, delta in (effects.get("relation") or {}).items():
        rel = session.scalar(
            select(RelationState).where(
                RelationState.branch_id == branch.id,
                RelationState.from_key == key,
            )
        )
        if rel is not None:
            rel.value = min(max(rel.value + float(delta), -1.0), 1.0)

    for key, delta in (effects.get("unrest") or {}).items():
        region = session.scalar(
            select(RegionState).where(
                RegionState.branch_id == branch.id, RegionState.region_key == key
            )
        )
        if region is not None:
            region.unrest = min(max(region.unrest + float(delta), 0.0), 1.0)

    for key, delta in (effects.get("grain") or {}).items():
        region = session.scalar(
            select(RegionState).where(
                RegionState.branch_id == branch.id, RegionState.region_key == key
            )
        )
        if region is not None:
            region.grain_stock = max(region.grain_stock + float(delta), 0.0)

    for key, delta in (effects.get("tax") or {}).items():
        region = session.scalar(
            select(RegionState).where(
                RegionState.branch_id == branch.id, RegionState.region_key == key
            )
        )
        if region is not None:
            region.tax_rate = min(max(region.tax_rate + float(delta), 0.0), 0.5)

    event = SimEvent(
        branch_id=branch.id,
        game_date=branch.current_date,
        tick_index=branch.tick_index,
        scope="nation",
        kind="decision",
        severity=4,
        duration_months=1,
        title=f"决策：{decision.title} → {option['label']}",
        summary=option.get("detail") or "",
        region_keys=[],
        faction_keys=["tang"],
        causes=(
            [{"event_id": decision.trigger_event_id, "rel": "caused_by"}]
            if decision.trigger_event_id
            else [{"rule": "decision", "kind": decision.kind}]
        ),
        metrics={"decision_kind": decision.kind, "option": option_key},
    )
    session.add(event)
    session.flush()

    decision.status = "resolved"
    decision.resolved_option = option_key
    decision.resolved_at = dt.datetime.now(dt.timezone.utc)
    decision.result_event_id = event.id
    session.flush()
    return event


def pending_decisions(session: Session, branch_id: int) -> list[Decision]:
    return list(
        session.scalars(
            select(Decision)
            .where(Decision.branch_id == branch_id, Decision.status == "pending")
            .order_by(Decision.tick_index.desc(), Decision.id.desc())
        )
    )


def decision_history(session: Session, branch_id: int, limit: int = 50) -> list[Decision]:
    return list(
        session.scalars(
            select(Decision)
            .where(Decision.branch_id == branch_id)
            .order_by(Decision.id.desc())
            .limit(limit)
        )
    )


def describe_relation(session: Session, branch_id: int) -> list[dict]:
    """把关系翻译成人能读的话。"""
    rows = list(
        session.scalars(
            select(RelationState).where(RelationState.branch_id == branch_id)
        )
    )
    out = []
    for rel in rows:
        value = rel.value
        if value >= 0.6:
            label = "恭顺"
        elif value >= 0.35:
            label = "听命"
        elif value >= 0.2:
            label = "阳奉阴违"
        elif value >= 0.0:
            label = "离心"
        else:
            label = "敌视"
        out.append({**rel.snapshot(), "label": label, "date": format_date(dt.date.today())})
    return out