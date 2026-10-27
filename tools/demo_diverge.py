"""演示"历史改道"：把一个前提改掉，看哪几件史实因此不再发生。

对比两条时间线：
  A. 史实线：哥舒翰守潼关
  B. 改道线：哥舒翰不在（提前病故）

    python tools/demo_diverge.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select  # noqa: E402

from app.app_factory import create_app, get_db  # noqa: E402
from app.engine import SimulationEngine  # noqa: E402
from app.models import CharacterState  # noqa: E402
from app.services import create_branch, get_world_by_key  # noqa: E402


def run(kill_geshu: bool) -> dict:
    app = create_app()
    with app.app_context():
        with get_db().session() as session:
            world = get_world_by_key(session, "tang_755")
            branch = create_branch(
                session,
                world,
                name="改道线" if kill_geshu else "史实线",
                seed=5,
                precision="macro",
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

            report = SimulationEngine(session).advance(branch, months=18)
            regions = {}
            state = session.scalar(select(CharacterState).where(
                CharacterState.branch_id == branch.id
            ))
            del state
            from app.models import RegionState

            for r in session.scalars(
                select(RegionState).where(RegionState.branch_id == branch.id)
            ):
                regions[r.region_key] = r.faction_key
            return {
                "fired": [e["title"] for e in report.history_fired],
                "diverged": [
                    (e["title"], e["reason"], e["note"]) for e in report.history_diverged
                ],
                "regions": regions,
            }


def main() -> int:
    baseline = run(False)
    changed = run(True)

    print("=" * 72)
    print("A. 史实线（哥舒翰守潼关）")
    print("=" * 72)
    for title in baseline["fired"]:
        print(f"  ✓ {title}")
    for title, reason, _ in baseline["diverged"]:
        print(f"  ✗ {title} — {reason}")

    print()
    print("=" * 72)
    print("B. 改道线（哥舒翰提前病故）")
    print("=" * 72)
    for title in changed["fired"]:
        print(f"  ✓ {title}")
    for title, reason, note in changed["diverged"]:
        print(f"  ✗ {title} — {reason}")
        print(f"      {note}")

    only_in_baseline = [t for t in baseline["fired"] if t not in changed["fired"]]
    print()
    print("=" * 72)
    print(f"因为一个人不在，这 {len(only_in_baseline)} 件史实没有再发生：")
    for title in only_in_baseline:
        print(f"  · {title}")

    print()
    print("地区归属对比：")
    for key in baseline["regions"]:
        a, b = baseline["regions"][key], changed["regions"][key]
        flag = "  ← 不同" if a != b else ""
        print(f"  {key:<14} 史实线={a:<5} 改道线={b:<5}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())