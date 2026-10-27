"""演示 AI 分析层：看看真正会送给模型的是什么材料。

    python tools/demo_ai.py
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:5210"


def call(path: str, method: str = "GET", payload: dict | None = None, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})} if data else (headers or {}),
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    world_key = sys.argv[1] if len(sys.argv) > 1 else "tang_755"
    branch = call(
        f"/api/worlds/{world_key}/branches",
        "POST",
        {"precision": "standard", "seed": 3, "name": "AI 演示"},
    )
    bid = branch["id"]

    call(f"/api/branches/{bid}/advance", "POST", {"months": 8})

    events = call(f"/api/branches/{bid}/events?limit=50")
    focus = next((e for e in events if e["kind"] == "grain_flow"), None)

    print("=" * 70)
    print("会送给模型的材料（节选）")
    print("=" * 70)
    material = call(
        f"/api/ai/branches/{bid}/material"
        + (f"?event_id={focus['id']}" if focus else "")
    )
    text = material["text"]
    print(text[:1800])
    print("..." if len(text) > 1800 else "")
    print(f"\n材料总长度：{len(text)} 字")
    print(f"引用资料：{[c['title'] for c in material['citations']]}")

    # 配置一个离线 provider 并跑一次分析（不需要真实 Key）
    call(
        "/api/ai/providers",
        "POST",
        {"name": "离线演示", "kind": "mock", "base_url": "", "model": "mock", "is_default": True},
    )
    result = call(
        f"/api/ai/branches/{bid}/analyze",
        "POST",
        {
            "question": "河北的粮荒是如何影响到其他道的？",
            "event_id": focus["id"] if focus else None,
        },
        headers={"X-LLM-Key": "sk-demo-should-not-leak"},
    )
    print("\n" + "=" * 70)
    print("分析结果（离线适配器）")
    print("=" * 70)
    print(result["answer"])
    print(f"\n用到的事实：{result['context']}")
    leaked = "sk-demo-should-not-leak" in json.dumps(result, ensure_ascii=False)
    print(f"响应中是否泄露 Key：{'是（有问题！）' if leaked else '否'}")
    return 0 if not leaked else 1


if __name__ == "__main__":
    raise SystemExit(main())