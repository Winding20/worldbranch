"""模拟引擎：按规则推进时间、更新状态、生成事件。

引擎只负责「算」，不做任何叙述性生成；AI 分析属于后续层。
所有随机都来自按 (seed, tick) 派生的独立随机源，保证同一分支可复现。
"""

from __future__ import annotations

import calendar
import datetime as dt
import random
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    ArmyState,
    Branch,
    CharacterState,
    FactionState,
    RegionState,
    RelationState,
    SimEvent,
    Snapshot,
    TradeLink,
)
from ..utils import format_date
from . import decisions, history, loyalty, rules

#: 精度档位 -> (最低事件等级, 是否生成局部事件, 灾害骰子次数)
PRECISION_PROFILE: dict[str, tuple[int, bool, int]] = {
    "macro": (3, False, 1),
    "standard": (2, False, 1),
    "fine": (1, False, 2),
    "deep": (1, True, 3),
}

#: 单月发生农事灾害的基础概率（每掷一次骰子）
SHOCK_BASE_PROB = 0.02


def add_months(day: dt.date, months: int) -> dt.date:
    """按自然月推进，保留到当月合法日期。"""
    total = day.year * 12 + (day.month - 1) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, min(day.day, last))


@dataclass
class TickReport:
    branch_id: int
    months: int
    from_date: dt.date
    to_date: dt.date
    events: list[dict[str, Any]] = field(default_factory=list)
    region_states: list[dict[str, Any]] = field(default_factory=list)
    faction_states: list[dict[str, Any]] = field(default_factory=list)
    #: 推进前后的差异摘要（只包含有变化的地区）
    changes: list[dict[str, Any]] = field(default_factory=list)
    #: 本次推进后新出现的决策
    decisions: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    history_fired: list[dict[str, Any]] = field(default_factory=list)
    history_diverged: list[dict[str, Any]] = field(default_factory=list)
    history_forks: list[dict[str, Any]] = field(default_factory=list)
    #: 本轮叛离的人物
    defections: list[dict[str, Any]] = field(default_factory=list)
    #: 是否因为出现岔路口而提前停下
    paused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "months": self.months,
            "from_date": format_date(self.from_date),
            "to_date": format_date(self.to_date),
            "event_count": len(self.events),
            "events": self.events,
            "region_states": self.region_states,
            "faction_states": self.faction_states,
            "changes": self.changes,
            "decisions": self.decisions,
            "relations": self.relations,
            "history_fired": self.history_fired,
            "history_diverged": self.history_diverged,
            "history_forks": self.history_forks,
            "defections": self.defections,
            "paused": self.paused,
        }


