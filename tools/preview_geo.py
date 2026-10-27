"""把地理数据渲染成 PNG，用于在没有浏览器的情况下做视觉检查。

    python tools/preview_geo.py [输出路径]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "backend" / "app" / "seed" / "data" / "tang_750_geo.json"

W, H = 1400, 900
PAD = 60

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]


def load_font(size: int = 18):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()

COLORS = [
    (74, 120, 150), (120, 150, 90), (150, 120, 90), (110, 100, 150),
    (90, 150, 140), (150, 110, 130), (100, 130, 170),
]


def project(lon: float, lat: float, bounds) -> tuple[float, float]:
    min_lon, min_lat, max_lon, max_lat = bounds
    sx = (W - 2 * PAD) / (max_lon - min_lon)
    sy = (H - 2 * PAD) / (max_lat - min_lat)
    s = min(sx, sy)
    ox = (W - (max_lon - min_lon) * s) / 2
    oy = (H - (max_lat - min_lat) * s) / 2
    return ox + (lon - min_lon) * s, oy + (max_lat - lat) * s


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".tmp" / "geo_preview.png"
    data = json.loads(GEO.read_text(encoding="utf-8"))
    dao = data["dao"]

    lons, lats = [], []
    for item in dao.values():
        for poly in item["coordinates"]:
            for ring in poly:
                for lon, lat in ring:
                    lons.append(lon)
                    lats.append(lat)
    bounds = (min(lons), min(lats), max(lons), max(lats))

    img = Image.new("RGB", (W, H), (16, 22, 28))
    draw = ImageDraw.Draw(img)
    font = load_font(20)

    for index, (key, item) in enumerate(dao.items()):
        color = COLORS[index % len(COLORS)]
        # 两遍绘制：先描边，再用填充盖住内部接缝
        for poly in item["coordinates"]:
            for ring in poly:
                pts = [project(lon, lat, bounds) for lon, lat in ring]
                if len(pts) >= 3:
                    draw.polygon(pts, fill=color, outline=(8, 14, 18))
        for poly in item["coordinates"]:
            for ring in poly:
                pts = [project(lon, lat, bounds) for lon, lat in ring]
                if len(pts) >= 3:
                    draw.polygon(pts, fill=color)

        seat_lon, seat_lat = item["seat"]
        x, y = project(seat_lon, seat_lat, bounds)
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(255, 220, 120))
        draw.text((x + 8, y - 6), item["name"], fill=(240, 245, 250), font=font)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"saved {out}  size={out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())