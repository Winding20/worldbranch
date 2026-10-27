"""按史载走完八年，列出每件史实的判定结果，排查哪一条没应验。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.app_factory import create_app, get_db  # noqa: E402
from app.engine import SimulationEngine  # noqa: E402
from app.engine.decisions import resolve_decision  # noqa: E402
from app.models import Decision, HistoricalFire  # noqa: E402
from app.seed import anlushan_755  # noqa: E402
from app.services import create_branch, get_world_by_key  # noqa: E402


def main() -> int:
    app = create_app()
    with app.app_context():
        with get_db().session() as session:
            world = get_world_by_key(session, "tang_755")
            branch = create_branch(session, world, name="排查", seed=5)
            engine = SimulationEngine(session)

            for _ in range(24):
                report = engine.advance(branch, months=12)
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
                if branch.current_date.year >= 764:
                    break

            fires = {
                f.event_key: f
                for f in session.scalars(
                    select(HistoricalFire).where(HistoricalFire.branch_id == branch.id)
                )
            }
            print(f"结束于 {branch.current_date}")
            for event in anlushan_755.HISTORICAL_EVENTS:
                f = fires.get(event["key"])
                status = f.status if f else "未判定"
                note = f.note if f else ""
                print(f"  {event['key']:<28} {event['date']}  {status:<10} {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())