class SimulationEngine:
    """在给定 Session 上推进一条分支。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ---------------------------------------------------------------- #
    def advance(
        self,
        branch: Branch,
        months: int = 1,
        *,
        precision: str | None = None,
    ) -> TickReport:
        if months < 1:
            raise ValueError("months 必须 >= 1")
        if months > 120:
            raise ValueError("单次推进不超过 120 个月")

        if precision is not None:
            if precision not in PRECISION_PROFILE:
                raise ValueError(f"未知精度档位: {precision}")
            branch.precision = precision
        profile = PRECISION_PROFILE.get(branch.precision, PRECISION_PROFILE["standard"])

        regions = list(
            self.session.scalars(
                select(RegionState).where(RegionState.branch_id == branch.id)
            )
        )
        factions = {
            f.faction_key: f
            for f in self.session.scalars(
                select(FactionState).where(FactionState.branch_id == branch.id)
            )
        }

        from_date = branch.current_date
        report = TickReport(
            branch_id=branch.id,
            months=months,
            from_date=from_date,
            to_date=from_date,
        )
        #: 推进前后的差异，用于给用户"这一个月到底变了什么"
        before = {
            r.region_key: (r.grain_stock, r.price_index, r.unrest) for r in regions
        }

        # 性能要点：远程数据库每次往返约 30-40ms，逐 tick 写库会让「推进 24 个月」
        # 变成上百次往返（实测 4.4 秒）。这里把事件与快照全部在内存里攒成
        # 普通字典，最后用 Core 批量 INSERT 一次写入。
        # 用 ORM 对象的话，SQLAlchemy 为了取回自增主键会把批量插入退化成逐条
        # INSERT，往返次数仍然随月数线性增长；走 Core 就不需要回填主键。
        pending_events: list[dict] = []
        pending_snapshots: list[dict] = []
        self._pending_events = pending_events

        # 事件要能互相引用（因果链），所以主键由引擎自己分配。
        # 走 Core 批量插入拿不回自增 ID，而逐条插入又会把远程往返拉回线性增长。
        max_id = self.session.scalar(select(func.max(SimEvent.id))) or 0
        self._next_event_id = int(max_id) + 1
        #: 每个道上次播报粮荒的 (tick, 严重度)，用来压制逐月重复刷屏
        self._last_famine: dict[str, tuple[int, int]] = {}
        #: 仍在持续的粮荒事件 id，供后续调运事件挂因果
        self._active_famine_event: dict[str, int] = {}
        #: 该分支最近一次用户干预（歉收）事件，按地区索引，用于串起因果链
        self._recent_shock: dict[str, int] = {}
        #: 本轮发生过灾害的道，用于触发赈济类决策
        self._shocked_keys: set[str] = set()
        recent = self.session.execute(
            select(SimEvent.id, SimEvent.region_keys)
            .where(
                SimEvent.branch_id == branch.id,
                SimEvent.kind == "user_shock",
                SimEvent.tick_index >= max(branch.tick_index - 24, 0),
            )
            .order_by(SimEvent.tick_index.desc())
        )
        for event_id, region_keys in recent:
            for key in region_keys or []:
                self._recent_shock.setdefault(key, event_id)

        links = list(
            self.session.scalars(
                select(TradeLink).where(TradeLink.world_id == branch.world_id)
            )
        )
        # 藩镇一旦敌视，河北粮道即被掐断——这是"拒不付饷"的真实代价
        relation_now = self.session.scalar(
            select(RelationState).where(
                RelationState.branch_id == branch.id,
                RelationState.from_key == "fanzhen",
            )
        )
        self._blockade = relation_now is not None and relation_now.value < 0

        # 史实事件必须逐月检查：一次推进 12 个月时，若只在结束时判定，
        # 整年的历史事件都会因为"过期"而被跳过。
        characters = {
            c.character_key: c
            for c in self.session.scalars(
                select(CharacterState).where(CharacterState.branch_id == branch.id)
            )
        }
        armies = {
            a.army_key: a
            for a in self.session.scalars(
                select(ArmyState).where(ArmyState.branch_id == branch.id)
            )
        }

        for step in range(months):
            self._tick(branch, regions, factions, step, profile, report, links)
            # 忠诚每月缓变：功高者渐生异志，朝廷威望不振则人心离散
            if characters:
                loyalty.monthly_drift(characters, armies, factions.get("tang"))
                defectors = loyalty.check_defection(
                    self.session, branch, characters, armies
                )
                for item in defectors:
                    report.defections.append(item)
                    self._emit(
                        branch, report,
                        kind="defection", scope="nation", severity=5,
                        title=f"{item['name']}叛归燕军",
                        summary=(
                            f"{item['name']}拥兵 {item['troops']:,}，"
                            f"忠诚已降至 {item['loyalty']:.2f}，遂叛。"
                            + (f" 失{item['regions'][0]}。" if item["regions"] else "")
                        ),
                        region_keys=[], faction_keys=["tang"],
                        causes=[{"rule": "defection", "character": item["character_key"]}],
                        metrics={"defection": item}, min_severity=0,
                    )

            # 到日子才成军的部队（回纥骑兵、九节度之师）在这里补上兵额
            for army in armies.values():
                if (
                    not army.raised
                    and army.raises_at is not None
                    and army.raises_at <= branch.current_date
                ):
                    army.raised = True
                    army.troops = army.troops_max
            branch.current_date = add_months(branch.current_date, 1)
            branch.tick_index += 1
            pending_snapshots.append(
                self._make_snapshot(branch, regions, factions)
            )
            if characters or armies:
                fired, diverged, forks = history.run_historical_events(
                    self.session,
                    branch,
                    regions=regions,
                    characters=characters,
                    armies=armies,
                    factions=factions,
                    emit_event=lambda **kw: self._emit(
                        branch, report, min_severity=0, **kw
                    ),
                )
                report.history_fired.extend(fired)
                report.history_diverged.extend(diverged)
                report.history_forks.extend(forks)
                # 岔路口一出现，时间就该停在这里等用户决定。
                # 否则后面的史实会在"前提尚未确定"的情况下被判定掉。
                if forks:
                    report.paused = True
                    report.months = step + 1
                    break

        report.to_date = branch.current_date
        report.region_states = [r.snapshot() for r in regions]
        report.faction_states = [
            {
                "faction_key": f.faction_key,
                "name": f.name,
                "treasury": round(f.treasury, 2),
                "legitimacy": round(f.legitimacy, 4),
                "military": round(f.military, 2),
            }
            for f in factions.values()
        ]

        # 变化摘要：只报"明显有变化"的项，避免每期都刷七个道
        for region in regions:
            g0, p0, u0 = before.get(region.region_key, (0.0, 1.0, 0.0))
            d_grain = region.grain_stock - g0
            d_price = region.price_index - p0
            d_unrest = region.unrest - u0
            grain_ratio = abs(d_grain) / max(g0, 1.0)
            if grain_ratio < 0.02 and abs(d_price) < 0.02 and abs(d_unrest) < 0.02:
                continue
            report.changes.append(
                {
                    "region_key": region.region_key,
                    "name": region.name,
                    "grain_delta": round(d_grain, 1),
                    "price_before": round(p0, 3),
                    "price_after": round(region.price_index, 3),
                    "price_delta": round(d_price, 3),
                    "unrest_before": round(u0, 3),
                    "unrest_after": round(region.unrest, 3),
                    "unrest_delta": round(d_unrest, 3),
                }
            )


        # 势力关系自然漂移：藩镇不会永远听话
        relations = {
            r.from_key: r
            for r in self.session.scalars(
                select(RelationState).where(RelationState.branch_id == branch.id)
            )
        }
        for rel in relations.values():
            if rel.kind == "allegiance":
                rel.value = max(rel.value - 0.004 * months, -1.0)

        raised = decisions.raise_decisions(
            self.session,
            branch,
            regions,
            factions,
            relations,
            shocked_keys=self._shocked_keys,
            rng=random.Random(f"{branch.seed}:{branch.tick_index}:decisions"),
            characters=characters,
            armies=armies,
        )
        report.decisions = [d.to_dict() for d in raised]
        report.relations = [r.snapshot() for r in relations.values()]

        with self.session.no_autoflush:
            if pending_events:
                self.session.execute(SimEvent.__table__.insert(), pending_events)
            if pending_snapshots:
                self.session.execute(Snapshot.__table__.insert(), pending_snapshots)
        self.session.flush()
        return report

    # ---------------------------------------------------------------- #
    def _tick(
        self,
        branch: Branch,
        regions: list[RegionState],
        factions: dict[str, FactionState],
        step: int,
        profile: tuple[int, bool, int],
        report: TickReport,
        links: list[TradeLink],
    ) -> None:
        min_severity, allow_local, shock_rolls = profile
        tick_index = branch.tick_index
        month = branch.current_date.month

        rng = random.Random(f"{branch.seed}:{tick_index}:{step}")
        revenue_by_faction: dict[str, float] = {}
        famines: list[tuple[RegionState, float]] = []
        #: 本 tick 各道的缺口与 famine 事件 id，供调运阶段使用
        shortage_by_key: dict[str, float] = {}
        consumption_by_key: dict[str, float] = {}
        famine_event_id: dict[str, int] = {}

        for region in regions:
            multiplier = 1.0
            shock_kind: str | None = None
            for _ in range(shock_rolls):
                if rng.random() < SHOCK_BASE_PROB:
                    shock = rng.choice(("drought", "flood", "locust"))
                    multiplier *= {"drought": 0.55, "flood": 0.7, "locust": 0.6}[shock]
                    shock_kind = shock
                    break

            result = rules.step_region(
                population=region.population,
                grain_stock=region.grain_stock,
                farmland=region.farmland,
                tax_rate=region.tax_rate,
                price_index=region.price_index,
                unrest=region.unrest,
                month=month,
                production_multiplier=multiplier,
            )

            # 事件只在「跨过阈值」时产生，持续状态不重复刷屏
            prev_stock = region.grain_stock
            prev_price = region.price_index
            prev_unrest = region.unrest

            region.grain_stock = result.stock_after
            region.price_index = result.price_after
            region.unrest = result.unrest_after

            shortage_by_key[region.region_key] = result.shortage
            consumption_by_key[region.region_key] = result.consumption

            if region.faction_key:
                revenue_by_faction[region.faction_key] = (
                    revenue_by_faction.get(region.faction_key, 0.0) + result.tax_revenue
                )

            if shock_kind:
                # 灾情不只减产，还会让地方人心浮动——这是后续"赈济"决策的引信
                region.unrest = min(region.unrest + 0.08, 1.0)
                self._shocked_keys.add(region.region_key)
                self._emit(
                    branch,
                    report,
                    kind="harvest_shock",
                    scope="region",
                    # 单月减产本身只算中等程度；只有真的引发缺粮才会升级为更严重的事件
                    severity=min(rules.severity_from_ratio(1.0 - multiplier), 3),
                    title=f"{region.name}遭遇{'旱灾' if shock_kind == 'drought' else '水灾' if shock_kind == 'flood' else '蝗灾'}",
                    summary=(
                        f"{region.name}本月农事产出下降约 {(1 - multiplier) * 100:.0f}%，"
                        f"粮食产量由常量基准下修。"
                    ),
                    region_keys=[region.region_key],
                    faction_keys=[region.faction_key] if region.faction_key else [],
                    causes=[{"rule": "harvest_shock", "shock": shock_kind}],
                    metrics={
                        "production_multiplier": round(multiplier, 3),
                        "production": round(result.production, 1),
                    },
                    min_severity=min_severity,
                )

            if result.shortage > 0:
                ratio = result.shortage / max(result.consumption, 1e-6)
                famines.append((region, ratio))
                severity = rules.severity_from_ratio(ratio)
                last = self._last_famine.get(region.region_key)
                # 只在「跨过阈值」时播报：断粮当月、严重度明显升级、
                # 或距上次播报已过半年。持续缺粮属于既有状态，不逐月刷屏。
                quiet = (
                    last is not None
                    and severity <= last[1]
                    and tick_index - last[0] < 6
                )
                if prev_stock > 0 and not quiet:
                    self._last_famine[region.region_key] = (tick_index, severity)
                    famine_causes: list[Any] = [
                        {"rule": "step_region", "reason": "grain_stock_below_consumption"}
                    ]
                    shock_id = self._recent_shock.get(region.region_key)
                    if shock_id is not None:
                        famine_causes.append(
                            {"event_id": shock_id, "rel": "caused_by_intervention"}
                        )
                    famine_id = self._emit(
                        branch,
                        report,
                        kind="famine",
                        scope="region",
                        severity=severity,
                        title=f"{region.name}出现粮荒",
                        summary=(
                            f"{region.name}本月缺粮 {result.shortage:.0f} 石，"
                            f"缺口约占月耗粮的 {ratio * 100:.0f}%，粮价指数升至 {result.price_after:.2f}。"
                        ),
                        region_keys=[region.region_key],
                        faction_keys=[region.faction_key] if region.faction_key else [],
                        causes=famine_causes,
                        metrics={
                            "shortage": round(result.shortage, 1),
                            "consumption": round(result.consumption, 1),
                            "price_index": round(result.price_after, 3),
                        },
                        min_severity=min_severity,
                    )
                    if famine_id is not None:
                        famine_event_id[region.region_key] = famine_id
                        self._active_famine_event[region.region_key] = famine_id
            elif prev_price < 2.0 <= result.price_after:
                self._emit(
                    branch,
                    report,
                    kind="price_spike",
                    scope="region",
                    severity=rules.severity_from_ratio(result.price_after / 5.0),
                    title=f"{region.name}粮价高企",
                    summary=f"{region.name}粮价指数达到 {result.price_after:.2f}，民生压力上升。",
                    region_keys=[region.region_key],
                    faction_keys=[region.faction_key] if region.faction_key else [],
                    causes=[{"rule": "target_price", "reason": "low_stock_months"}],
                    metrics={"price_index": round(result.price_after, 3)},
                    min_severity=min_severity,
                )

            if result.unrest_after >= 0.6 and prev_unrest < 0.6:
                self._emit(
                    branch,
                    report,
                    kind="unrest",
                    scope="region",
                    severity=rules.severity_from_ratio(result.unrest_after),
                    title=f"{region.name}民变风险升高",
                    summary=(
                        f"{region.name}民变指数升至 {result.unrest_after:.2f}，"
                        f"地方秩序出现松动。"
                    ),
                    region_keys=[region.region_key],
                    faction_keys=[region.faction_key] if region.faction_key else [],
                    causes=[{"rule": "step_region", "reason": "unrest_threshold"}],
                    metrics={"unrest": round(result.unrest_after, 3)},
                    min_severity=min_severity,
                )

        # ---- 跨区域调运：把上面算出的缺口沿真实通道补上 ----
        self._trade_phase(
            branch,
            regions,
            factions,
            links,
            report,
            shortage_by_key,
            consumption_by_key,
            famine_event_id,
            min_severity,
        )

        # ---- 势力财政 ----
        for key, faction in factions.items():
            treasury, legitimacy, military = rules.step_faction(
                treasury=faction.treasury,
                legitimacy=faction.legitimacy,
                military=faction.military,
                revenue=revenue_by_faction.get(key, 0.0),
            )
            deficit = treasury < 0 <= faction.treasury
            faction.treasury = treasury
            faction.legitimacy = legitimacy
            faction.military = military

            # 府库见底时，势力会自行在辖区加征——这会把压力转成民怨。
            # 没有这条，任何势力都会在几十年后欠出天文数字。
            own_regions = [r for r in regions if r.faction_key == key]
            if treasury < -200_000 and own_regions:
                squeezed = min(-treasury * 0.15, 400_000)
                faction.treasury += squeezed
                for region in own_regions:
                    region.tax_rate = min(region.tax_rate + 0.004, 0.3)
                    region.unrest = min(region.unrest + 0.012, 1.0)

            if deficit:
                self._emit(
                    branch,
                    report,
                    kind="fiscal_crisis",
                    scope="nation",
                    severity=4,
                    title=f"{faction.name}财政转负",
                    summary=f"{faction.name}本月府库透支，合法性开始受损。",
                    region_keys=[],
                    faction_keys=[key],
                    causes=[{"rule": "step_faction", "reason": "treasury_below_zero"}],
                    metrics={"treasury": round(treasury, 2)},
                    min_severity=min(min_severity, 4),
                )

        # ---- 跨区域：同一月多处粮荒上升为更高层级事件 ----
        if len(famines) >= 2:
            worst_key, worst_ratio = max(famines, key=lambda item: item[1])
            self._emit(
                branch,
                report,
                kind="regional_crisis",
                scope="world",
                severity=rules.severity_from_ratio(sum(r for _, r in famines)),
                title="多道同时缺粮",
                summary=(
                    f"本月共有 {len(famines)} 个地区出现粮荒，"
                    f"以{worst_key.name}最重（缺口比例 {worst_ratio * 100:.0f}%）。"
                ),
                region_keys=[r.region_key for r, _ in famines],
                faction_keys=[],
                causes=[{"rule": "aggregate_famine", "regions": len(famines)}],
                metrics={"famine_regions": len(famines)},
                min_severity=min(min_severity, 4),
            )

        # ---- 局部事件只在 deep 精度下产生 ----
        if allow_local:
            busiest = max(regions, key=lambda r: r.unrest, default=None)
            if busiest is not None and busiest.unrest >= 0.45:
                self._emit(
                    branch,
                    report,
                    kind="local_disturbance",
                    scope="local",
                    severity=2,
                    title=f"{busiest.name}出现聚众事件",
                    summary=f"{busiest.name}乡镇出现小规模聚众，地方官府弹压。",
                    region_keys=[busiest.region_key],
                    faction_keys=[busiest.faction_key] if busiest.faction_key else [],
                    causes=[{"rule": "local_detail", "reason": "deep_precision"}],
                    metrics={"unrest": round(busiest.unrest, 3)},
                    min_severity=1,
                )

    # ---------------------------------------------------------------- #
    def _emit(
        self,
        branch: Branch,
        report: TickReport,
        *,
        kind: str,
        scope: str,
        severity: int,
        title: str,
        summary: str,
        region_keys: Iterable[str],
        faction_keys: Iterable[str],
        causes: list[Any],
        metrics: dict[str, Any],
        min_severity: int,
    ) -> int | None:
        if severity < min_severity:
            return None
        region_list = list(region_keys)
        faction_list = list(faction_keys)
        event_id = self._next_event_id
        self._next_event_id += 1
        # 先攒成待插入的行（字典），由 advance() 用 Core 批量写入，
        # 避免逐条往返远程数据库
        self._pending_events.append(
            {
                "id": event_id,
                "branch_id": branch.id,
                "game_date": branch.current_date,
                "tick_index": branch.tick_index,
                "scope": scope,
                "kind": kind,
                "severity": severity,
                "duration_months": 1,
                "title": title,
                "summary": summary,
                "region_keys": region_list,
                "faction_keys": faction_list,
                "causes": causes,
                "metrics": metrics,
            }
        )
        report.events.append(
            {
                "id": event_id,
                "game_date": format_date(branch.current_date),
                "scope": scope,
                "kind": kind,
                "severity": severity,
                "title": title,
                "summary": summary,
                "region_keys": region_list,
                "faction_keys": faction_list,
                "causes": causes,
                "metrics": metrics,
            }
        )
        return event_id

    # ---------------------------------------------------------------- #
    def _trade_phase(
        self,
        branch: Branch,
        regions: list[RegionState],
        factions: dict[str, FactionState],
        links: list[TradeLink],
        report: TickReport,
        shortage_by_key: dict[str, float],
        consumption_by_key: dict[str, float],
        famine_event_id: dict[str, int],
        min_severity: int,
    ) -> None:
        """沿真实存在的转运通道，把余粮调到缺粮的道。

        这一步是「跨区域因果传导」的引擎实现：河北歉收 → 向河南买粮 →
        河南存粮下降、粮价上抬。链条靠事件 id 串起来，而不是靠 AI 事后叙述。
        """
        if not links:
            return

        by_key = {r.region_key: r for r in regions}
        blockaded = getattr(self, "_blockade", False)
        if blockaded:
            links = [
                link
                for link in links
                if "hebei" not in (link.from_key, link.to_key)
            ]
        incoming: dict[str, list[TradeLink]] = {}
        for link in links:
            incoming.setdefault(link.to_key, []).append(link)
        # 通道容量大的先走（相当于优先使用干道）
        for bucket in incoming.values():
            bucket.sort(key=lambda l: l.capacity, reverse=True)

        deficits = [
            (key, amount)
            for key, amount in shortage_by_key.items()
            if amount > 1.0 and key in by_key
        ]
        # 缺口大的先补给
        deficits.sort(key=lambda item: item[1], reverse=True)

        for key, need in deficits:
            importer = by_key[key]
            consumption = consumption_by_key.get(key, 0.0) or 1.0
            remaining = need
            covered = 0.0
            flows: list[dict[str, Any]] = []

            for link in incoming.get(key, []):
                if remaining <= 1.0:
                    break
                exporter = by_key.get(link.from_key)
                if exporter is None or exporter is importer:
                    continue
                exporter_consumption = consumption_by_key.get(link.from_key, 0.0) or 1.0
                surplus = rules.exportable_surplus(
                    exporter.grain_stock, exporter_consumption
                )
                if surplus <= 1.0:
                    continue

                amount = min(remaining, surplus, link.capacity)
                if amount <= 1.0:
                    continue
                delivered = rules.delivered_amount(amount, link.loss)

                exporter.grain_stock = max(exporter.grain_stock - amount, 0.0)
                importer.grain_stock += delivered
                remaining -= delivered
                covered += delivered

                # 价格：进口方回落，出口方上抬
                importer.price_index = rules.price_after_import(
                    importer.price_index, importer.grain_stock, consumption
                )
                exporter.price_index = rules.price_after_export(
                    exporter.price_index, exporter.grain_stock, exporter_consumption
                )

                # 货款在两方势力之间转移（跨势力调运要花钱）
                price = importer.price_index
                value = delivered * price
                self._settle_payment(factions, importer.faction_key, exporter.faction_key, value)

                cause_list: list[Any] = [
                    {"rule": "trade_transfer", "link": f"{link.from_key}->{link.to_key}"}
                ]
                famine_ref = famine_event_id.get(key) or self._active_famine_event.get(key)
                if famine_ref is not None:
                    cause_list.append({"event_id": famine_ref, "rel": "caused_by_famine"})

                flow_id = self._emit(
                    branch,
                    report,
                    kind="grain_flow",
                    scope="region",
                    severity=rules.severity_from_ratio(delivered / max(need, 1.0)),
                    title=f"{by_key[link.from_key].name}调粮至{importer.name}",
                    summary=(
                        f"{by_key[link.from_key].name}本月向{importer.name}调运粮食 "
                        f"{amount:.0f} 石，途耗后到位 {delivered:.0f} 石；"
                        f"{importer.name}粮价指数回到 {importer.price_index:.2f}。"
                    ),
                    region_keys=[link.from_key, key],
                    faction_keys=[
                        k
                        for k in (importer.faction_key, exporter.faction_key)
                        if k
                    ],
                    causes=cause_list,
                    metrics={
                        "amount": round(amount, 1),
                        "delivered": round(delivered, 1),
                        "loss": link.loss,
                        "importer_price": round(importer.price_index, 3),
                        "exporter_price": round(exporter.price_index, 3),
                    },
                    min_severity=min_severity,
                )
                flows.append({"from": link.from_key, "to": key, "delivered": delivered, "event_id": flow_id})

                # 出口方如果被拉到紧张区间，产生"粮价外溢"事件，挂在调运事件下面
                if exporter.price_index >= 1.6 and flow_id is not None:
                    self._emit(
                        branch,
                        report,
                        kind="price_pressure",
                        scope="region",
                        severity=rules.severity_from_ratio(exporter.price_index / 3.0),
                        title=f"{exporter.name}粮价被推高",
                        summary=(
                            f"因向{importer.name}调粮，{exporter.name}存粮降至"
                            f"{exporter.grain_stock:.0f} 石，粮价指数升至 {exporter.price_index:.2f}。"
                        ),
                        region_keys=[link.from_key],
                        faction_keys=[exporter.faction_key] if exporter.faction_key else [],
                        causes=[
                            {"event_id": flow_id, "rel": "caused_by_transfer"},
                        ],
                        metrics={
                            "price_index": round(exporter.price_index, 3),
                            "grain_stock": round(exporter.grain_stock, 1),
                        },
                        min_severity=1,
                    )

            if covered > 0:
                importer.unrest = max(importer.unrest - 0.05 * (covered / consumption), 0.0)

    # ---------------------------------------------------------------- #
    @staticmethod
    def _settle_payment(
        factions: dict[str, FactionState],
        buyer_key: str | None,
        seller_key: str | None,
        value: float,
    ) -> None:
        """跨势力调运要付钱：买方扣、卖方收；同势力内部调拨只记支出。"""
        if value <= 0:
            return
        buyer = factions.get(buyer_key) if buyer_key else None
        seller = factions.get(seller_key) if seller_key else None
        if buyer is not None:
            buyer.treasury -= value
        if seller is not None and seller is not buyer:
            seller.treasury += value

    # ---------------------------------------------------------------- #
    def _make_snapshot(
        self,
        branch: Branch,
        regions: list[RegionState],
        factions: dict[str, FactionState],
    ) -> dict:
        """构造当前 tick 的快照对象（不落库，由 advance 统一批量写入）。"""
        return {
            "branch_id": branch.id,
            "game_date": branch.current_date,
            "tick_index": branch.tick_index,
            "state": {
                "date": format_date(branch.current_date),
                "precision": branch.precision,
                "regions": [r.snapshot() for r in regions],
                "factions": [
                    {
                        "faction_key": f.faction_key,
                        "treasury": round(f.treasury, 2),
                        "legitimacy": round(f.legitimacy, 4),
                    }
                    for f in factions.values()
                ],
            },
        }