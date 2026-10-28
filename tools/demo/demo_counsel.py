"""演示朝堂进谏：做决定前，先看看谁在说什么。

    python tools/demo_counsel.py
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
        raw = resp.read()
        return json.loads(raw.decode("utf-8")) if raw else None


def show(decision: dict) -> None:
    print("=" * 74)
    print(f"{decision['game_date']}  {decision['title']}")
    print("=" * 74)
    print(f"  {decision['description']}")
    print()
    if decision.get("advice"):
        print("  朝议：")
        for item in decision["advice"]:
            tag = f"〔{item['tag']}〕" if item.get("tag") else ""
            print(
                f"    · {item['name']}（{item['office']}，"
                f"才略 {item['ability']} 忠诚 {item['loyalty']}）"
            )
            print(f"      「{item['text']}」 → 主{item['option_label']} {tag}")
        print()
    else:
        print("  无人进言。")
        print()
    for option in decision["options"]:
        print(f"    [ ] {option['label']}：{option['detail']}")


def main() -> int:
    branch = call(
        "/api/worlds/tang_755/branches",
        "POST",
        {"seed": 5, "precision": "macro", "name": "朝议演示"},
    )
    bid = branch["id"]

    shown = 0
    for _ in range(24):
        call(f"/api/branches/{bid}/advance", "POST", {"months": 12})
        for decision in call(f"/api/branches/{bid}/decisions"):
            if shown >= 4:
                continue
            show(decision)
            shown += 1
            # 一律选「按史载」，便于与史实对照
            chosen = next(
                (o for o in decision["options"] if o.get("outcome") == "historical"),
                decision["options"][0],
            )
            call(
                f"/api/branches/{bid}/decisions/{decision['id']}/resolve",
                "POST",
                {"option": chosen["key"]},
            )
            print(f"\n  → 决断：{chosen['label']}\n")
        if shown >= 4:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())