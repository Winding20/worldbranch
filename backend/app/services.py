"""世界与分支的服务层：创建、派生、查询。

放在引擎之外，避免引擎直接依赖 HTTP 或命令行。
"""

from __future__ import annotations

import datetime as dt
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    ArmyState,
    Branch,
    CharacterState,
    Decision,
    Faction,
    FactionState,
    Region,
    RegionState,
    RelationState,
    SimEvent,
    World,
)


class WorldNotFound(LookupError):
    pass


class BranchNotFound(LookupError):
    pass


def get_world_by_key(session: Session, key: str) -> World:
    world = session.scalar(select(World).where(World.key == key))
    if world is None:
        raise WorldNotFound(f"世界不存在: {key}")
    return world


def list_worlds(session: Session) -> Sequence[World]:
    return list(session.scalars(select(World).order_by(World.id)))


def _raised(raises_at: dt.date | None, start_date: dt.date) -> bool:
    """成军之日早于（或等于）开局日期，才算开局已有此军。"""
    if raises_at is None:
        return True
    return raises_at <= start_date


def create_branch(
    session: Session,
    world: World,
    *,
    name: str | None = None,
    precision: str = "standard",
    seed: int = 1,
    start_date: dt.date | None = None,
) -> Branch:
    """从世界模板开出一条新分支，并复制初始状态。"""
    branch = Branch(
        world_id=world.id,
        name=name or f"{world.name}·{world.start_date.isoformat()}",
        seed=seed,
        precision=precision,
        current_date=start_date or world.start_date,
        tick_index=0,
    )
    session.add(branch)
    session.flush()

    for region in world.regions:
        session.add(
            RegionState(
                branch_id=branch.id,
                region_key=region.key,
                name=region.name,
                population=region.population,
                grain_stock=region.grain_stock,
                farmland=region.farmland,
                tax_rate=region.tax_rate,
                price_index=region.price_index,
                unrest=region.unrest,
                faction_key=region.faction_key,
            )
        )
    for faction in world.factions:
        session.add(
            FactionState(
                branch_id=branch.id,
                faction_key=faction.key,
                name=faction.name,
                treasury=faction.treasury,
                legitimacy=faction.legitimacy,
                military=faction.military,
            )
        )
    for relation in world.relations:
        session.add(
            RelationState(
                branch_id=branch.id,
                from_key=relation.from_key,
                to_key=relation.to_key,
                kind=relation.kind,
                value=relation.value,
            )
        )
    # 唐史推演：人物与军队也要落成分支状态，否则人物之死、军队易主无法记录
    for person in world.characters:
        session.add(
            CharacterState(
                branch_id=branch.id,
                character_key=person.key,
                name=person.name,
                faction_key=person.faction_key,
                role=person.role,
                office=person.office,
                office_rank=person.office_rank,
                office_kind=person.office_kind,
                loyalty=person.loyalty,
                ambition=person.ambition,
                ability=person.ability,
                location_region_key=person.location_region_key,
                alive=person.alive,
            )
        )
    for army in world.armies:
        session.add(
            ArmyState(
                branch_id=branch.id,
                army_key=army.key,
                name=army.name,
                faction_key=army.faction_key,
                commander_key=army.commander_key,
                region_key=army.region_key,
                # 尚未成军的部队先按零兵计，免得开局战力虚高
                troops=army.troops if _raised(army.raises_at, world.start_date) else 0,
                morale=army.morale,
                supply=army.supply,
                troops_max=army.troops,
                raises_at=army.raises_at,
                raised=_raised(army.raises_at, world.start_date),
            )
        )
    session.flush()
    return branch


