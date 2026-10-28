"""演示：主帅不同，同一支军队的战力不同。

    python tools/demo_armies.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.app_factory import create_app, get_db  # noqa: E402
from app.engine.military import army_power, odds, side_strength  # noqa: E402
from app.models import ArmyState, CharacterState  # noqa: E402
from app.services import create_branch, get_world_by_key  # noqa: E402


def bar(value: float, width: int = 28) -> str:
    filled = int(min(value, 1.0) * width)
    return "█" * filled + "·" * (width - filled)


def main() -> int:
    app = create_app()
    with app.app_context():
        with get_db().session() as session:
            world = get_world_by_key(session, "tang_755")
            branch = create_branch(session, world, name="军力演示", seed=5)

            armies = list(
                session.scalars(
                    select(ArmyState).where(ArmyState.branch_id == branch.id)
                )
            )
            chars = {
                c.character_key: c
                for c in session.scalars(
                    select(CharacterState).where(CharacterState.branch_id == branch.id)
                )
            }

            print("=" * 78)
            print(f"{branch.current_date}  各军战力")
            print("=" * 78)
            print(f"  {'军队':<12}{'主帅':<8}{'兵力':>9}{'战力':>12}  士气  补给")
            for army in sorted(armies, key=lambda a: a.faction_key or ""):
                p = army_power(army, chars.get(army.commander_key or ""))
                print(
                    f"  {p.name:<12}{p.commander_name:<8}{p.troops:>9,}{p.power:>12,.0f}"
                    f"  {bar(p.morale, 10)} {p.supply:.2f}"
                )

            tang = side_strength(armies, chars, "tang")
            yan = side_strength(armies, chars, "yan")
            print()
            print(f"  唐军总战力 {tang:,.0f}   燕军总战力 {yan:,.0f}")
            print(f"  唐军胜算约 {odds(tang, yan) * 100:.0f}%")

            # 同一支军队换帅
            print()
            print("=" * 78)
            print("同一支朔方军，换帅之后")
            print("=" * 78)
            shuofang = next(a for a in armies if a.army_key == "shuofang_army")
            for key in ("guo_ziyi", "li_guangbi", "yang_guozhong", None):
                person = chars.get(key) if key else None
                p = army_power(shuofang, person)
                name = person.name if person else "（无主帅）"
                ability = f"{person.ability:.2f}" if person else "—"
                print(
                    f"  {name:<8} 才略 {ability:<5} → 战力 {p.power:>10,.0f}"
                    f"  {bar(p.power / 60000, 30)}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())