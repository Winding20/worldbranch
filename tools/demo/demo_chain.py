"""端到端演示：用户干预 -> 粮荒 -> 跨道调运 -> 价格外溢，全程可追溯。

    python tools/demo_chain.py
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:5210"


def call(path: str, method: str = "GET", payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    branch = call(
        "/api/worlds/tang_750/branches",
        "POST",
        {"precision": "standard", "seed": 3, "name": "因果链演示"},
    )
    bid = branch["id"]
    print(f"分支 {bid} 建立于 {branch['current_date']}")

    # 用户在河北道制造一次严重歉收
    shock = call(
        f"/api/branches/{bid}/actions",
        "POST",
        {"kind": "shock", "region_key": "hebei", "params": {"damage_ratio": 0.85}},
    )
    print(f"\n[干预] {shock['title']}  (event id={shock['id']})")

    report = call(f"/api/branches/{bid}/advance", "POST", {"months": 2})
    print(f"\n推进 2 个月，产生 {report['event_count']} 条事件：")
    for e in report["events"]:
        causes = [
            c.get("rule") or f"事件{c.get('event_id')}" for c in e["causes"] if isinstance(c, dict)
        ]
        print(f"  [{e['game_date']}] {e['kind']:<15} {e['title']}  ← {', '.join(causes)}")

    # 找一条调运事件，回溯它的完整因果链
    events = call(f"/api/branches/{bid}/events?limit=100")
    flow = next((e for e in events if e["kind"] == "grain_flow"), None)
    if not flow:
        print("\n没有调运事件（本局未出现缺口）")
        return 1

    chain = call(f"/api/branches/{bid}/events/{flow['id']}/chain")
    print(f"\n从「{flow['title']}」回溯因果链（{len(chain['nodes'])} 个节点）：")
    for node in chain["nodes"]:
        print(f"  {node['game_date']}  {node['title']}")

    has_intervention = any(n["kind"] == "user_shock" for n in chain["nodes"])
    print(f"\n因果链是否追溯到用户干预：{'是' if has_intervention else '否'}")
    return 0 if has_intervention else 1


if __name__ == "__main__":
    raise SystemExit(main())