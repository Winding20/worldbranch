"""界面方向提案 2：让重点占满屏幕。

游戏感来自"节奏"：平时看世界，出事时世界退到背景、只剩眼前这件事。
所以决策不是侧栏里的一张卡，而是盖在地图上的整屏奏疏。

    python tools/mockup_ui2.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "backend" / "app" / "seed" / "data" / "tang_750_geo.json"
OUT = ROOT / ".tmp" / "mockup2.png"

W, H = 1600, 1000

PAPER = (239, 231, 214)
PAPER_HI = (247, 241, 229)
INK = (38, 33, 28)
INK_SOFT = (96, 86, 74)
CINNABAR = (172, 52, 41)
CINNABAR_DK = (132, 38, 30)
GOLD = (146, 114, 58)

REGION_FILL = {
    "guannei": (214, 202, 172),
    "henan": (204, 196, 162),
    "hebei": (212, 188, 158),
    "hedong": (199, 190, 166),
    "huainan": (207, 198, 168),
    "jiangnan": (196, 192, 164),
    "longyou": (186, 180, 160),
}

CJK = r"C:\Windows\Fonts\msyh.ttc"
CJK_BD = r"C:\Windows\Fonts\msyhbd.ttc"
SERIF = r"C:\Windows\Fonts\simsun.ttc"


def F(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def polys(item):
    coords = item.get("coordinates") or []
    return [coords] if item.get("type") == "Polygon" else coords


def main() -> int:
    data = json.loads(GEO.read_text(encoding="utf-8"))
    dao = data["dao"]

    # ---------------- 底：整屏地图 ----------------
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    rnd = random.Random(11)
    for _ in range(3000):
        x, y = rnd.randint(0, W - 1), rnd.randint(0, H - 1)
        px = img.getpixel((x, y))
        s = rnd.randint(-6, 4)
        img.putpixel((x, y), tuple(max(0, min(255, c + s)) for c in px))

    lons, lats = [], []
    for item in dao.values():
        for poly in polys(item):
            for lon, lat in poly[0]:
                lons.append(lon)
                lats.append(lat)
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    # 地图铺满整个画面（留一点边）
    scale = min((W - 120) / (max_lon - min_lon), (H - 120) / (max_lat - min_lat))
    ox = (W - (max_lon - min_lon) * scale) / 2
    oy = (H - (max_lat - min_lat) * scale) / 2

    def to_xy(lon, lat):
        return ox + (lon - min_lon) * scale, oy + (max_lat - lat) * scale

    for key, item in dao.items():
        fill = REGION_FILL.get(key, (200, 192, 170))
        for poly in polys(item):
            pts = [to_xy(lon, lat) for lon, lat in poly[0]]
            if len(pts) >= 3:
                d.polygon(pts, fill=fill, outline=INK, width=2)

    hebei = dao.get("hebei")
    if hebei:
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        for poly in polys(hebei):
            od.polygon([to_xy(lon, lat) for lon, lat in poly[0]], fill=(172, 52, 41, 80))
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
        d.text((x, y), name, font=F(SERIF, 30), fill=INK, anchor="mm")

    # ---------------- 压暗整屏 ----------------
    scrim = Image.new("RGBA", (W, H), (22, 18, 14, 186))
    img = Image.alpha_composite(img.convert("RGBA"), scrim).convert("RGB")
    d = ImageDraw.Draw(img)

    # ---------------- 聚光：把"出事的地方"从暗场里挑出来 ----------------
    if hebei:
        spot = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd0 = ImageDraw.Draw(spot)
        for poly in polys(hebei):
            pts = [to_xy(lon, lat) for lon, lat in poly[0]]
            sd0.polygon(pts, fill=(212, 188, 158, 255), outline=(172, 52, 41, 255))
        img = Image.alpha_composite(img.convert("RGBA"), spot).convert("RGB")
        d = ImageDraw.Draw(img)
        hx, hy = to_xy(117.4, 38.6)
        d.text((hx, hy), "河北道", font=F(SERIF, 30), fill=INK, anchor="mm")

    # ---------------- 中央奏疏 ----------------
    CW, CH = 820, 660
    CX, CY = (W - CW) // 2, 130

    # 投影
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rectangle([CX + 10, CY + 16, CX + CW + 10, CY + CH + 16], fill=(0, 0, 0, 120))
    img = Image.alpha_composite(img.convert("RGBA"), shadow).convert("RGB")
    d = ImageDraw.Draw(img)

    d.rectangle([CX, CY, CX + CW, CY + CH], fill=PAPER_HI, outline=CINNABAR_DK, width=3)
    d.rectangle([CX + 14, CY + 14, CX + CW - 14, CY + CH - 14], outline=(206, 186, 158), width=1)

    # 朱印
    d.rectangle([CX + 40, CY + 38, CX + 96, CY + 94], fill=CINNABAR)
    d.text((CX + 68, CY + 66), "奏", font=F(SERIF, 34), fill=PAPER_HI, anchor="mm")

    d.text((CX + 122, CY + 34), "河北藩镇上表请饷", font=F(CJK_BD, 34), fill=INK)
    d.text((CX + 124, CY + 84), "天宝九年 · 七月", font=F(SERIF, 18), fill=INK_SOFT)

    body = (
        "臣安禄山顿首。河北三镇军士十七万，府库已罄，粮饷不继。\n"
        "边军窃议于营中，臣恐不能制。伏请朝廷拨付钱帛，以安军心。"
    )
    d.multiline_text((CX + 48, CY + 126), body, font=F(SERIF, 20), fill=INK, spacing=14)

    d.line([CX + 48, CY + 206, CX + CW - 48, CY + 206], fill=(206, 186, 158), width=1)

    # 三项抉择：第一项为"主推"，用朱色实心，另外两项描边
    options = [
        ("如数拨付", "府库耗 56 万贯", "臣属度 +0.12，一年无事", True),
        ("折半给付", "府库耗 28 万贯", "臣属度 +0.03，边军怨望", False),
        ("断然拒绝", "分文不出", "臣属度减 0.18，河北民变增 0.14", False),
    ]
    y = CY + 232
    for label, cost, note, primary in options:
        box = [CX + 44, y, CX + CW - 44, y + 108]
        if primary:
            d.rectangle(box, fill=CINNABAR, outline=CINNABAR_DK, width=2)
            d.text((CX + 68, y + 22), label, font=F(CJK_BD, 26), fill=PAPER_HI)
            d.text((CX + 68, y + 62), f"{cost}   ·   {note}", font=F(SERIF, 18), fill=(245, 224, 210))
        else:
            d.rectangle(box, fill=PAPER, outline=(180, 164, 138), width=1)
            d.text((CX + 68, y + 22), label, font=F(CJK_BD, 26), fill=INK)
            d.text((CX + 68, y + 62), f"{cost}   ·   {note}", font=F(SERIF, 18), fill=CINNABAR)
        y += 122

    d.text(
        (CX + 48, CY + CH - 52),
        "回车或点击决断 · 决断之后本月即结算",
        font=F(CJK, 15),
        fill=INK_SOFT,
    )

    # ---------------- HUD（贴边，不抢戏） ----------------
    d.text((44, 36), "天宝九年 · 七月", font=F(SERIF, 22), fill=(238, 230, 212))
    d.text((44, 70), "唐廷", font=F(SERIF, 16), fill=(214, 150, 130))

    d.text((W - 380, 40), "府库 279 万贯", font=F(CJK, 18), fill=(238, 230, 212))
    d.text((W - 380, 70), "河北臣属 0.32 · 阳奉阴违", font=F(CJK, 18), fill=(226, 174, 120))

    # ---------------- 底部：五年进度 ----------------
    bar_y = H - 78
    d.line([80, bar_y, W - 80, bar_y], fill=(120, 108, 92), width=2)
    for i, year in enumerate(range(750, 756)):
        x = 80 + (W - 160) * i / 5
        d.line([x, bar_y - 8, x, bar_y + 8], fill=(150, 136, 116), width=2)
        d.text((x, bar_y + 22), f"{year}", font=F(SERIF, 15), fill=(168, 156, 136), anchor="mt")
    marker = 80 + (W - 160) * (6 / 60)
    d.ellipse([marker - 8, bar_y - 8, marker + 8, bar_y + 8], fill=CINNABAR)
    d.text((marker, bar_y - 26), "现在", font=F(CJK, 14), fill=(226, 174, 120), anchor="mb")
    d.text((W - 80, bar_y - 26), "距五年之期还有 54 个月", font=F(CJK, 15), fill=(170, 158, 138), anchor="rb")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(f"saved {OUT} size={OUT.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())