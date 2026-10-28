"""八年之后：两种打法各自的结局。

    python tools/demo_end_tang.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.app_factory import create_app, get_db  # noqa: E402
from app.engine import SimulationEngine  # noqa: E402
from app.engine.decisions import resolve_decision  # noqa: E402
from app.engine.end_tang import evaluate_tang_ending  # noqa: E402
from app.models import Decision, HistoricalFire  # noqa: E402
from app.services import create_branch, get_world_by_key  # noqa: E402

#: 两种打法：按史载 / 凡事另作他图
STRATEGY = {
    "history": None,
    "diverge": "diverge",
}


def play(mode: str) -> dict:
    app = create_app()
    with app.app_context():
        with get_db().session() as session:
            world = get_world_by_key(session, "tang_755")
            branch = create_branch(session, world, name=f"八年·{mode}", seed=5)
            engine = SimulationEngine(session)
            picks: list[str] = []

            for _ in range(40):
                report = engine.advance(branch, months=12)
                pending = list(
                    session.scalars(
                        select(Decision).where(
                            Decision.branch_id == branch.id,
                            Decision.kind == "history_fork",
                            Decision.status == "pending",
                        )
                    )
                )
                for decision in pending:
                    want_historical = STRATEGY[mode] is None
                    if want_historical:
                        option = next(
                            (o for o in decision.options if o.get("outcome") == "historical"),
                            decision.options[0],
                        )
                    else:
                        option = next(
                            (o for o in decision.options if o.get("outcome") != "historical"),
                            decision.options[0],
                        )
                    resolve_decision(session, branch, decision, option["key"])
                    session.flush()
                    picks.append(f"{decision.title} → {option['label']}")

                if branch.current_date.year >= 764:
                    break

            fired = sum(
                1
                for f in session.scalars(
                    select(HistoricalFire).where(HistoricalFire.branch_id == branch.id)
                )
                if f.status == "fired"
            )
            diverged = sum(
                1
                for f in session.scalars(
                    select(HistoricalFire).where(HistoricalFire.branch_id == branch.id)
                )
                if f.status == "diverged"
            )
            return {
                "picks": picks,
                "ending": evaluate_tang_ending(session, branch),
                "fired": fired,
                "diverged": diverged,
            }


def main() -> int:
    for mode, title in (("history", "A. 一路按史载"), ("diverge", "B. 每次另作他图")):
        result = play(mode)
        ending = result["ending"]
        print("=" * 74)
        print(f"{title}   （至 {ending['date']}）")
        print("=" * 74)
        for pick in result["picks"]:
            print(f"  ◆ {pick}")
        print(f"\n  史实应验 {result['fired']} 件，改道 {result['diverged']} 件")
        print(f"\n  结局：{ending['grade']}（{ending['score']} 分）")
        print(f"  {ending['verdict']}")
        print()
        for name, value in ending["scores"].items():
            bar = "█" * int(value / 5)
            print(f"    {name:<4}{value:>6.1f}  {bar}")
        m = ending["metrics"]
        print(
            f"\n    府库 {m['treasury']:,.0f} · 威望 {m['legitimacy']:.2f} · "
            f"两京在唐 {m['capitals_held']}/2 · 乱平 {'是' if m['rebellion_over'] else '否'}"
        )
        if m["rebel_regions"]:
            print(f"    仍为叛军所据：{'、'.join(m['rebel_regions'])}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())