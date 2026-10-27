"""排查史实触发记录。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.app_factory import create_app, get_db  # noqa: E402
from app.models import Branch, Decision, HistoricalFire  # noqa: E402


def main() -> int:
    app = create_app()
    with app.app_context():
        with get_db().session() as session:
            branches = list(session.scalars(select(Branch).order_by(Branch.id.desc()).limit(1)))
            if not branches:
                print("没有分支")
                return 1
            branch = branches[0]
            print(f"分支 {branch.id} {branch.name} 日期 {branch.current_date}")

            fires = list(
                session.scalars(
                    select(HistoricalFire)
                    .where(HistoricalFire.branch_id == branch.id)
                    .order_by(HistoricalFire.id)
                )
            )
            print(f"\n史实记录 {len(fires)} 条：")
            counts: dict[str, int] = {}
            for f in fires:
                counts[f.event_key] = counts.get(f.event_key, 0) + 1
            for f in fires:
                print(f"  {f.event_key:<28} {f.status:<10} {f.game_date} {f.note}")
            dup = {k: v for k, v in counts.items() if v > 1}
            if dup:
                print(f"\n重复记录：{dup}")

            decisions = list(
                session.scalars(
                    select(Decision).where(Decision.branch_id == branch.id).order_by(Decision.id)
                )
            )
            print(f"\n决策 {len(decisions)} 条：")
            for d in decisions:
                print(f"  #{d.id} {d.kind:<14} {d.ref_key or '-':<20} {d.status} {d.resolved_option or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())