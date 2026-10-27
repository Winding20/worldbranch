"""界面方向提案渲染（用于给用户看设计方向，不是实际产品界面）。

用代码画出来，是因为本机无法截浏览器图；这张图代表"我打算做成什么样"。

    python tools/mockup_ui.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "backend" / "app" / "seed" / "data" / "tang_750_geo.json"
OUT = ROOT / ".tmp" / "mockup.png"

W, H = 1600, 1000

# 绢帛配色
PAPER = (239, 231, 214)
PAPER_DK = (226, 215, 193)
INK = (43, 38, 32)
INK_SOFT = (92, 82, 70)
CINNABAR = (176, 58, 46)
GOLD = (150, 118, 62)

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


def font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def polygons_of(item):
    coords = item.get("coordinates") or []
    if item.get("type") == "Polygon":
        return [coords]
    return coords


def main() -> int:
    data = json.loads(GEO.read_text(encoding="utf-8"))
    dao = data["dao"]

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    # 纸面做一点斑驳
    import random

    rnd = random.Random(7)
    for _ in range(2600):
        x, y = rnd.randint(0, W - 1), rnd.randint(0, H - 1)
        shade = rnd.randint(-6, 4)
        px = img.getpixel((x, y))
        img.putpixel((x, y), tuple(max(0, min(255, c + shade)) for c in px))

    # ---------------- 顶部 ----------------
    d.rectangle([0, 0, W, 76], fill=PAPER_DK)
    d.line([0, 76, W, 76], fill=INK_SOFT, width=1)
    d.text((44, 22), "天宝九年 · 三月", font=font(SERIF, 30), fill=INK)
    d.text((360, 30), "唐廷", font=font(SERIF, 20), fill=CINNABAR)
    d.text((W - 300, 28), "第五年 · 还有 51 个月", font=font(CJK, 17), fill=INK_SOFT)

    # ---------------- 地图 ----------------
    MAP = (40, 110, 1010, 820)
    lons, lats = [], []
    for item in dao.values():
        for poly in polygons_of(item):
            for lon, lat in poly[0]:
                lons.append(lon)
                lats.append(lat)
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    mw, mh = MAP[2] - MAP[0], MAP[3] - MAP[1]
    span_lon, span_lat = max_lon - min_lon, max_lat - min_lat
    scale = min(mw / span_lon, mh / span_lat)
    ox = MAP[0] + (mw - span_lon * scale) / 2
    oy = MAP[1] + (mh - span_lat * scale) / 2

    def to_xy(lon, lat):
        return ox + (lon - min_lon) * scale, oy + (max_lat - lat) * scale

    # 逐个道填充 + 墨线描边（Pillow 的 polygon 直接支持 outline/width，
    # 不要再用"先铺一层深色"的土办法，那会变成脏兮兮的投影）
    for key, item in dao.items():
        fill = REGION_FILL.get(key, (200, 192, 170))
        for poly in polygons_of(item):
            ring = poly[0]
            pts = [to_xy(lon, lat) for lon, lat in ring]
            if len(pts) >= 3:
                d.polygon(pts, fill=fill, outline=INK, width=2)

    # 河北：受灾，染一层朱
    hebei = dao.get("hebei")
    if hebei:
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for poly in polygons_of(hebei):
            pts = [to_xy(lon, lat) for lon, lat in poly[0]]
            od.polygon(pts, fill=(176, 58, 46, 70))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        d = ImageDraw.Draw(img)

    # 地名
    labels = {
        "guannei": ("关内道", (108.2, 34.6)),
        "henan": ("河南道", (115.6, 34.4)),
        "hebei": ("河北道", (117.4, 38.6)),
        "hedong": ("河东道", (112.4, 38.2)),
        "huainan": ("淮南道", (118.6, 32.6)),
        "jiangnan": ("江南道", (116.4, 28.4)),
        "longyou": ("陇右道", (96.0, 39.0)),
    }
    f_name = font(SERIF, 26)
    f_sub = font(CJK, 15)
    for key, (name, (lon, lat)) in labels.items():
        x, y = to_xy(lon, lat)
        d.text((x, y), name, font=f_name, fill=INK, anchor="mm")
        if key == "hebei":
            d.text((x, y + 26), "民变 0.62", font=f_sub, fill=CINNABAR, anchor="mm")

    # 粮道箭头（河北 ← 河南）
    ax, ay = to_xy(114.6, 35.6)
    bx, by = to_xy(115.9, 37.8)
    d.line([ax, ay, bx, by], fill=CINNABAR, width=3)
    ang = 26
    d.polygon([(bx, by), (bx - 14, by - 12), (bx - 5, by - 2)], fill=CINNABAR)

    # ---------------- 右侧：奏疏 ----------------
    PX, PY, PW = 1050, 110, 510
    d.rectangle([PX, PY, PX + PW, PY + 700], fill=(246, 240, 226), outline=INK_SOFT, width=2)
    d.rectangle([PX + 18, PY + 18, PX + PW - 18, PY + 700 - 18], outline=(200, 188, 164), width=1)

    d.text((PX + 40, PY + 42), "奏", font=font(SERIF, 34), fill=CINNABAR)
    d.line([PX + 92, PY + 46, PX + 92, PY + 700 - 42], fill=(200, 120, 100), width=1)

    d.text((PX + 118, PY + 40), "河北藩镇上表请饷", font=font(CJK_BD, 28), fill=INK)
    d.text((PX + 118, PY + 82), "天宝九年 七月", font=font(SERIF, 16), fill=INK_SOFT)

    body = (
        "臣安禄山顿首。河北三镇军士十七万，府库已罄，\n"
        "粮饷不继，边军窃议。伏请朝廷拨付钱帛，\n"
        "以安军心，以固边圉。"
    )
    d.multiline_text((PX + 46, PY + 126), body, font=font(SERIF, 19), fill=INK, spacing=12)

    d.line([PX + 46, PY + 250, PX + PW - 46, PY + 250], fill=(200, 188, 164), width=1)

    options = [
        ("如数拨付", "府库 −56 万贯 · 臣属度 +0.12", "可保一年无事"),
        ("折半给付", "府库 −28 万贯 · 臣属度 +0.03", "边军或有怨言"),
        ("断然拒绝", "臣属度 −0.18 · 河北民变 +0.14", "恐生兵变"),
    ]
    y = PY + 272
    for i, (label, cost, note) in enumerate(options):
        box = [PX + 40, y, PX + PW - 40, y + 118]
        d.rectangle(box, fill=(238, 231, 215), outline=(190, 176, 150), width=1)
        if i == 0:
            d.rectangle(box, outline=CINNABAR, width=2)
        d.text((PX + 60, y + 22), label, font=font(CJK_BD, 22), fill=INK)
        d.text((PX + 60, y + 58), cost, font=font(SERIF, 16), fill=CINNABAR)
        d.text((PX + 60, y + 86), note, font=font(CJK, 14), fill=INK_SOFT)
        y += 132

    d.text(
        (PX + 40, PY + 690 - 30),
        "选完之后，这里的数字会立刻变化。",
        font=font(CJK, 14),
        fill=INK_SOFT,
    )

    # ---------------- 底部 ----------------
    d.line([0, 872, W, 872], fill=INK_SOFT, width=1)
    d.text((44, 900), "推进：", font=font(SERIF, 22), fill=INK)
    bx0 = 150
    for label in ("一月", "三月", "一年"):
        d.rectangle([bx0, 898, bx0 + 110, 948], fill=(228, 218, 198), outline=INK_SOFT, width=1)
        d.text((bx0 + 55, 923), label, font=font(SERIF, 20), fill=INK, anchor="mm")
        bx0 += 126

    d.text(
        (W - 620, 906),
        "上月：河南调粮 26 万石 → 河北粮价 1.42 → 1.18",
        font=font(CJK, 16),
        fill=INK_SOFT,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(f"saved {OUT} size={OUT.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())