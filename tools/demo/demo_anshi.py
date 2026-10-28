"""安史之乱八年推演演示。

跑一遍 755–763，看史实事件是否按史发生、在哪里改道。

    python tools/demo_anshi.py [--diverge]

--diverge 会在起兵后立刻让安禄山死掉，用来验证"历史改道"。
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:5210"
DIVERGE = "--diverge" in sys.argv


def call(path: str, method: str = "GET", payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
        return json.loads(raw.decode("utf-8")) if raw else None


def main() -> int:
    world = call("/api/worlds/tang_755")
    sc = world["scenario"]
    print("=" * 70)
    print(f"世界：{world['name']} · {world['era']}")
    print(f"角色：{sc['role']}")
    print(f"目标：{sc['goal']}")
    print("=" * 70)

    branch = call(
        "/api/worlds/tang_755/branches",
        "POST",
        {"seed": 5, "precision": "macro", "name": "史实线"},
    )
    bid = branch["id"]
    print(f"\n开局：{world['start_date']}，{len(world['regions'])} 个地区，分支 {bid}")

    last_date = None
    for _ in range(24):
        report = call(f"/api/branches/{bid}/advance", "POST", {"months": 12})
        last_date = report["to_date"]
        for item in report.get("history_fired", []):
            print(f"\n  【史实】{item['date']}  {item['title']}")
            for eff in item.get("applied", []):
                print(f"      {eff['label']}: {eff['before']} → {eff['after']}")
            print(f"      （{item['source']}）")
        for item in report.get("history_diverged", []):
            print(f"\n  【改道】{item['expected_date']} 原应发生「{item['title']}」")
            print(f"      原因：{item['reason']}")
            print(f"      {item['note']}")
        # 岔路口：史实线一律选「按史载」
        for decision in call(f"/api/branches/{bid}/decisions"):
            if decision["kind"] != "history_fork":
                continue
            chosen = next(
                (o for o in decision["options"] if o.get("outcome") == "historical"),
                decision["options"][0],
            )
            result = call(
                f"/api/branches/{bid}/decisions/{decision['id']}/resolve",
                "POST",
                {"option": chosen["key"]},
            )
            print(f"\n  【抉择】{decision['title']} → {chosen['label']}")
            print(f"      {result['event']['title']}")
            for eff in result["event"]["metrics"].get("applied", []):
                print(f"      {eff['label']}: {eff['before']} → {eff['after']}")

        if last_date and last_date[:4] >= "763":
            break

    status = call(f"/api/branches/{bid}/history")
    state = call(f"/api/branches/{bid}/state")

    print("\n" + "=" * 70)
    print(f"结束于 {last_date}")
    print(f"史实应验 {len(status['fired'])} 件，改道 {len(status['diverged'])} 件")
    tang = next(f for f in state["factions"] if f["faction_key"] == "tang")
    yan = next((f for f in state["factions"] if f["faction_key"] == "yan"), None)
    print(f"唐廷府库 {tang['treasury']:,.0f}，威望 {tang['legitimacy']:.2f}")
    if yan:
        print(f"燕军府库 {yan['treasury']:,.0f}")

    lost = [r["name"] for r in state["regions"] if r["faction_key"] != "tang"]
    held = [r["name"] for r in state["regions"] if r["faction_key"] == "tang"]
    print(f"唐军仍守：{'、'.join(held)}")
    print(f"已失之地：{'、'.join(lost) if lost else '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())