"""史实事件引擎。

安史之乱模拟器的关键机制：**史实不是剧本，是有前提的**。

每个史实事件都带 conditions。条件成立 → 按史实发生；
条件不成立 → 记为「改道」(diverged)，并说明原事件为何没有发生。
这样用户改了一个决策之后，能直接看到"哪一段历史从这里分岔了"。
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..utils import format_date
from .counsel import attach_advice
from ..models import (
    ArmyState,
    Branch,
    CharacterState,
    Decision,
    FactionState,
    HistoricalEvent,
    HistoricalFire,
    RegionState,
    RelationState,
    SimEvent,
)

#: 到点之后宽限多少个月（史书月份可能有出入，给出容错）
GRACE_MONTHS = 2


def _month_diff(a: dt.date, b: dt.date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def check_conditions(
    conditions: dict[str, Any],
    *,
    regions: dict[str, RegionState],
    characters: dict[str, CharacterState],
    armies: dict[str, ArmyState],
) -> tuple[bool, str]:
    """返回 (是否成立, 不成立的原因)。"""
    if not conditions:
        return True, ""

    for key, value in conditions.items():
        if key == "region_held":
            region = regions.get(value)
            if region is None:
                return False, f"{value} 不在此世界"
            # 地区被叛军占据即视为"已失"
            if region.faction_key != "tang":
                return False, f"{region.name} 已失"
        elif key == "region_lost":
            region = regions.get(value)
            if region is None:
                return False, f"{value} 不在此世界"
            if region.faction_key == "tang":
                return False, f"{region.name} 仍在唐军手中"
        elif key == "character_dead":
            person = characters.get(value)
            if person is None:
                return False, f"{value} 不在此世界"
            if person.alive:
                return False, f"{person.name}尚在"
        elif key == "character_alive":
            person = characters.get(value)
            if person is None:
                return False, f"{value} 不在此世界"
            if not person.alive:
                return False, f"{person.name}已不在"
        else:
            return False, f"未知条件 {key}"

    return True, ""


def run_historical_events(
    session: Session,
    branch: Branch,
    *,
    regions: list[RegionState],
    characters: dict[str, CharacterState],
    armies: dict[str, ArmyState],
    factions: dict[str, FactionState],
    emit_event: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """推进到当前日期后，检查有没有该发生的史实。

    返回 (发生的事件, 改道的事件)，都是给前端展示用的字典。
    """
    fired_rows = {
        row.event_key: row
        for row in session.scalars(
            select(HistoricalFire).where(HistoricalFire.branch_id == branch.id)
        )
    }
    region_map = {r.region_key: r for r in regions}

    events = list(
        session.scalars(
            select(HistoricalEvent)
            .where(HistoricalEvent.world_id == branch.world_id)
            .order_by(HistoricalEvent.date)
        )
    )

    fired: list[dict[str, Any]] = []
    diverged: list[dict[str, Any]] = []
    forks: list[dict[str, Any]] = []

    for event in events:
        if event.key in fired_rows:
            continue
        # 还没到日子
        if event.date > branch.current_date:
            continue
        # 过太久就不追认了（说明前面早就乱套了）
        if _month_diff(event.date, branch.current_date) > GRACE_MONTHS:
            continue

        ok, reason = check_conditions(
            event.conditions or {},
            regions=region_map,
            characters=characters,
            armies=armies,
        )

        # 前提成立、但这件史实带"岔路口"：把决定权交给用户，暂缓发生
        if ok and event.fork:
            decision = Decision(
                branch_id=branch.id,
                game_date=branch.current_date,
                tick_index=branch.tick_index,
                kind="history_fork",
                ref_key=event.key,
                focus_region=_fork_focus(event),
                title=event.fork["title"],
                description=event.fork["description"],
                options=event.fork["options"],
                status="pending",
            )
            session.add(decision)
            session.flush()
            attach_advice(decision, characters, event=event)
            session.add(
                HistoricalFire(
                    branch_id=branch.id,
                    event_key=event.key,
                    game_date=branch.current_date,
                    status="pending",
                    note="",
                )
            )
            session.flush()
            forks.append(decision.to_dict())
            # 岔路口之后的事，必须等用户决定完再判：否则"潼关是否失守"还没定，
            # 依赖它的"长安陷落"就已经被当成不成立而永久改道了。
            break

        if not ok:
            session.add(
                HistoricalFire(
                    branch_id=branch.id,
                    event_key=event.key,
                    game_date=branch.current_date,
                    status="diverged",
                    note=reason,
                )
            )
            diverged.append(
                {
                    "key": event.key,
                    "title": event.title,
                    "expected_date": event.date.isoformat(),
                    "reason": reason,
                    "note": event.divergence_note or f"因{reason}，此事未发生。",
                    "source": event.source,
                }
            )
            continue

        applied = _apply_effects(
            event.effects or {},
            regions=region_map,
            characters=characters,
            armies=armies,
            factions=factions,
        )
        session.add(
            HistoricalFire(
                branch_id=branch.id,
                event_key=event.key,
                game_date=branch.current_date,
                status="fired",
                note="",
            )
        )
        if emit_event is not None:
            # 交给引擎统一分配事件 ID：引擎是按 max(id)+1 手工编号再批量插入的，
            # 这里如果直接 add(SimEvent) 会和引擎的编号撞车。
            emit_event(
                kind="history",
                scope="world",
                severity=5,
                title=event.title,
                summary=event.description,
                region_keys=[],
                faction_keys=[],
                causes=[{"rule": "history", "event_key": event.key}],
                metrics={"historical_key": event.key, "applied": applied},
            )
        else:
            session.add(
                SimEvent(
                    branch_id=branch.id,
                    game_date=branch.current_date,
                    tick_index=branch.tick_index,
                    scope="world",
                    kind="history",
                    severity=5,
                    duration_months=1,
                    title=event.title,
                    summary=event.description,
                    region_keys=[],
                    faction_keys=[],
                    causes=[{"rule": "history", "event_key": event.key}],
                    metrics={"historical_key": event.key, "applied": applied},
                )
            )
        fired.append(
            {
                "key": event.key,
                "title": event.title,
                "date": event.date.isoformat(),
                "description": event.description,
                "category": event.category,
                "applied": applied,
                "source": event.source,
            }
        )

    return fired, diverged, forks


def _fork_focus(event: HistoricalEvent) -> str | None:
    """史实岔路口发生在哪里：优先看事件的得失地与前提条件。"""
    effects = event.effects or {}
    for key in ("lose_region", "gain_region"):
        if effects.get(key):
            return effects[key]
    conditions = event.conditions or {}
    for key in ("region_held", "region_lost"):
        if conditions.get(key):
            return conditions[key]
    return None


def _apply_effects(
    effects: dict[str, Any],
    *,
    regions: dict[str, RegionState],
    characters: dict[str, CharacterState],
    armies: dict[str, ArmyState],
    factions: dict[str, FactionState],
) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []

    if effects.get("lose_region"):
        region = regions.get(effects["lose_region"])
        if region is not None and region.faction_key == "tang":
            region.faction_key = "yan"
            applied.append({"label": f"{region.name}失守", "before": "唐", "after": "燕"})

    # 名义归附：叛军投降，州郡在名义上归唐，实则由降将自专
    for key in effects.get("nominal_control") or []:
        region = regions.get(key)
        if region is not None:
            before = "燕" if region.faction_key != "tang" else "唐"
            region.faction_key = "tang"
            region.autonomous = True
            applied.append(
                {"label": f"{region.name}名义归附", "before": before, "after": "唐（藩镇自专）"}
            )

    if effects.get("gain_region"):
        region = regions.get(effects["gain_region"])
        if region is not None and region.faction_key != "tang":
            region.faction_key = "tang"
            applied.append({"label": f"收复{region.name}", "before": "燕", "after": "唐"})

    # 同一次收复里连带收回的据点（如收复长安时一并复潼关）
    for key in effects.get("gain_region_extra") or []:
        region = regions.get(key)
        if region is not None and region.faction_key != "tang":
            region.faction_key = "tang"
            region.autonomous = False
            applied.append({"label": f"收复{region.name}", "before": "燕", "after": "唐"})

    for key in effects.get("kill") or []:
        person = characters.get(key)
        if person is not None and person.alive:
            person.alive = False
            applied.append({"label": f"{person.name}身死", "before": "在世", "after": "殁"})

    tang = factions.get("tang")
    if tang is not None:
        if effects.get("treasury"):
            before = tang.treasury
            tang.treasury += float(effects["treasury"])
            applied.append(
                {
                    "label": "朝廷府库",
                    "before": round(before, 0),
                    "after": round(tang.treasury, 0),
                }
            )
        if effects.get("legitimacy"):
            before = tang.legitimacy
            tang.legitimacy = min(max(tang.legitimacy + float(effects["legitimacy"]), 0.0), 1.0)
            applied.append(
                {
                    "label": "朝廷威望",
                    "before": round(before, 3),
                    "after": round(tang.legitimacy, 3),
                }
            )

    for army_key, delta in (effects.get("morale") or {}).items():
        army = armies.get(army_key)
        if army is not None:
            before = army.morale
            army.morale = min(max(army.morale + float(delta), 0.0), 1.0)
            applied.append(
                {
                    "label": f"{army.name}士气",
                    "before": round(before, 3),
                    "after": round(army.morale, 3),
                }
            )

    for army_key, delta in (effects.get("supply") or {}).items():
        army = armies.get(army_key)
        if army is not None:
            before = army.supply
            army.supply = min(max(army.supply + float(delta), 0.0), 1.0)
            applied.append(
                {
                    "label": f"{army.name}补给",
                    "before": round(before, 3),
                    "after": round(army.supply, 3),
                }
            )

    return applied


def resolve_fork(
    session: Session, branch: Branch, decision: Decision, option_key: str
) -> SimEvent:
    """用户在历史岔路口上做出选择。

    选「按史载」→ 事件照史发生；选别的 → 事件改道，并记录原因。
    """
    event = session.scalar(
        select(HistoricalEvent).where(
            HistoricalEvent.world_id == branch.world_id,
            HistoricalEvent.key == decision.ref_key,
        )
    )
    if event is None:
        raise ValueError(f"找不到史实事件 {decision.ref_key}")

    option = next((o for o in (decision.options or []) if o["key"] == option_key), None)
    if option is None:
        raise ValueError(f"没有这个选项: {option_key}")

    regions = {
        r.region_key: r
        for r in session.scalars(
            select(RegionState).where(RegionState.branch_id == branch.id)
        )
    }
    characters = {
        c.character_key: c
        for c in session.scalars(
            select(CharacterState).where(CharacterState.branch_id == branch.id)
        )
    }
    armies = {
        a.army_key: a
        for a in session.scalars(
            select(ArmyState).where(ArmyState.branch_id == branch.id)
        )
    }
    factions = {
        f.faction_key: f
        for f in session.scalars(
            select(FactionState).where(FactionState.branch_id == branch.id)
        )
    }

    follow_history = option.get("outcome") == "historical"
    # 按史载时，事件效果与选项自带的补充效果都要生效：
    # 例如「就地授节度使」既是史实结果，也要把河北标成藩镇自专。
    effects = dict(event.effects or {})
    for key, value in (option.get("effects") or {}).items():
        if isinstance(value, dict) and isinstance(effects.get(key), dict):
            effects[key] = {**effects[key], **value}
        else:
            effects[key] = value
    if not follow_history:
        effects = option.get("effects") or {}
    applied = _apply_effects(
        effects,
        regions=regions,
        characters=characters,
        armies=armies,
        factions=factions,
    )

    fire = session.scalar(
        select(HistoricalFire).where(
            HistoricalFire.branch_id == branch.id,
            HistoricalFire.event_key == event.key,
            HistoricalFire.status == "pending",
        )
    )
    if fire is not None:
        fire.status = "fired" if follow_history else "diverged"
        fire.note = "" if follow_history else f"朝廷选择「{option['label']}」"

    title = event.title if follow_history else f"{event.title}未发生（{option['label']}）"
    summary = (
        event.description
        if follow_history
        else (event.divergence_note or option.get("detail", ""))
    )

    sim = SimEvent(
        branch_id=branch.id,
        game_date=branch.current_date,
        tick_index=branch.tick_index,
        scope="world",
        kind="history_fork",
        severity=5,
        duration_months=1,
        title=title,
        summary=summary,
        region_keys=[],
        faction_keys=[],
        causes=[{"rule": "history_fork", "event_key": event.key, "option": option_key}],
        metrics={
            "historical_key": event.key,
            "option": option_key,
            "follow_history": follow_history,
            "applied": applied,
        },
    )
    session.add(sim)
    session.flush()

    # 必须把决策标记为已处理：否则每轮查询都会把它当成"还待决"，
    # 用户会看到同一份奏疏反复出现，效果也被重复施加。
    decision.status = "resolved"
    decision.resolved_option = option_key
    decision.resolved_at = dt.datetime.now(dt.timezone.utc)
    decision.result_event_id = sim.id
    session.flush()
    return sim


def history_status(session: Session, branch_id: int) -> dict[str, Any]:
    """这条时间线上，哪些史实发生了、哪些改道了。"""
    rows = list(
        session.scalars(
            select(HistoricalFire)
            .where(HistoricalFire.branch_id == branch_id)
            .order_by(HistoricalFire.id)
        )
    )
    # 补上标题，界面与 AI 材料里直接读得懂
    # 显示用史实自身的年月，而不是"引擎发现它"的那一个月
    templates = {
        e.key: e
        for e in session.scalars(
            select(HistoricalEvent).where(
                HistoricalEvent.world_id == session.get(Branch, branch_id).world_id
            )
        )
    }

    def _title(key: str) -> str:
        event = templates.get(key)
        return event.title if event else key

    def _date(key: str, fallback: dt.date) -> str:
        event = templates.get(key)
        return format_date(event.date if event else fallback)
    return {
        "fired": [
            {
                "key": r.event_key,
                "title": _title(r.event_key),
                "date": _date(r.event_key, r.game_date),
            }
            for r in rows
            if r.status == "fired"
        ],
        "diverged": [
            {
                "key": r.event_key,
                "title": _title(r.event_key),
                "date": _date(r.event_key, r.game_date),
                "reason": r.note,
            }
            for r in rows
            if r.status == "diverged"
        ],
    }