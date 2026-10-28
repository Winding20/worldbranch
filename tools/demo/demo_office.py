"""演示官职迁转：夺兵权之后，官位到底变成了什么。

    python tools/demo_office.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.app_factory import create_app, get_db  # noqa: E402
from app.engine import SimulationEngine  # noqa: E402
from app.engine.decisions import pending_decisions, resolve_decision  # noqa: E402
from app.engine.loyalty import DEFECT_LOYALTY, WARNING_LOYALTY, loyalty_overview  # noqa: E402
from app.engine.offices import can_command, kind_label, rank_label  # noqa: E402
from app.models import ArmyState, CharacterState  # noqa: E402
from app.services import create_branch, get_world_by_key  # noqa: E402


def show(session, branch, title: str) -> None:
    armies = {
        a.army_key: a
        for a in session.scalars(
            select(ArmyState).where(ArmyState.branch_id == branch.id)
        )
    }
    chars = {
        c.character_key: c
        for c in session.scalars(
            select(CharacterState).where(CharacterState.branch_id == branch.id)
        )
    }
    print(f"\n{title}")
    print(f"  {'人物':<8}{'官职':<22}{'品级':<6}{'性质':<6}{'统兵':<6}忠诚")
    for row in loyalty_overview(chars, armies)[:6]:
        person = chars[row["key"]]
        print(
            f"  {row['name']:<8}{person.office[:20]:<22}"
            f"{rank_label(person.office_rank):<6}"
            f"{kind_label(person.office_kind):<6}"
            f"{'可' if can_command(person) else '否':<6}{row['loyalty']:.2f}"
        )


def main() -> int:
    app = create_app()
    with app.app_context():
        with get_db().session() as session:
            world = get_world_by_key(session, "tang_755")
            branch = create_branch(session, world, name="官职演示", seed=5)
            show(session, branch, "开局")

            guo = session.scalar(
                select(CharacterState).where(
                    CharacterState.branch_id == branch.id,
                    CharacterState.character_key == "guo_ziyi",
                )
            )
            guo.loyalty = (DEFECT_LOYALTY + WARNING_LOYALTY) / 2
            session.flush()

            SimulationEngine(session).advance(branch, months=1)
            decision = next(
                d
                for d in pending_decisions(session, branch.id)
                if d.kind == "reward_general"
            )
            print(f"\n【待决】{decision.title}")
            print(f"  {decision.description}")
            for opt in decision.options:
                print(f"    · {opt['label']}：{opt['detail']}")

            event = resolve_decision(session, branch, decision, "strip_command")
            print("\n→ 选择「削其兵权」")
            for item in event.metrics["applied"]:
                print(f"    {item['label']}：{item['before']} → {item['after']}")

            show(session, branch, "削权之后")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())