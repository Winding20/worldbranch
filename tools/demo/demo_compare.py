"""分支对比演示：同一世界开出两条时间线，看差异。

    python tools/demo_compare.py
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
    a = call(
        "/api/worlds/tang_750/branches",
        "POST",
        {"precision": "standard", "seed": 3, "name": "甲：置之不理"},
    )
    aid = a["id"]
    print(f"分支 A #{aid}「{a['name']}」建立于 {a['current_date']}")

    # 在 A 上制造一次河北歉收，然后放任不管
    call(
        f"/api/branches/{aid}/actions",
        "POST",
        {"kind": "shock", "region_key": "hebei", "params": {"damage_ratio": 0.7}},
    )
    call(f"/api/branches/{aid}/advance", "POST", {"months": 1})

    # 从此刻派生 B，B 上立刻开仓赈济
    b = call(f"/api/branches/{aid}/fork", "POST", {"name": "乙：开仓赈济"})
    bid = b["id"]
    call(
        f"/api/branches/{bid}/actions",
        "POST",
        {"kind": "relief", "region_key": "hebei", "params": {"amount": 900_000}},
    )

    # 两条线各自再走 6 个月
    call(f"/api/branches/{aid}/advance", "POST", {"months": 6})
    call(f"/api/branches/{bid}/advance", "POST", {"months": 6})

    cmp = call(f"/api/branches/compare?left={aid}&right={bid}")
    print(
        f"\nA: {cmp['left']['current_date']} (tick {cmp['left']['tick_index']})"
        f"   B: {cmp['right']['current_date']} (tick {cmp['right']['tick_index']})"
    )
    div = cmp["divergence"]
    print(
        f"关系：B 从 A 派生 = {div['left_ancestor_of_right']}；"
        f"共同祖先 = {div['common_ancestor_name']}；"
        f"共有事件 {cmp['events']['common_count']} 条"
    )

    print(f"\n{'地区':<8}{'存粮(A)':>14}{'存粮(B)':>14}{'差异':>12}{'粮价A':>8}{'粮价B':>8}")
    for row in cmp["regions"]:
        print(
            f"{row['name']:<8}"
            f"{row['left']['grain_stock']:>14,.0f}"
            f"{row['right']['grain_stock']:>14,.0f}"
            f"{row['delta']['grain_stock']:>+12,.0f}"
            f"{row['left']['price_index']:>8.2f}"
            f"{row['right']['price_index']:>8.2f}"
        )

    print(f"\n只在 A 发生的事件：{len(cmp['events']['left_only'])} 条")
    for e in cmp["events"]["left_only"][:5]:
        print(f"  {e['game_date']} {e['title']}")
    print(f"只在 B 发生的事件：{len(cmp['events']['right_only'])} 条")
    for e in cmp["events"]["right_only"][:5]:
        print(f"  {e['game_date']} {e['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())