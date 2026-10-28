"""演示"世界主动提问题"：推进几个月，看决策怎么冒出来、选项怎么改变世界。

    python tools/demo_decisions.py
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
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    world = call("/api/worlds/tang_750")
    sc = world["scenario"]
    print("=" * 66)
    print(f"你扮演：{sc['role']}")
    print(f"目标：{sc['goal']}")
    print("当前局面：")
    for p in sc["pressures"]:
        print(f"  · {p}")
    print("=" * 66)

    branch = call(
        "/api/worlds/tang_750/branches",
        "POST",
        {"precision": "standard", "seed": 3, "name": "决策演示"},
    )
    bid = branch["id"]

    rel = call(f"/api/branches/{bid}/relations")
    print(f"\n开局：河北藩镇臣属度 {rel[0]['value']:.2f}（{rel[0]['label']}）")

    pending = call(f"/api/branches/{bid}/decisions")
    print(f"开局待决事项：{len(pending)} 件")

    for round_no in range(1, 5):
        report = call(f"/api/branches/{bid}/advance", "POST", {"months": 6})
        print(f"\n—— 第 {round_no} 次推进：{report['from_date']} → {report['to_date']} ——")
        print(f"新事件 {report['event_count']} 条，涉及 {len(report['changes'])} 个道有变化")

        for d in report["decisions"]:
            print(f"\n【待决】{d['title']}")
            print(f"  {d['description']}")
            for opt in d["options"]:
                print(f"   · {opt['label']}：{opt['detail']}")

        if report["decisions"]:
            decision = report["decisions"][0]
            choice = decision["options"][0]
            result = call(
                f"/api/branches/{bid}/decisions/{decision['id']}/resolve",
                "POST",
                {"option": choice["key"]},
            )
            print(f"\n→ 选择「{choice['label']}」")
            print(f"  事件：{result['event']['title']}")

            rel = call(f"/api/branches/{bid}/relations")
            state = call(f"/api/branches/{bid}/state")
            tang = next(f for f in state["factions"] if f["faction_key"] == "tang")
            print(
                f"  结果：唐廷府库 {tang['treasury']:,.0f}，"
                f"河北臣属度 {rel[0]['value']:.2f}（{rel[0]['label']}）"
            )

    remaining = call(f"/api/branches/{bid}/decisions")
    history = call(f"/api/branches/{bid}/decisions?history=1")
    print(f"\n剩余待决：{len(remaining)} 件；历史决策 {len(history)} 件")
    for d in history:
        if d["status"] != "resolved":
            print(f"  · {d['game_date']} {d['title']}（仍待决）")
            continue
        chosen = next(
            (o for o in d["options"] if o["key"] == d["resolved_option"]), None
        )
        label = chosen["label"] if chosen else d["resolved_option"]
        print(f"  · {d['game_date']} {d['title']} → {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())