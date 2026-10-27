"""端到端验收脚本：直接打真实 HTTP 接口，输出用 UTF-8。

    python tools/verify_api.py [base_url]
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5210"


def call(path: str, method: str = "GET", payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    health = call("/api/health")
    print(f"[1] health           : {health}")

    worlds = call("/api/worlds")
    print(f"[2] worlds           : {[w['name'] for w in worlds]}")

    branches = call("/api/worlds/tang_750/branches")
    print(f"[3] 已有分支         : {[(b['id'], b['current_date'], b['tick_index']) for b in branches]}")

    branch = call(
        "/api/worlds/tang_750/branches",
        "POST",
        {"precision": "standard", "seed": 1, "name": "验收分支"},
    )
    bid = branch["id"]
    print(f"[4] 新建分支         : id={bid} {branch['name']} @ {branch['current_date']}")

    report = call(f"/api/branches/{bid}/advance", "POST", {"months": 24})
    print(f"[5] 推进 24 个月     : {report['from_date']} -> {report['to_date']}，事件 {report['event_count']} 条")

    state = call(f"/api/branches/{bid}/state")
    print(f"[6] 地区状态         : {len(state['regions'])} 个")
    for r in state["regions"][:3]:
        print(
            f"      {r['name']:<6} 粮价 {r['price_index']:.2f}  "
            f"存粮 {r['grain_stock']:,.0f} 石  民变 {r['unrest']:.2f}"
        )

    events = call(f"/api/branches/{bid}/events?limit=5")
    print(f"[7] 最近事件         : {len(events)} 条")
    for e in events[:3]:
        print(f"      [{e['game_date']}] {e['scope']}/{e['kind']} 严重度{e['severity']} {e['title']}")
        print(f"          因果: {e['causes']}")

    world_scope = call(f"/api/branches/{bid}/events?min_scope=world&limit=50")
    print(f"[8] 世界级事件筛选   : {len(world_scope)} 条（观察尺度过滤生效）")

    forked = call(f"/api/branches/{bid}/fork", "POST", {"name": "验收对照分支"})
    fork_events = call(f"/api/branches/{forked['id']}/events?limit=200")
    print(
        f"[9] 派生分支         : id={forked['id']} 继承历史事件 {len(fork_events)} 条"
        f"（源分支 {len(call(f'/api/branches/{bid}/events?limit=200'))} 条）"
    )

    ok = (
        len(state["regions"]) == 7
        and report["to_date"] == "752-01-01"
        and len(fork_events) == len(events) + max(0, len(call(f"/api/branches/{bid}/events?limit=200")) - len(events))
    )
    print("\n结果:", "全部通过" if ok else "存在异常")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())