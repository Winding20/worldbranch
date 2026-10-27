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

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Branch,
    FactionState,
    RegionState,
    SimEvent,
    Snapshot,
)
from ..utils import format_date
from . import rules

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

        for step in range(months):
            self._tick(branch, regions, factions, step, profile, report)
            branch.current_date = add_months(branch.current_date, 1)
            branch.tick_index += 1
            self._save_snapshot(branch, regions, factions)

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
    ) -> None:
        min_severity, allow_local, shock_rolls = profile
        tick_index = branch.tick_index
        month = branch.current_date.month

        rng = random.Random(f"{branch.seed}:{tick_index}:{step}")
        revenue_by_faction: dict[str, float] = {}
        famines: list[tuple[RegionState, float]] = []

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

            if region.faction_key:
                revenue_by_faction[region.faction_key] = (
                    revenue_by_faction.get(region.faction_key, 0.0) + result.tax_revenue
                )

            if shock_kind:
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
                if prev_stock > 0:
                    # 只在「首次断粮」时播报；持续缺粮属于既有危机状态，
                    # 由地区详情与民变事件体现，不逐月重复刷屏
                    self._emit(
                        branch,
                        report,
                        kind="famine",
                        scope="region",
                        severity=rules.severity_from_ratio(ratio),
                        title=f"{region.name}出现粮荒",
                        summary=(
                            f"{region.name}本月缺粮 {result.shortage:.0f} 石，"
                            f"缺口约占月耗粮的 {ratio * 100:.0f}%，粮价指数升至 {result.price_after:.2f}。"
                        ),
                        region_keys=[region.region_key],
                        faction_keys=[region.faction_key] if region.faction_key else [],
                        causes=[{"rule": "step_region", "reason": "grain_stock_below_consumption"}],
                        metrics={
                            "shortage": round(result.shortage, 1),
                            "consumption": round(result.consumption, 1),
                            "price_index": round(result.price_after, 3),
                        },
                        min_severity=min_severity,
                    )
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
    ) -> None:
        if severity < min_severity:
            return
        event = SimEvent(
            branch_id=branch.id,
            game_date=branch.current_date,
            tick_index=branch.tick_index,
            scope=scope,
            kind=kind,
            severity=severity,
            title=title,
            summary=summary,
            region_keys=list(region_keys),
            faction_keys=list(faction_keys),
            causes=causes,
            metrics=metrics,
        )
        self.session.add(event)
        report.events.append(
            {
                "game_date": format_date(event.game_date),
                "scope": scope,
                "kind": kind,
                "severity": severity,
                "title": title,
                "summary": summary,
                "region_keys": event.region_keys,
                "faction_keys": event.faction_keys,
                "causes": causes,
                "metrics": metrics,
            }
        )

    # ---------------------------------------------------------------- #
    def _save_snapshot(
        self,
        branch: Branch,
        regions: list[RegionState],
        factions: dict[str, FactionState],
    ) -> None:
        exists = self.session.scalar(
            select(Snapshot.id).where(
                Snapshot.branch_id == branch.id,
                Snapshot.tick_index == branch.tick_index,
            )
        )
        if exists:
            return
        self.session.add(
            Snapshot(
                branch_id=branch.id,
                game_date=branch.current_date,
                tick_index=branch.tick_index,
                state={
                    "date": branch.current_date.isoformat(),
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
            )
        )