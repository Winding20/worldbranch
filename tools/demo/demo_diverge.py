"""演示历史改道：同样的结果，不同的原因。

三个场景对比：
  A. 史实线     —— 朝廷催战，潼关失守
  B. 抗命坚守   —— 朝廷令哥舒翰坚守，潼关不失
  C. 换个人守   —— 哥舒翰提前病故，无人可催，潼关同样不失

B 与 C 结局相同，但原因完全不同——这正是"因果经得起推敲"要看的东西。

    python tools/demo_diverge.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.app_factory import create_app, get_db  # noqa: E402
from app.engine import SimulationEngine  # noqa: E402
from app.engine.decisions import resolve_decision  # noqa: E402
from app.models import CharacterState, Decision, RegionState  # noqa: E402
from app.services import create_branch, get_world_by_key  # noqa: E402

SCENARIOS = {
    "history": ("A. 史实线（朝廷催战）", "order_attack", False),
    "hold": ("B. 朝廷令其坚守", "hold_position", False),
    "dead": ("C. 哥舒翰提前病故", None, True),
}


def run(mode: str) -> dict:
    _, fork_choice, kill_geshu = SCENARIOS[mode]
    app = create_app()
    with app.app_context():
        with get_db().session() as session:
            world = get_world_by_key(session, "tang_755")
            branch = create_branch(
                session, world, name=f"场景 {mode}", seed=5, precision="macro"
            )
            if kill_geshu:
                person = session.scalar(
                    select(CharacterState).where(
                        CharacterState.branch_id == branch.id,
                        CharacterState.character_key == "geshu_han",
                    )
                )
                person.alive = False
                session.flush()

            engine = SimulationEngine(session)
            fired: list[str] = []
            diverged: list[tuple[str, str]] = []
            forks: list[str] = []

            for _ in range(8):
                report = engine.advance(branch, months=12)
                fired.extend(e["title"] for e in report.history_fired)
                diverged.extend(
                    (e["title"], e["reason"]) for e in report.history_diverged
                )
                for item in report.history_forks:
                    decision = session.get(Decision, item["id"])
                    if decision is None or decision.status != "pending":
                        continue
                    option = next(
                        (o for o in decision.options if o["key"] == fork_choice),
                        decision.options[0],
                    )
                    resolve_decision(session, branch, decision, option["key"])
                    session.flush()
                    forks.append(f"{decision.title} → {option['label']}")
                if branch.current_date.year >= 763:
                    break

            regions = {
                r.region_key: r.faction_key
                for r in session.scalars(
                    select(RegionState).where(RegionState.branch_id == branch.id)
                )
            }
            return {
                "fired": fired,
                "diverged": diverged,
                "forks": forks,
                "regions": regions,
                "date": str(branch.current_date),
            }


def main() -> int:
    results = {mode: run(mode) for mode in SCENARIOS}

    for mode, (title, _, _) in SCENARIOS.items():
        r = results[mode]
        print("=" * 74)
        print(f"{title}   （至 {r['date']}）")
        print("=" * 74)
        for f in r["forks"]:
            print(f"  ◆ 抉择：{f}")
        for t in r["fired"]:
            print(f"  ✓ {t}")
        for t, reason in r["diverged"]:
            print(f"  ✗ {t} —— {reason}")
        print()

    print("=" * 74)
    print("地区归属")
    print("=" * 74)
    print(f"  {'地区':<14}{'A 催战':<10}{'B 坚守':<10}{'C 病故':<10}")
    for key in results["history"]["regions"]:
        a = results["history"]["regions"][key]
        b = results["hold"]["regions"][key]
        c = results["dead"]["regions"][key]
        mark = "  ←" if len({a, b, c}) > 1 else ""
        print(f"  {key:<14}{a:<10}{b:<10}{c:<10}{mark}")

    print()
    print("潼关的三种结局：")
    causes = {
        "history": "朝廷催战，出关遇伏",
        "hold": "朝廷令其坚守，不出战",
        "dead": "哥舒翰已故，无人可催",
    }
    for mode, (title, _, _) in SCENARIOS.items():
        owner = results[mode]["regions"]["tongguan"]
        print(f"  {title:<22} 潼关属{'唐' if owner == 'tang' else '燕'}  （{causes[mode]}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())