def fork_branch(
    session: Session,
    source: Branch,
    *,
    name: str | None = None,
    seed: int | None = None,
) -> Branch:
    """从当前时刻复制一条独立分支。

    设计文档要求：分支隔离、可复现。因此复制的是「此刻的状态」，
    而不是重新从世界模板开始，历史事件也留在原分支。
    """
    branch = Branch(
        world_id=source.world_id,
        name=name or f"{source.name}·分支{source.id}",
        seed=seed if seed is not None else source.seed + 1,
        precision=source.precision,
        current_date=source.current_date,
        tick_index=source.tick_index,
        parent_branch_id=source.id,
        forked_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(branch)
    session.flush()

    for state in session.scalars(
        select(RegionState).where(RegionState.branch_id == source.id)
    ):
        session.add(
            RegionState(
                branch_id=branch.id,
                region_key=state.region_key,
                name=state.name,
                population=state.population,
                grain_stock=state.grain_stock,
                farmland=state.farmland,
                tax_rate=state.tax_rate,
                price_index=state.price_index,
                unrest=state.unrest,
                faction_key=state.faction_key,
            )
        )
    for state in session.scalars(
        select(FactionState).where(FactionState.branch_id == source.id)
    ):
        session.add(
            FactionState(
                branch_id=branch.id,
                faction_key=state.faction_key,
                name=state.name,
                treasury=state.treasury,
                legitimacy=state.legitimacy,
                military=state.military,
            )
        )
    for relation in session.scalars(
        select(RelationState).where(RelationState.branch_id == source.id)
    ):
        session.add(
            RelationState(
                branch_id=branch.id,
                from_key=relation.from_key,
                to_key=relation.to_key,
                kind=relation.kind,
                value=relation.value,
            )
        )

    # 派生点之前的历史是两条时间线共有的既成事实，一并复制；
    # 派生之后各自产生的事件才互相隔离。
    for event in session.scalars(
        select(SimEvent).where(
            SimEvent.branch_id == source.id,
            SimEvent.tick_index <= source.tick_index,
        )
    ):
        session.add(
            SimEvent(
                branch_id=branch.id,
                game_date=event.game_date,
                tick_index=event.tick_index,
                scope=event.scope,
                kind=event.kind,
                severity=event.severity,
                duration_months=event.duration_months,
                title=event.title,
                summary=event.summary,
                region_keys=list(event.region_keys or []),
                faction_keys=list(event.faction_keys or []),
                causes=list(event.causes or []),
                metrics=dict(event.metrics or {}),
            )
        )

    session.flush()
    return branch


def get_branch(session: Session, branch_id: int) -> Branch:
    branch = session.get(Branch, branch_id)
    if branch is None:
        raise BranchNotFound(f"分支不存在: {branch_id}")
    return branch


def region_geo_map(session: Session, world_id: int) -> dict[str, dict]:
    """地区 key -> 地理信息，供地图渲染。"""
    out: dict[str, dict] = {}
    for region in session.scalars(select(Region).where(Region.world_id == world_id)):
        out[region.key] = {
            "name": region.name,
            "level": region.level,
            "lat": region.lat,
            "lon": region.lon,
            "geo": region.geo,
            "data_quality": region.data_quality or {},
        }
    return out


def faction_meta(session: Session, world_id: int) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for faction in session.scalars(
        select(Faction).where(Faction.world_id == world_id)
    ):
        out[faction.key] = {
            "name": faction.name,
            "kind": faction.kind,
            "capital_region_key": faction.capital_region_key,
        }
    return out


# --------------------------------------------------------------------------- #
# 用户干预
# --------------------------------------------------------------------------- #
class ActionError(ValueError):
    pass


#: 支持的用户干预类型
ACTION_KINDS = ("shock", "relief", "tax")


def apply_action(
    session: Session,
    branch: Branch,
    kind: str,
    region_key: str,
    params: dict,
) -> SimEvent:
    """用户在某一时刻对世界施加的干预。

    干预是"因果链的起点"：它会写入一条事件，后续由它引发的粮荒、调运
    都会把这条事件挂成原因，于是用户能在界面上看到自己造成了什么。
    """
    if kind not in ACTION_KINDS:
        raise ActionError(f"不支持的干预类型: {kind}")

    state = session.scalar(
        select(RegionState).where(
            RegionState.branch_id == branch.id,
            RegionState.region_key == region_key,
        )
    )
    if state is None:
        raise LookupError(f"地区不存在: {region_key}")

    title = ""
    summary = ""
    kind_code = ""
    metrics: dict = {"region_key": region_key}

    if kind == "shock":
        ratio = float(params.get("damage_ratio", 0.5))
        if not 0 < ratio <= 1:
            raise ActionError("damage_ratio 必须在 (0, 1] 之间")
        lost = state.grain_stock * ratio
        state.grain_stock = max(state.grain_stock - lost, 0.0)
        kind_code = "user_shock"
        title = f"（干预）{state.name}歉收"
        summary = (
            f"用户在该道制造了一次歉收：当季存粮减少 {lost:,.0f} 石"
            f"（约 {ratio * 100:.0f}%）。"
        )
        metrics.update({"damage_ratio": ratio, "lost": round(lost, 1)})

    elif kind == "relief":
        amount = float(params.get("amount", 0))
        if amount <= 0:
            raise ActionError("amount 必须大于 0")
        price = state.price_index
        state.grain_stock += amount
        faction = session.scalar(
            select(FactionState).where(
                FactionState.branch_id == branch.id,
                FactionState.faction_key == state.faction_key,
            )
        ) if state.faction_key else None
        cost = amount * price
        if faction is not None:
            faction.treasury -= cost
        kind_code = "user_relief"
        title = f"（干预）{state.name}开仓赈济"
        summary = (
            f"用户调拨 {amount:,.0f} 石粮食进入{state.name}，"
            f"按当季粮价折合支出 {cost:,.0f} 贯。"
        )
        metrics.update({"amount": amount, "cost": round(cost, 1)})

    else:  # tax
        rate = float(params.get("rate", state.tax_rate))
        if not 0 <= rate <= 0.5:
            raise ActionError("税率必须在 0~0.5 之间")
        old = state.tax_rate
        state.tax_rate = rate
        kind_code = "user_tax"
        title = f"（干预）{state.name}税率调整"
        summary = f"用户把{state.name}的税率从 {old * 100:.0f}% 调整为 {rate * 100:.0f}%。"
        metrics.update({"from": old, "to": rate})

    event = SimEvent(
        branch_id=branch.id,
        game_date=branch.current_date,
        tick_index=branch.tick_index,
        scope="region",
        kind=kind_code,
        severity=3,
        duration_months=1,
        title=title,
        summary=summary,
        region_keys=[region_key],
        faction_keys=[state.faction_key] if state.faction_key else [],
        causes=[{"rule": "user_action", "kind": kind}],
        metrics=metrics,
    )
    session.add(event)
    session.flush()
    return event


# --------------------------------------------------------------------------- #
# 因果链
# --------------------------------------------------------------------------- #
def cause_event_ids(event: SimEvent) -> list[int]:
    """从事件的 causes 里挑出指向其它事件的 id。"""
    ids: list[int] = []
    for cause in event.causes or []:
        if isinstance(cause, dict) and isinstance(cause.get("event_id"), int):
            ids.append(cause["event_id"])
    return ids


def build_event_chain(
    session: Session,
    branch_id: int,
    event_id: int,
    *,
    max_depth: int = 6,
) -> dict:
    """回溯一个事件的上游因果链。

    设计文档要求：影响必须由规则和数据支持，不能仅凭 AI 叙述。
    因此「为什么发生」是从事件记录里查出来的，而不是让模型编。
    """
    root = session.get(SimEvent, event_id)
    if root is None or root.branch_id != branch_id:
        raise LookupError(f"事件不存在: {event_id}")

    nodes: dict[int, dict] = {}
    edges: list[dict] = []
    frontier = [root]
    depth_map = {root.id: 0}

    while frontier:
        current = frontier.pop()
        nodes[current.id] = current.to_dict()
        depth = depth_map[current.id]
        if depth >= max_depth:
            continue
        for parent_id in cause_event_ids(current):
            parent = session.get(SimEvent, parent_id)
            if parent is None or parent.branch_id != branch_id:
                continue
            edges.append({"from": parent_id, "to": current.id, "rel": "cause"})
            if parent_id not in depth_map:
                depth_map[parent_id] = depth + 1
                frontier.append(parent)

    return {
        "root_id": event_id,
        "nodes": sorted(nodes.values(), key=lambda n: (n["game_date"], n["id"])),
        "edges": edges,
    }


# --------------------------------------------------------------------------- #
# 多尺度观察
# --------------------------------------------------------------------------- #
#: 观察尺度 -> 聚合方式
SCALES = ("world", "nation", "region", "local")


def aggregate_by_scale(session: Session, branch: Branch, scale: str) -> dict:
    """按观察尺度聚合世界状态。

    设计文档的核心要求：地图缩放不制造也不隐藏数据，只是换一种聚合方式。
    因此这里不产生任何新数据，只是把同一批 RegionState 按势力或按道汇总。
    """
    if scale not in SCALES:
        raise ValueError(f"未知的观察尺度: {scale}")

    states = list(
        session.scalars(
            select(RegionState).where(RegionState.branch_id == branch.id)
        )
    )
    faction_states = {
        f.faction_key: f
        for f in session.scalars(
            select(FactionState).where(FactionState.branch_id == branch.id)
        )
    }
    meta = faction_meta(session, branch.world_id)

    def unit_payload(key: str, name: str, kind: str, members: list[RegionState]) -> dict:
        total_pop = sum(r.population for r in members) or 1
        weighted_price = sum(
            r.price_index * r.population for r in members
        ) / total_pop
        faction = faction_states.get(key)
        return {
            "key": key,
            "name": name,
            "kind": kind,
            "region_keys": [r.region_key for r in members],
            "metrics": {
                "population": total_pop,
                "grain_stock": round(sum(r.grain_stock for r in members), 1),
                "price_index": round(weighted_price, 4),
                "unrest_max": round(max((r.unrest for r in members), default=0.0), 4),
                "region_count": len(members),
                "treasury": round(faction.treasury, 1) if faction else None,
                "legitimacy": round(faction.legitimacy, 4) if faction else None,
            },
            "capital_region_key": meta.get(key, {}).get("capital_region_key"),
        }

    if scale == "world":
        # 最宏观：只看势力。世界级只应呈现战争、联盟、全局灾难这个量级的事。
        by_faction: dict[str, list[RegionState]] = {}
        for r in states:
            by_faction.setdefault(r.faction_key or "unknown", []).append(r)
        units = [
            unit_payload(
                key,
                meta.get(key, {}).get("name", key),
                "faction",
                members,
            )
            for key, members in sorted(by_faction.items())
        ]
        event_scopes = ["world", "nation"]

    elif scale == "nation":
        # 国家级：仍是势力视角，但带上治所，便于看朝堂与藩镇的对比
        by_faction = {}
        for r in states:
            by_faction.setdefault(r.faction_key or "unknown", []).append(r)
        units = [
            unit_payload(key, meta.get(key, {}).get("name", key), "faction", members)
            for key, members in sorted(by_faction.items())
        ]
        event_scopes = ["nation", "region"]

    else:
        # 地区级 / 局部级：回到逐个道
        units = [
            unit_payload(r.region_key, r.name, "region", [r])
            for r in sorted(states, key=lambda x: x.region_key)
        ]
        event_scopes = ["region", "local"] if scale == "local" else ["region"]

    return {
        "scale": scale,
        "branch": branch.to_dict(),
        "units": units,
        "event_scopes": event_scopes,
    }
#: 对比时关注的地区指标
REGION_METRICS = ("population", "grain_stock", "price_index", "unrest", "tax_rate")


def ancestor_chain(session: Session, branch: Branch) -> list[Branch]:
    """从当前分支一路回溯到根分支。"""
    chain: list[Branch] = [branch]
    seen = {branch.id}
    current = branch
    while current.parent_branch_id and current.parent_branch_id not in seen:
        parent = session.get(Branch, current.parent_branch_id)
        if parent is None:
            break
        chain.append(parent)
        seen.add(parent.id)
        current = parent
    return chain


def _event_signature(event: SimEvent) -> tuple:
    """用来判断两条分支里是不是"同一件事"。

    派生分支会复制派生点之前的历史事件，但主键是新的，所以不能比 id。
    """
    return (event.tick_index, event.kind, event.title)


def compare_branches(session: Session, left: Branch, right: Branch) -> dict:
    """对比两条时间线：状态差异 + 分叉点 + 各自独有的事件。"""
    if left.world_id != right.world_id:
        raise ValueError("只能对比同一个世界内的分支")

    left_states = {
        s.region_key: s
        for s in session.scalars(
            select(RegionState).where(RegionState.branch_id == left.id)
        )
    }
    right_states = {
        s.region_key: s
        for s in session.scalars(
            select(RegionState).where(RegionState.branch_id == right.id)
        )
    }

    regions = []
    for key in sorted(set(left_states) | set(right_states)):
        a = left_states.get(key)
        b = right_states.get(key)
        name = (a or b).name
        row = {"region_key": key, "name": name, "left": {}, "right": {}, "delta": {}}
        for metric in REGION_METRICS:
            av = getattr(a, metric, None)
            bv = getattr(b, metric, None)
            row["left"][metric] = av
            row["right"][metric] = bv
            if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                row["delta"][metric] = round(bv - av, 4)
            else:
                row["delta"][metric] = None
        regions.append(row)

    left_events = list(
        session.scalars(select(SimEvent).where(SimEvent.branch_id == left.id))
    )
    right_events = list(
        session.scalars(select(SimEvent).where(SimEvent.branch_id == right.id))
    )
    left_sigs = {_event_signature(e) for e in left_events}
    right_sigs = {_event_signature(e) for e in right_events}
    common = left_sigs & right_sigs

    def pick(events, sigs):
        return sorted(
            (e.to_dict() for e in events if _event_signature(e) in sigs),
            key=lambda d: (d["game_date"], d["id"]),
        )

    # 分叉点：两条分支最近的共同祖先决定了它们从哪里开始不同
    left_chain = {b.id: b for b in ancestor_chain(session, left)}
    right_chain = {b.id: b for b in ancestor_chain(session, right)}
    shared = set(left_chain) & set(right_chain)
    common_ancestor = None
    if shared:
        # 取 tick 最大的那个共同祖先（离现在最近的汇合点）
        common_ancestor = max(
            (left_chain[i] for i in shared), key=lambda b: b.tick_index
        )

    return {
        "left": left.to_dict(),
        "right": right.to_dict(),
        "regions": regions,
        "events": {
            "left_only": pick(left_events, left_sigs - right_sigs),
            "right_only": pick(right_events, right_sigs - left_sigs),
            "common_count": len(common),
        },
        "divergence": {
            "common_ancestor_id": common_ancestor.id if common_ancestor else None,
            "common_ancestor_name": common_ancestor.name if common_ancestor else None,
            "same_branch": left.id == right.id,
            #: left 是 right 的祖先（即 right 从 left 派生出来）
            "left_ancestor_of_right": left.id in right_chain,
            #: right 是 left 的祖先
            "right_ancestor_of_left": right.id in left_chain,
        },
    }