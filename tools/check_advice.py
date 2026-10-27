"""检查各分支待决事项是否带朝议。"""

from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:5210"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read().decode())


for branch in get("/api/worlds/tang_755/branches"):
    bid = branch["id"]
    decisions = get(f"/api/branches/{bid}/decisions")
    print(f"分支 {bid} {branch.get('name','')}: 待决 {len(decisions)}")
    for d in decisions:
        print(f"   {d['kind']:<16} {d['title'][:18]:<20} 朝议 {len(d.get('advice') or [])}")
        for a in (d.get("advice") or [])[:2]:
            print(f"      {a['name']} 主{a['option_label']} 才略 {a['ability']}")