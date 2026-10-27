"""为安史之乱切片生成地理数据。

不能退回方块：这个项目承诺过地图是真实边界。
做法是拿唐朝七道的真实边界，按历史情形切成八块：

  关内道 → 京兆（南，京畿）+ 灵武（北，朔方）
  河北道 → 范阳（北）+ 河北诸州（南）
  河南道 → 河南府（西）+ 睢阳（东）
  河东道 → 太原（整道）
  潼关   → 关内道东缘的一个小区域（关隘）
  陇右道 → 不在本切片

    python tools/build_geo_755.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "backend" / "app" / "seed" / "data" / "tang_750_geo.json"
OUT = ROOT / "backend" / "app" / "seed" / "data" / "tang_755_geo.json"


def rings_of(item: dict) -> list[list[list[float]]]:
    """取出所有外环。Polygon 是 [ring]，MultiPolygon 是 [[ring], ...]。"""
    coords = item.get("coordinates") or []
    if item.get("type") == "Polygon":
        return [coords] if coords and isinstance(coords[0][0], (int, float)) else coords
    return [ring for poly in coords for ring in poly]


def clip_halfplane(
    ring: list[list[float]], axis: int, threshold: float, keep_greater: bool
) -> list[list[float]]:
    """用一条经线/纬线切多边形（Sutherland–Hodgman，裁剪区是半平面）。"""

    def inside(pt: list[float]) -> bool:
        return pt[axis] >= threshold if keep_greater else pt[axis] <= threshold

    out: list[list[float]] = []
    n = len(ring)
    for i in range(n):
        cur = ring[i]
        prev = ring[i - 1]
        cur_in, prev_in = inside(cur), inside(prev)
        if cur_in != prev_in:
            # 求与分界线的交点
            d_cur = cur[axis] - threshold
            d_prev = prev[axis] - threshold
            t = d_prev / (d_prev - d_cur) if (d_prev - d_cur) else 0.0
            cross = [
                prev[0] + (cur[0] - prev[0]) * t,
                prev[1] + (cur[1] - prev[1]) * t,
            ]
            cross[axis] = threshold
            out.append(cross)
        if cur_in:
            out.append(list(cur))
    return out


def split_rings(rings, axis, threshold):
    """把一组环按分界线切成 (大于, 小于) 两部分。"""
    hi, lo = [], []
    for ring in rings:
        a = clip_halfplane(ring, axis, threshold, True)
        b = clip_halfplane(ring, axis, threshold, False)
        if len(a) >= 3:
            hi.append(a)
        if len(b) >= 3:
            lo.append(b)
    return hi, lo


def as_item(rings, geom_type="Polygon"):
    """按前端的约定包装：Polygon 的 coordinates 是「环的列表」。

    注意这里跟严格 GeoJSON 差一层：前端 MapView 的 polygonsOf() 把
    Polygon 的 coordinates 直接当作「多边形」用（poly[0] 取名下的环），
    所以 Polygon 必须是 [ring]，MultiPolygon 则是 [[ring], ...]。
    """
    clean = [[p for p in ring] for ring in rings if len(ring) >= 4]
    if not clean:
        return None
    if geom_type == "MultiPolygon" or len(clean) > 1:
        return {"type": "MultiPolygon", "coordinates": [[r] for r in clean]}
    return {"type": "Polygon", "coordinates": [clean[0]]}


def main() -> int:
    src = json.loads(SRC.read_text(encoding="utf-8"))
    dao = src["dao"]

    out: dict[str, dict] = {}

    # 关内道：按 36.6°N 切南北 —— 北为朔方（灵武），南为京畿（京兆）
    guannei = rings_of(dao["guannei"])
    north, south = split_rings(guannei, 1, 36.6)
    out["lingwu"] = as_item(north)
    out["changan"] = as_item(south)

    # 河北道：按 38.6°N 切 —— 北为范阳，南为河北诸州
    hebei = rings_of(dao["hebei"])
    north, south = split_rings(hebei, 1, 38.6)
    out["fanyang"] = as_item(north)
    out["hebei_plain"] = as_item(south)

    # 河南道：按 114.6°E 切 —— 西为河南府，东为睢阳
    henan = rings_of(dao["henan"])
    east, west = split_rings(henan, 0, 114.6)
    out["suiyang"] = as_item(east)
    out["luoyang"] = as_item(west)

    # 河东道：整道作太原
    out["taiyuan"] = as_item(rings_of(dao["hedong"]))

    # 潼关：关内道东缘的一块小区域（在 110.1–110.6°E、34.4–34.8°N）
    out["tongguan"] = {
        "type": "Polygon",
        "coordinates": [
            [
                [110.10, 34.40],
                [110.62, 34.40],
                [110.62, 34.82],
                [110.10, 34.82],
                [110.10, 34.40],
            ]
        ],
    }

    missing = [k for k, v in out.items() if v is None]
    if missing:
        raise SystemExit(f"这些地区没切出形状：{missing}")

    OUT.write_text(
        json.dumps({"dao": out}, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    total = 0
    for key, item in out.items():
        rings = rings_of(item)
        pts = sum(len(r) for r in rings)
        total += pts
        print(f"  {key:<12} {item['type']:<12} {len(rings)} 环 {pts} 点")
    print(f"写入 {OUT}，合计 {total} 点")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())