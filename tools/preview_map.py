"""按前端相同的投影与两遍绘制逻辑，把接口返回的真实数据渲染成 PNG。

用来在没有浏览器截图能力时做视觉验证：如果这张图对，页面上大概率也对。

    python tools/preview_map.py [world_key] [输出路径]
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:5210"
W, H = 1440, 900
PAD = 26


def load_font(size: int = 20):
    for path in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def polygons_of(region):
    geo = region.get("geo") or {}
    coords = geo.get("coordinates") or []
    if geo.get("type") == "Polygon":
        return [coords]
    if geo.get("type") == "MultiPolygon":
        return coords
    return []


REGION_COLORS = {
    "guannei": (86, 118, 150),
    "henan": (104, 132, 108),
    "hebei": (138, 110, 92),
    "hedong": (120, 104, 142),
    "huainan": (96, 138, 132),
    "jiangnan": (128, 116, 150),
    "longyou": (102, 112, 128),
}
FALLBACK_COLOR = (104, 118, 132)

LABEL_AT = {
    "guannei": (108.6, 33.4),
    "henan": (114.8, 33.9),
    "hebei": (116.6, 39.4),
    "hedong": (112.3, 37.6),
    "huainan": (117.0, 32.2),
    "jiangnan": (116.8, 27.6),
    "longyou": (97.0, 38.6),
}


def stress_alpha(price: float) -> float:
    t = max(0.0, min((price - 1.0) / 1.6, 1.0))
    return round(t * 0.62, 3)


def main() -> int:
    key = sys.argv[1] if len(sys.argv) > 1 else "tang_750"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / ".tmp" / "map_preview.png"

    with urllib.request.urlopen(f"{BASE}/api/worlds/{key}", timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    regions = data["regions"]

    lons, lats = [], []
    for region in regions:
        for poly in polygons_of(region):
            for lon, lat in (poly[0] or []):
                lons.append(lon)
                lats.append(lat)
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    span_lon = max(max_lon - min_lon, 0.001)
    span_lat = max(max_lat - min_lat, 0.001)
    scale = min((W - 2 * PAD) / span_lon, (H - 2 * PAD) / span_lat)
    off_x = (W - span_lon * scale) / 2
    off_y = (H - span_lat * scale) / 2

    def to_xy(lon, lat):
        return off_x + (lon - min_lon) * scale, off_y + (max_lat - lat) * scale

    img = Image.new("RGB", (W, H), (15, 20, 25))
    draw = ImageDraw.Draw(img)
    font = load_font(21)
    small = load_font(15)

    shapes = []
    for region in regions:
        polys = []
        for poly in polygons_of(region):
            ring = poly[0] if poly else []
            if len(ring) >= 3:
                polys.append([to_xy(lon, lat) for lon, lat in ring])
        if polys:
            shapes.append((region, polys))

    # 第一遍：填充 + 描边（内部接缝会被第二遍盖掉）
    for region, polys in shapes:
        color = REGION_COLORS.get(region.get("region_key") or region.get("key"), FALLBACK_COLOR)
        for pts in polys:
            draw.polygon(pts, fill=color, outline=(10, 15, 20))
    # 第二遍：只填不描边
    for region, polys in shapes:
        color = REGION_COLORS.get(region.get("region_key") or region.get("key"), FALLBACK_COLOR)
        for pts in polys:
            draw.polygon(pts, fill=color)

    # 粮价压力叠加（用半透明红在单独图层上合成，模拟 SVG 的 rgba 填充）
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for region, polys in shapes:
        alpha = stress_alpha(region.get("price_index") or 1.0)
        if alpha <= 0:
            continue
        for pts in polys:
            odraw.polygon(pts, fill=(214, 62, 42, int(alpha * 255)))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    for region, _polys in shapes:
        key = region.get("region_key") or region.get("key")
        anchor = LABEL_AT.get(key)
        if anchor:
            x, y = to_xy(anchor[0], anchor[1])
        else:
            x, y = to_xy(region["lon"], region["lat"])
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 214, 120))
        draw.text((x + 7, y - 12), region["name"], fill=(240, 246, 252), font=font)
        draw.text(
            (x + 7, y + 8),
            f"粮价 {(region.get('price_index') or 1):.2f}",
            fill=(190, 208, 222),
            font=small,
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"saved {out}  size={out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())