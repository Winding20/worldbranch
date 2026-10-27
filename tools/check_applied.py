"""检查决议事件里记录的 applied 明细。"""

from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:5210"
with urllib.request.urlopen(f"{BASE}/api/worlds/tang_750/branches", timeout=20) as r:
    branches = json.loads(r.read().decode())
bid = branches[0]["id"]
with urllib.request.urlopen(f"{BASE}/api/branches/{bid}/events?limit=200", timeout=20) as r:
    events = json.loads(r.read().decode())

decisions = [e for e in events if e["kind"] == "decision"]
print(f"分支 {bid}：决议事件 {len(decisions)} 条")
for e in decisions[:3]:
    print(f"\n{e['game_date']} {e['title']}")
    for item in e["metrics"].get("applied", []):
        print(f"  {item['label']}: {item['before']} → {item['after']} {item['unit']}")