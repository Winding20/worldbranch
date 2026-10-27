"""推进性能计时：对比「计算耗时」与「数据库往返耗时」。

    python tools/bench_advance.py [月数]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import create_app  # noqa: E402
from app.app_factory import get_db  # noqa: E402
from app.engine import SimulationEngine  # noqa: E402
from app.services import create_branch, get_world_by_key  # noqa: E402


def main() -> int:
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    app = create_app()
    with app.app_context():
        cfg = app.config["WORLDBRANCH"]
        backend = cfg.DATABASE_URL.split("://")[0]
        print(f"数据库后端：{backend}")
        print(f"推进月数：{months}")

        with get_db().session() as session:
            world = get_world_by_key(session, "tang_750")
            branch = create_branch(session, world, name="计时分支", seed=1)
            branch_id = branch.id

        t0 = time.perf_counter()
        with get_db().session() as session:
            from app.services import get_branch

            b = get_branch(session, branch_id)
            report = SimulationEngine(session).advance(b, months=months)
        elapsed = time.perf_counter() - t0

        print(f"事件数：{len(report.events)}")
        print(f"总耗时：{elapsed * 1000:.0f} ms")
        print(f"每月均摊：{elapsed * 1000 / months:.1f} ms")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())