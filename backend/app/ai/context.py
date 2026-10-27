"""把引擎已经记录的事实整理成给模型看的材料。

**这一层不产生任何新数据**，只做筛选、排序与格式化。
设计文档要求：AI 的解释必须建立在真实模拟记录上，而不是让模型自由发挥。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Branch,
    FactionState,
    RegionState,
    SimEvent,
    World,
)
from ..services import build_event_chain
from ..utils import format_date
from . import knowledge

#: 送进提示词的近期事件条数上限
MAX_RECENT_EVENTS = 12
#: 因果链最多回溯的节点数
MAX_CHAIN_NODES = 8


def _region_lines(states: list[RegionState], limit: int = 7) -> list[str]:
    lines = []
    for r in sorted(states, key=lambda x: -x.price_index)[:limit]:
        lines.append(
            f"- {r.name}：人口 {r.population:,}，存粮 {r.grain_stock:,.0f} 石，"
            f"粮价指数 {r.price_index:.2f}，民变指数 {r.unrest:.2f}，税率 {r.tax_rate:.0%}"
        )
    return lines


def _faction_lines(states: list[FactionState]) -> list[str]:
    return [
        f"- {f.name}：府库 {f.treasury:,.0f}，合法性 {f.legitimacy:.2f}，军额 {f.military:,.0f}"
        for f in states
    ]


def _event_line(e: SimEvent) -> str:
    return f"- [{format_date(e.game_date)}]（{e.scope}/{e.kind}，程度{e.severity}）{e.title}：{e.summary}"


def build_context(
    session: Session,
    branch: Branch,
    *,
    question: str = "",
    event_id: int | None = None,
) -> dict[str, Any]:
    """组装分析材料。返回的每一块都能在界面上溯源。"""
    world = session.get(World, branch.world_id)
    regions = list(
        session.scalars(select(RegionState).where(RegionState.branch_id == branch.id))
    )
    factions = list(
        session.scalars(select(FactionState).where(FactionState.branch_id == branch.id))
    )

    recent = list(
        session.scalars(
            select(SimEvent)
            .where(SimEvent.branch_id == branch.id)
            .order_by(SimEvent.tick_index.desc(), SimEvent.severity.desc())
            .limit(MAX_RECENT_EVENTS)
        )
    )

    focus_event = None
    chain_nodes: list[dict] = []
    if event_id is not None:
        focus = session.get(SimEvent, event_id)
        if focus is None or focus.branch_id != branch.id:
            raise LookupError(f"事件不存在: {event_id}")
        focus_event = focus.to_dict()
        chain = build_event_chain(session, branch.id, event_id)
        chain_nodes = [
            n for n in chain["nodes"] if n["id"] != event_id
        ][-MAX_CHAIN_NODES:]

    # 检索：问题 + 焦点事件标题 + 近期事件标题 一起作为查询
    query_parts = [question]
    if focus_event:
        query_parts.append(focus_event["title"])
    query_parts.extend(e.title for e in recent[:5])
    query = " ".join(p for p in query_parts if p)

    snippets = knowledge.search(session, branch.world_id, query, limit=4)

    provenance = (world.provenance if world else {}) or {}
    return {
        "world": {
            "name": world.name if world else "",
            "era": world.era if world else "",
            "note": "本世界的数值多为量级估算或模拟假设，引用时必须保留可信度说明。",
            "sources": provenance.get("sources", []),
            "caveats": provenance.get("notes", []),
        },
        "branch": {
            "name": branch.name,
            "date": format_date(branch.current_date),
            "tick_index": branch.tick_index,
            "precision": branch.precision,
        },
        "regions": _region_lines(regions),
        "factions": _faction_lines(factions),
        "recent_events": [_event_line(e) for e in recent],
        "focus_event": focus_event,
        "cause_chain": chain_nodes,
        "knowledge": snippets,
        "citation_list": knowledge.citations(snippets),
    }


SYSTEM_PROMPT = """你是 WorldBranch 的世界推演分析助手。

硬性规则：
1. 只能依据下面提供的模拟记录与资料回答，不得编造未记录的事件、人物或数字。
2. 数值直接引用材料里的值；材料没给的就明确说"材料中没有"，不要估算一个看起来合理的数字。
3. 材料里的数值多数是量级估算或模拟假设，引用时要保留可信度提示。
4. 解释因果时，必须沿着材料给出的因果链说明，不要自行发明因果。
5. 用简体中文回答，条理清晰，控制在 400 字以内。
6. 如果问题超出材料范围，直接说明缺什么材料，以及需要补充什么资料。"""


def format_context(ctx: dict[str, Any]) -> str:
    """把结构化材料渲染成提示词里的资料部分。"""
    lines: list[str] = []
    w = ctx["world"]
    lines.append(f"【世界】{w['name']}（{w['era']}）")
    if w["sources"]:
        lines.append(f"【资料来源】{'；'.join(w['sources'])}")
    if w["caveats"]:
        lines.append("【数据可信度说明】" + "；".join(w["caveats"]))

    b = ctx["branch"]
    lines.append(
        f"\n【当前时间线】{b['name']}，日期 {b['date']}，已推进 {b['tick_index']} 个月，"
        f"模拟精度 {b['precision']}"
    )

    lines.append("\n【各道现状】")
    lines.extend(ctx["regions"])

    lines.append("\n【势力状况】")
    lines.extend(ctx["factions"] or ["- 无"])

    lines.append("\n【近期事件】")
    lines.extend(ctx["recent_events"] or ["- 暂无"])

    if ctx["focus_event"]:
        fe = ctx["focus_event"]
        lines.append(f"\n【重点事件】[{fe['game_date']}] {fe['title']}：{fe['summary']}")
        if ctx["cause_chain"]:
            lines.append("【该事件的因果链（由远及近）】")
            for node in ctx["cause_chain"]:
                lines.append(f"  · [{node['game_date']}] {node['title']}")

    if ctx["knowledge"]:
        lines.append("\n【参考资料】")
        for i, s in enumerate(ctx["knowledge"], 1):
            lines.append(
                f"[{i}] {s['title']}（{s['source']}，可信度 {s['reliability']}）：{s['text']}"
            )

    return "\n".join(lines)


def build_messages(ctx: dict[str, Any], question: str) -> list[dict[str, str]]:
    material = format_context(ctx)
    user = (
        f"{material}\n\n"
        f"【用户问题】{question or '请总结当前局势，并指出最值得关注的风险。'}\n\n"
        "请基于以上材料回答。"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]