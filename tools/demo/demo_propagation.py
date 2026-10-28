"""手动触发一次「河北歉收 -> 向邻道调粮」的链路，验证跨区域传导真的发生。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app import create_app  # noqa: E402
from app.app_factory import get_db  # noqa: E402
from app.engine import SimulationEngine  # noqa: E402
from app.models import RegionState, SimEvent  # noqa: E402
from app.services import create_branch, get_branch, get_world_by_key  # noqa: E402


def main() -> int:
    app = create_app()
    with app.app_context():
        with get_db().session() as session:
            world = get_world_by_key(session, "tang_750")
            branch = create_branch(session, world, name="传导验证", seed=11)
            bid = branch.id

            # 人为把河北的存粮打到接近零，模拟一次严重歉收
            hebei = session.scalar(
                select(RegionState).where(
                    RegionState.branch_id == bid, RegionState.region_key == "hebei"
                )
            )
            hebei.grain_stock = hebei.population * 0.42 * 0.15  # 只够几天
            print(f"河北存粮设为 {hebei.grain_stock:,.0f} 石（月耗 {hebei.population * 0.42:,.0f} 石）")

        with get_db().session() as session:
            b = get_branch(session, bid)
            report = SimulationEngine(session).advance(b, months=2)
            print(f"\n推进 2 个月，产生 {len(report.events)} 条事件：")
            for e in report.events:
                causes = ", ".join(
                    f"{c.get('rule') or 'event:' + str(c.get('event_id'))}" for c in e["causes"]
                )
                print(f"  [{e['game_date']}] {e['kind']:<15} {e['title']}  ← {causes}")

        with get_db().session() as session:
            flows = list(
                session.scalars(
                    select(SimEvent).where(
                        SimEvent.branch_id == bid, SimEvent.kind == "grain_flow"
                    )
                )
            )
            print(f"\n调运事件 {len(flows)} 条")
            for f in flows:
                print(
                    f"  {f.game_date} {f.summary}\n"
                    f"      区域={f.region_keys} 因果={f.causes}"
                )
        return 0 if flows else 1


if __name__ == "__main__":
    raise SystemExit(main())