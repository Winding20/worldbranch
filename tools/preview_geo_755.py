"""把 tang_755 的地理数据画出来，检查切分有没有画坏。

    python tools/preview_geo_755.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "backend" / "app" / "seed" / "data" / "tang_755_geo.json"
OUT = ROOT / ".tmp" / "geo755.png"

W, H = 1400, 900
PAPER = (240, 233, 216)
INK = (38, 33, 28)

FILL = {
    "changan": (206, 196, 168),
    "lingwu": (214, 200, 168),
    "luoyang": (200, 192, 160),
    "suiyang": (208, 198, 164),
    "fanyang": (196, 186, 158),
    "hebei_plain": (204, 190, 158),
    "taiyuan": (198, 190, 166),
    "tongguan": (188, 150, 120),
}

SERIF = r"C:\Windows\Fonts\simsun.ttc"


def F(size):
    try:
        return ImageFont.truetype(SERIF, size)
    except OSError:
        return ImageFont.load_default()


def rings_of(item):
    coords = item.get("coordinates") or []
    if item.get("type") == "Polygon":
        return coords if coords and isinstance(coords[0][0], list) else [coords]
    return [ring for poly in coords for ring in poly]


def main() -> int:
    dao = json.loads(GEO.read_text(encoding="utf-8"))["dao"]
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    rnd = random.Random(5)
    for _ in range(2200):
        x, y = rnd.randint(0, W - 1), rnd.randint(0, H - 1)
        px = img.getpixel((x, y))
        s = rnd.randint(-5, 3)
        img.putpixel((x, y), tuple(max(0, min(255, c + s)) for c in px))

    lons, lats = [], []
    for item in dao.values():
        for ring in rings_of(item):
            for lon, lat in ring:
                lons.append(lon)
                lats.append(lat)
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    scale = min((W - 120) / (max_lon - min_lon), (H - 120) / (max_lat - min_lat))
    ox = (W - (max_lon - min_lon) * scale) / 2
    oy = (H - (max_lat - min_lat) * scale) / 2

    def to_xy(lon, lat):
        return ox + (lon - min_lon) * scale, oy + (max_lat - lat) * scale

    for key, item in dao.items():
        fill = FILL.get(key, (200, 192, 170))
        for ring in rings_of(item):
            pts = [to_xy(lon, lat) for lon, lat in ring]
            if len(pts) >= 3:
                d.polygon(pts, fill=fill, outline=INK, width=2)

    centers = {}
    for key, item in dao.items():
        pts = [
            to_xy(lon, lat) for ring in rings_of(item) for lon, lat in ring
        ]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        centers[key] = (cx, cy)

    names = {
        "changan": "京兆",
        "lingwu": "灵武",
        "luoyang": "河南府",
        "suiyang": "睢阳",
        "fanyang": "范阳",
        "hebei_plain": "河北诸州",
        "taiyuan": "太原",
        "tongguan": "潼关",
    }
    for key, (cx, cy) in centers.items():
        d.text((cx, cy), names[key], font=F(22), fill=INK, anchor="mm")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(f"saved {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())