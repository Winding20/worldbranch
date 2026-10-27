"""聚焦排查：追安庆绪为何被判成"河南府已失"。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.app_factory import create_app, get_db  # noqa: E402
from app.engine import SimulationEngine  # noqa: E402
from app.engine.decisions import resolve_decision  # noqa: E402
from app.models import Decision, HistoricalFire, RegionState  # noqa: E402
from app.services import create_branch, get_world_by_key  # noqa: E402


def main() -> int:
    app = create_app()
    with app.app_context():
        with get_db().session() as session:
            world = get_world_by_key(session, "tang_755")
            branch = create_branch(session, world, name="聚焦排查", seed=5)
            engine = SimulationEngine(session)

            for _ in range(30):
                report = engine.advance(branch, months=1)
                luoyang = session.scalar(
                    select(RegionState).where(
                        RegionState.branch_id == branch.id,
                        RegionState.region_key == "luoyang",
                    )
                )
                fires = [
                    f.event_key
                    for f in session.scalars(
                        select(HistoricalFire).where(
                            HistoricalFire.branch_id == branch.id
                        )
                    )
                ]
                mark = ""
                if "luoyang_recovered" in fires:
                    mark = " ← 收复洛阳已判"
                print(
                    f"{branch.current_date}  河南府属{luoyang.faction_key}{mark}"
                )
                for item in report.history_forks:
                    decision = session.get(Decision, item["id"])
                    if decision is None or decision.status != "pending":
                        continue
                    option = next(
                        (o for o in decision.options if o.get("outcome") == "historical"),
                        decision.options[0],
                    )
                    resolve_decision(session, branch, decision, option["key"])
                    session.flush()
                if branch.current_date.year >= 759:
                    break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())