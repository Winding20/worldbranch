"""五年通关演示：自动替用户做选择，跑完 60 个月看结局。

    python tools/demo_ending.py [策略]

策略：austerity（省钱） / appease（安抚） / ignore（不作为），默认 appease
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:5210"
STRATEGY = sys.argv[1] if len(sys.argv) > 1 else "appease"

#: 不同策略下，每类决策优先选哪个选项
PREFERENCE = {
    "austerity": {
        "warlord_supply": ["refuse", "grant_half", "grant_full"],
        "famine_relief": ["tax_relief", "ignore", "open_granary"],
        "cut_warlord": ["wait", "appease", "cut"],
        "warlord_revolt": ["conciliate", "suppress", "hold"],
        "border_raid": ["ignore", "bribe", "reinforce"],
        "transport_break": ["suspend", "requisition", "land_route"],
    },
    "appease": {
        "warlord_supply": ["grant_full", "grant_half", "refuse"],
        "famine_relief": ["open_granary", "tax_relief", "ignore"],
        "cut_warlord": ["appease", "wait", "cut"],
        "warlord_revolt": ["conciliate", "suppress", "hold"],
        "border_raid": ["bribe", "reinforce", "ignore"],
        "transport_break": ["land_route", "suspend", "requisition"],
    },
    "ignore": {
        "warlord_supply": ["refuse", "grant_half", "grant_full"],
        "famine_relief": ["ignore", "tax_relief", "open_granary"],
        "cut_warlord": ["wait", "cut", "appease"],
        "warlord_revolt": ["hold", "conciliate", "suppress"],
        "border_raid": ["ignore", "bribe", "reinforce"],
        "transport_break": ["suspend", "requisition", "land_route"],
    },
}


def call(path: str, method: str = "GET", payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
        return json.loads(raw.decode("utf-8")) if raw else None


def choose(decision) -> dict:
    prefs = PREFERENCE[STRATEGY].get(decision["kind"], [])
    for key in prefs:
        found = next((o for o in decision["options"] if o["key"] == key), None)
        if found:
            return found
    return decision["options"][0]


def main() -> int:
    world = call("/api/worlds/tang_750")
    sc = world["scenario"]
    print("=" * 68)
    print(f"角色：{sc['role']}")
    print(f"目标：{sc['goal']}")
    print(f"策略：{STRATEGY}")
    print("=" * 68)

    branch = call(
        "/api/worlds/tang_750/branches",
        "POST",
        {"precision": "macro", "seed": 3, "name": f"五年·{STRATEGY}"},
    )
    bid = branch["id"]

    seen = 0
    for month in range(0, 60, 6):
        report = call(f"/api/branches/{bid}/advance", "POST", {"months": 6})
        decisions = call(f"/api/branches/{bid}/decisions")
        for decision in decisions:
            option = choose(decision)
            result = call(
                f"/api/branches/{bid}/decisions/{decision['id']}/resolve",
                "POST",
                {"option": option["key"]},
            )
            seen += 1
            print(
                f"  [{result['event']['game_date']}] {decision['title']}"
                f" → {option['label']}"
            )

    state = call(f"/api/branches/{bid}/state")
    tang = next(f for f in state["factions"] if f["faction_key"] == "tang")
    rel = call(f"/api/branches/{bid}/relations")
    ending = call(f"/api/branches/{bid}/ending")

    print(f"\n共做出 {seen} 次决策")
    print(f"唐廷府库：{tang['treasury']:,.0f} 贯；藩镇臣属度：{rel[0]['value']:.2f}（{rel[0]['label']}）")

    if not ending:
        print("尚未到达五年，无结局")
        return 1

    print("\n" + "=" * 68)
    print(f"结局：{ending['grade']}（{ending['score']} 分）")
    print(f"评语：{ending['verdict']}")
    print("-" * 68)
    for name, value in ending["scores"].items():
        bar = "█" * int(value / 5)
        print(f"  {name:<4} {value:>5.1f}  {bar}")
    print("-" * 68)
    m = ending["metrics"]
    print(
        f"  府库 {m['treasury']:,.0f} · 威望 {m['legitimacy']:.2f} · "
        f"臣属 {m['allegiance']:.2f} · 均价 {m['avg_price']:.2f} · "
        f"民变峰值 {m['max_unrest']:.2f}"
    )
    print(f"  决策 {m['decisions_made']} 次 · 事件 {m['events']} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())