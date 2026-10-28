"""演示离心：功劳太大的人，忠心会掉。

    python tools/demo_loyalty.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.app_factory import create_app, get_db  # noqa: E402
from app.engine import SimulationEngine  # noqa: E402
from app.engine.decisions import resolve_decision  # noqa: E402
from app.engine.loyalty import loyalty_overview  # noqa: E402
from app.models import ArmyState, CharacterState, Decision  # noqa: E402
from app.services import create_branch, get_world_by_key  # noqa: E402


def bar(value: float, width: int = 20) -> str:
    filled = int(value * width)
    return "█" * filled + "·" * (width - filled)


def show(session, branch, title: str) -> None:
    armies = {
        a.army_key: a
        for a in session.scalars(select(ArmyState).where(ArmyState.branch_id == branch.id))
    }
    chars = {
        c.character_key: c
        for c in session.scalars(
            select(CharacterState).where(CharacterState.branch_id == branch.id)
        )
    }
    rows = [r for r in loyalty_overview(chars, armies) if r["alive"]]
    print(f"\n{title}  （{branch.current_date}）")
    print(f"  {'人物':<8}{'官职':<18}{'忠诚':<26}{'兵力':>9}  状态")
    for r in rows[:8]:
        print(
            f"  {r['name']:<8}{r['office'][:16]:<18}"
            f"{bar(r['loyalty'])} {r['loyalty']:.2f}  "
            f"{r['troops']:>8,}  {r['status']}"
        )


def main() -> int:
    app = create_app()
    with app.app_context():
        with get_db().session() as session:
            world = get_world_by_key(session, "tang_755")
            branch = create_branch(session, world, name="离心演示", seed=5)
            engine = SimulationEngine(session)
            show(session, branch, "开局")

            for year in range(4):
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
                for item in report.defections:
                    print(
                        f"\n  ✗ {item['name']}叛归燕军，带走 {item['troops']:,} 兵"
                        f"{'，失' + item['regions'][0] if item['regions'] else ''}"
                    )
                show(session, branch, f"第 {year + 1} 年")

            # 展示一个「拥兵自重」的抉择
            pending = session.scalars(
                select(Decision).where(
                    Decision.branch_id == branch.id,
                    Decision.kind == "reward_general",
                    Decision.status == "pending",
                )
            ).first()
            if pending is not None:
                print(f"\n{'=' * 70}")
                print(f"{pending.title}")
                print(f"  {pending.description}")
                for opt in pending.options:
                    print(f"    · {opt['label']}：{opt['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())