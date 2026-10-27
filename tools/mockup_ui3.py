"""界面方向提案 3：减法。

平时（没有决策）看到的界面，只保留四样东西：
地图、日期、两个关键数字、一个推进按钮。

    python tools/mockup_ui3.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "backend" / "app" / "seed" / "data" / "tang_750_geo.json"
OUT = ROOT / ".tmp" / "mockup3.png"

W, H = 1600, 1000

PAPER = (240, 233, 216)
INK = (38, 33, 28)
INK_SOFT = (108, 96, 82)
CINNABAR = (172, 52, 41)

REGION_FILL = {
    "guannei": (214, 202, 172),
    "henan": (203, 195, 160),
    "hebei": (208, 186, 158),
    "hedong": (198, 189, 165),
    "huainan": (206, 197, 167),
    "jiangnan": (195, 191, 163),
    "longyou": (185, 179, 159),
}

CJK = r"C:\Windows\Fonts\msyh.ttc"
CJK_BD = r"C:\Windows\Fonts\msyhbd.ttc"
SERIF = r"C:\Windows\Fonts\simsun.ttc"


def F(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def polys(item):
    coords = item.get("coordinates") or []
    return [coords] if item.get("type") == "Polygon" else coords


def main() -> int:
    dao = json.loads(GEO.read_text(encoding="utf-8"))["dao"]
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    rnd = random.Random(3)
    for _ in range(3200):
        x, y = rnd.randint(0, W - 1), rnd.randint(0, H - 1)
        px = img.getpixel((x, y))
        s = rnd.randint(-5, 3)
        img.putpixel((x, y), tuple(max(0, min(255, c + s)) for c in px))

    lons, lats = [], []
    for item in dao.values():
        for poly in polys(item):
            for lon, lat in poly[0]:
                lons.append(lon)
                lats.append(lat)
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    scale = min((W - 200) / (max_lon - min_lon), (H - 260) / (max_lat - min_lat))
    ox = (W - (max_lon - min_lon) * scale) / 2
    oy = 90 + ((H - 260) - (max_lat - min_lat) * scale) / 2

    def to_xy(lon, lat):
        return ox + (lon - min_lon) * scale, oy + (max_lat - lat) * scale

    for key, item in dao.items():
        fill = REGION_FILL.get(key, (200, 192, 170))
        for poly in polys(item):
            pts = [to_xy(lon, lat) for lon, lat in poly[0]]
            if len(pts) >= 3:
                d.polygon(pts, fill=fill, outline=INK, width=2)

    # 只在"出事"的道上染色：河北民变 0.62
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for poly in polys(dao["hebei"]):
        od.polygon([to_xy(lon, lat) for lon, lat in poly[0]], fill=(172, 52, 41, 66))
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    d = ImageDraw.Draw(img)

    labels = {
        "guannei": ("关内道", (108.2, 34.6)),
        "henan": ("河南道", (115.6, 34.4)),
        "hebei": ("河北道", (117.4, 38.6)),
        "hedong": ("河东道", (112.4, 38.2)),
        "huainan": ("淮南道", (118.6, 32.6)),
        "jiangnan": ("江南道", (116.4, 28.4)),
        "longyou": ("陇右道", (96.0, 39.0)),
    }
    for key, (name, (lon, lat)) in labels.items():
        x, y = to_xy(lon, lat)
        d.text((x, y), name, font=F(SERIF, 28), fill=INK, anchor="mm")

    # ---- 四样常驻元素 ----
    # 1) 日期
    d.text((56, 42), "天宝九年 · 七月", font=F(SERIF, 28), fill=INK)
    d.text((56, 80), "唐廷", font=F(SERIF, 15), fill=CINNABAR)

    # 2) 两个数字
    d.text((W - 380, 40), "府库 279 万贯", font=F(CJK, 20), fill=INK)
    d.text((W - 380, 74), "河北臣属 0.32 · 阳奉阴违", font=F(CJK, 18), fill=(150, 92, 56))

    # 3) 一行"上月"提示
    d.line([56, H - 150, W - 56, H - 150], fill=(206, 192, 166), width=1)
    d.text(
        (56, H - 138),
        "上月：河南调粮 26 万石，河北粮价 1.42 → 1.18，民变 0.55 → 0.62",
        font=F(CJK, 17),
        fill=INK_SOFT,
    )

    # 4) 进度条 + 推进按钮
    bar_y = H - 92
    d.line([56, bar_y, W - 300, bar_y], fill=(178, 164, 140), width=2)
    for i, year in enumerate(range(750, 756)):
        x = 56 + (W - 356) * i / 5
        d.line([x, bar_y - 7, x, bar_y + 7], fill=(178, 164, 140), width=2)
        d.text((x, bar_y + 20), f"{year}", font=F(SERIF, 14), fill=INK_SOFT, anchor="mt")
    marker = 56 + (W - 356) * (6 / 60)
    d.ellipse([marker - 7, bar_y - 7, marker + 7, bar_y + 7], fill=CINNABAR)

    d.rectangle([W - 260, H - 130, W - 56, H - 58], fill=CINNABAR, outline=(132, 38, 30), width=2)
    d.text((W - 158, H - 94), "推进一月", font=F(CJK_BD, 22), fill=PAPER, anchor="mm")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(f"saved {OUT} size={OUT.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())