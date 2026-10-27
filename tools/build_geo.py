"""生成唐朝七道的近似地理轮廓。

做法
----
用现代省级行政区边界**近似**唐代「道」的辖境：每个道由若干省/直辖市组成，
渲染时同一道的多个多边形用相同填充色叠画，视觉上就是一个整体。

为什么不用 shapely 做真正的合并
------------------------------
合并需要 shapely（二进制轮子，本机镜像安装不稳定）。用「同一填充色 + 两遍绘制」
的技巧可以完全不依赖第三方库得到同样的视觉效果：
先给每个多边形描边，再用填充色盖住内部接缝，只有外轮廓的描边会留下。

这是**近似**数据，不是历史行政区划复原，必须如实标注。

用法::

    python tools/build_geo.py            # 下载并生成
    python tools/build_geo.py --offline  # 只用已有缓存

输出：backend/app/seed/data/tang_750_geo.json
"""

from __future__ import annotations

import json
import math
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "backend" / "app" / "seed" / "data"
CACHE = DATA_DIR / "china_provinces.json"
OUT = DATA_DIR / "tang_750_geo.json"

SOURCE_URL = "https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json"

#: 道 -> 组成它的现代省/直辖市/自治区（用 DataV 里的 name 字段匹配）
TANG_DAO: dict[str, dict] = {
    "guannei": {
        "name": "关内道",
        "provinces": ["陕西省", "宁夏回族自治区"],
        "seat": (108.94, 34.34),  # 长安
    },
    "longyou": {
        "name": "陇右道",
        "provinces": ["甘肃省", "青海省", "新疆维吾尔自治区"],
        "seat": (101.78, 36.62),  # 鄯州
    },
    "hedong": {
        "name": "河东道",
        "provinces": ["山西省"],
        "seat": (112.55, 37.87),  # 太原府
    },
    "hebei": {
        "name": "河北道",
        "provinces": ["河北省", "北京市", "天津市", "辽宁省"],
        "seat": (116.40, 39.90),  # 幽州
    },
    "henan": {
        "name": "河南道",
        "provinces": ["河南省", "山东省"],
        "seat": (112.45, 34.62),  # 洛阳
    },
    "huainan": {
        "name": "淮南道",
        "provinces": ["江苏省", "安徽省"],
        "seat": (119.42, 32.39),  # 扬州
    },
    "jiangnan": {
        "name": "江南道",
        "provinces": ["浙江省", "江西省", "湖南省", "福建省", "上海市"],
        "seat": (120.58, 30.03),  # 越州
    },
}

#: 简化容差（度）。约 0.03° ≈ 3 公里，在国家级视图里完全看不出差别。
SIMPLIFY_EPS = 0.03
#: 合并相邻点、去噪的最小间隔（度）
MIN_SEGMENT = 0.01


def download() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    CACHE.write_bytes(raw)
    return json.loads(raw.decode("utf-8"))


def load(offline: bool) -> dict:
    if offline or (CACHE.exists() and "--refresh" not in sys.argv):
        if CACHE.exists():
            return json.loads(CACHE.read_text(encoding="utf-8"))
    return download()


# --------------------------------------------------------------------------- #
# 简化算法（Douglas-Peucker），避免依赖 shapely
# --------------------------------------------------------------------------- #
def _perpendicular_distance(point, start, end) -> float:
    (px, py), (sx, sy), (ex, ey) = point, start, end
    dx, dy = ex - sx, ey - sy
    if dx == 0 and dy == 0:
        return math.hypot(px - sx, py - sy)
    t = ((px - sx) * dx + (py - sy) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (sx + t * dx), py - (sy + t * dy))


def simplify_ring(points: list[list[float]], eps: float = SIMPLIFY_EPS) -> list[list[float]]:
    """对闭合环做 Douglas-Peucker 简化。"""
    if len(points) <= 4:
        return points

    first, last = points[0], points[-1]
    closed = first == last
    body = points[:-1] if closed else points
    if len(body) <= 3:
        return points

    def rdp(seq: list[list[float]]) -> list[list[float]]:
        if len(seq) < 3:
            return seq
        start, end = seq[0], seq[-1]
        index, best = 0, 0.0
        for i in range(1, len(seq) - 1):
            d = _perpendicular_distance(seq[i], start, end)
            if d > best:
                index, best = i, d
        if best <= eps:
            return [start, end]
        left = rdp(seq[: index + 1])
        right = rdp(seq[index:])
        return left[:-1] + right

    reduced = rdp(body + [body[0]])
    if reduced[-1] != reduced[0]:
        reduced.append(reduced[0])
    if len(reduced) < 4:
        return points
    return reduced


def clean_ring(points: list[list[float]]) -> list[list[float]]:
    """去零长线段 + 坐标保留 3 位小数。"""
    out: list[list[float]] = []
    for lon, lat in points:
        lon, lat = round(lon, 3), round(lat, 3)
        if out:
            plon, plat = out[-1]
            if abs(lon - plon) < MIN_SEGMENT and abs(lat - plat) < MIN_SEGMENT:
                continue
        out.append([lon, lat])
    if out and out[0] != out[-1]:
        out.append(out[0])
    return out


def ring_area(points: list[list[float]]) -> float:
    area = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        area += x1 * y2 - x2 * y1
    return abs(area) / 2


def extract_polygons(feature: dict) -> list[list[list[list[float]]]]:
    """把一条省级 feature 拆成若干 Polygon（每个是环的列表）。"""
    geom = feature.get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    if gtype == "Polygon":
        return [coords]
    if gtype == "MultiPolygon":
        return list(coords)
    return []


def main() -> int:
    offline = "--offline" in sys.argv
    try:
        data = load(offline)
    except Exception as exc:  # noqa: BLE001
        print(f"下载失败：{exc}")
        return 1

    by_name = {f["properties"]["name"]: f for f in data.get("features", [])}
    print(f"已加载省级数据：{len(by_name)} 个行政区")

    result: dict[str, dict] = {}
    total_points = 0

    for key, spec in TANG_DAO.items():
        polygons: list[list[list[list[float]]]] = []
        missing = []
        for province in spec["provinces"]:
            feature = by_name.get(province)
            if feature is None:
                missing.append(province)
                continue
            for rings in extract_polygons(feature):
                cleaned = []
                for ring_index, ring in enumerate(rings):
                    simplified = simplify_ring(clean_ring(ring))
                    # 丢掉过小的碎块（岛屿、飞地），保留主体
                    if ring_index == 0 and ring_area(simplified) < 0.05:
                        continue
                    if len(simplified) >= 4:
                        cleaned.append(simplified)
                if cleaned:
                    polygons.append(cleaned)
        if missing:
            print(f"  ⚠ {spec['name']} 缺少省份数据：{missing}")

        points = sum(len(ring) for poly in polygons for ring in poly)
        total_points += points
        result[key] = {
            "name": spec["name"],
            "seat": list(spec["seat"]),
            "provinces": spec["provinces"],
            "type": "MultiPolygon",
            "coordinates": polygons,
        }
        print(f"  {spec['name']:<5} <- {'、'.join(spec['provinces'])}  多边形 {len(polygons)} 个，顶点 {points}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": SOURCE_URL,
        "note": "以现代省级行政区边界近似唐代辖境，仅供展示与尺度演示，非历史行政区划复原。",
        "generated_by": "tools/build_geo.py",
        "simplify_eps": SIMPLIFY_EPS,
        "dao": result,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    print(f"\n已写出 {OUT.name}：{size_kb:.0f} KB，顶点合计 {total_points}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())