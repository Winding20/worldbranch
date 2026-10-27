"""检查 tang_755 的 geo 结构是否符合前端预期。"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:5210"


def depth(value, level=0):
    if not isinstance(value, list):
        return level
    if not value:
        return level + 1
    return max(depth(item, level + 1) for item in value[:3])


with urllib.request.urlopen(f"{BASE}/api/worlds/tang_755", timeout=20) as r:
    world = json.loads(r.read().decode())

for region in world["regions"]:
    geo = region.get("geo") or {}
    print(
        f"{region['key']:<12} {geo.get('type', '-'):<14} "
        f"depth={depth(geo.get('coordinates'))} "
        f"sample={json.dumps(geo.get('coordinates'))[:70]}"
    )

# 期望：Polygon → [ring] depth=3（点→坐标→环→多边形）；MultiPolygon depth=4