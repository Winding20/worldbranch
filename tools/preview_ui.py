"""按当前实现画一张界面效果图，便于与真实页面比对。

对应 frontend/src/App.vue 的「舞台」结构：
  地图铺满 → 顶部 HUD → 底部动作条 → 右侧抽屉 → 决策浮层
手机上抽屉从底部升起、浮层铺满，见文末第二张图。

    python tools/mockup_ui4.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "backend" / "app" / "seed" / "data" / "tang_755_geo.json"
OUT = ROOT / ".tmp" / "mockup4.png"
OUT_M = ROOT / ".tmp" / "mockup4-mobile.png"

W, H = 1600, 1000

BG = (15, 20, 25)
PANEL = (22, 29, 36)
PANEL2 = (29, 38, 47)
LINE = (42, 53, 64)
TEXT = (223, 231, 238)
MUTED = (143, 161, 176)
ACCENT = (74, 168, 216)
ACCENT2 = (216, 162, 74)
DANGER = (216, 97, 74)

REGION_FILL = {
    "changan": (196, 188, 162),
    "lingwu": (204, 192, 162),
    "luoyang": (190, 182, 152),
    "suiyang": (198, 188, 156),
    "fanyang": (186, 176, 150),
    "hebei_plain": (194, 180, 150),
    "taiyuan": (188, 180, 158),
    "tongguan": (176, 142, 112),
}

CJK = r"C:\Windows\Fonts\msyh.ttc"
CJK_BD = r"C:\Windows\Fonts\msyhbd.ttc"
SERIF = r"C:\Windows\Fonts\simsun.ttc"


def F(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def rings_of(item):
    coords = item.get("coordinates") or []
    if item.get("type") == "Polygon":
        return coords if coords and isinstance(coords[0][0], list) else [coords]
    return [ring for poly in coords for ring in poly]


def draw_map(size, dim=0.0, focus: str | None = None):
    """画地图。dim 为压暗程度（0 不压暗，1 全黑）。"""
    dao = json.loads(GEO.read_text(encoding="utf-8"))["dao"]
    w, h = size
    img = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(img)

    rnd = random.Random(9)
    for _ in range(int(w * h / 700)):
        x, y = rnd.randint(0, w - 1), rnd.randint(0, h - 1)
        px = img.getpixel((x, y))
        s = rnd.randint(-4, 4)
        img.putpixel((x, y), tuple(max(0, min(255, c + s)) for c in px))

    lons, lats = [], []
    for item in dao.values():
        for ring in rings_of(item):
            for lon, lat in ring:
                lons.append(lon)
                lats.append(lat)
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    scale = min((w - 80) / (max_lon - min_lon), (h - 160) / (max_lat - min_lat))
    ox = (w - (max_lon - min_lon) * scale) / 2
    oy = 60 + ((h - 160) - (max_lat - min_lat) * scale) / 2

    def to_xy(lon, lat):
        return ox + (lon - min_lon) * scale, oy + (max_lat - lat) * scale

    for key, item in dao.items():
        fill = REGION_FILL.get(key, (190, 182, 158))
        # 聚光：非焦点地区压暗（与 CSS 里 opacity 0.22 的效果一致）
        if focus and key != focus:
            fill = tuple(int(c * 0.22) for c in fill)
        for ring in rings_of(item):
            pts = [to_xy(lon, lat) for lon, lat in ring]
            if len(pts) >= 3:
                d.polygon(pts, fill=fill, outline=(30, 26, 22), width=2)

    # 焦点地区加一圈金边
    if focus and focus in dao:
        for ring in rings_of(dao[focus]):
            pts = [to_xy(lon, lat) for lon, lat in ring]
            if len(pts) >= 3:
                d.line(pts + [pts[0]], fill=ACCENT2, width=4, joint="curve")

    names = {
        "changan": "京兆", "lingwu": "灵武", "luoyang": "河南府", "suiyang": "睢阳",
        "fanyang": "范阳", "hebei_plain": "河北诸州", "taiyuan": "太原", "tongguan": "潼关",
    }
    for key, item in dao.items():
        pts = [to_xy(lon, lat) for ring in rings_of(item) for lon, lat in ring]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        d.text((cx, cy), names[key], font=F(SERIF, 20), fill=(51, 44, 37), anchor="mm")

    if dim > 0:
        veil = Image.new("RGBA", size, (8, 11, 14, int(255 * dim)))
        img = Image.alpha_composite(img.convert("RGBA"), veil).convert("RGB")
    return img


def desktop() -> Image.Image:
    # 遮罩只在右半加重，左半留给聚光（与 CSS 的渐变一致）
    img = draw_map((W, H), dim=0.0, focus="hebei_plain")
    veil = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(veil)
    for x in range(W):
        t = x / W
        alpha = int(30 + max(0.0, (t - 0.55) / 0.45) * 120) if t > 0.55 else int(12 + t * 30)
        vd.line([(x, 0), (x, H)], fill=(8, 11, 14, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), veil).convert("RGB")
    d = ImageDraw.Draw(img)

    # ---------- 顶部 HUD ----------
    d.text((26, 18), "756-07-01", font=F(SERIF, 22), fill=TEXT)
    d.text((26, 50), "唐廷", font=F(SERIF, 14), fill=DANGER)
    d.text((W - 320, 20), "府库 1,455,510", font=F(CJK, 16), fill=MUTED)
    d.text((W - 320, 46), "河北 0.32 阳奉阴违", font=F(CJK, 16), fill=ACCENT2)

    # ---------- 观察尺度浮条 ----------
    bar_w = 300
    d.rounded_rectangle(
        [(W - bar_w) // 2, 14, (W + bar_w) // 2, 50], radius=18,
        fill=(17, 23, 29), outline=LINE,
    )
    d.text((W // 2, 32), "观察尺度  地区级 ▾", font=F(CJK, 14), fill=MUTED, anchor="mm")

    # ---------- 底部动作条 ----------
    d.rectangle([0, H - 86, W, H], fill=(10, 14, 18))
    d.line([0, H - 86, W, H - 86], fill=LINE)
    d.line([26, H - 56, W - 420, H - 56], fill=LINE, width=3)
    d.ellipse([26, H - 60, 38, H - 48], fill=ACCENT)
    d.line([26, H - 56, 26 + (W - 446) * 0.20, H - 56], fill=ACCENT, width=3)
    d.text((26, H - 40), "距广德元年还有 79 月", font=F(CJK, 12), fill=MUTED)

    bx = W - 400
    for label, primary in (("1 月", False), ("3 月", False), ("1 年", True), ("朝局", False)):
        bw = 84 if label != "朝局" else 96
        x0 = bx
        d.rounded_rectangle(
            [x0, H - 70, x0 + bw, H - 24], radius=9,
            fill=DANGER if primary else PANEL2, outline=DANGER if primary else LINE,
        )
        d.text((x0 + bw // 2, H - 47), label, font=F(CJK, 15),
               fill=(255, 255, 255) if primary else TEXT, anchor="mm")
        bx += bw + 10
    # 待决计数
    d.ellipse([W - 30, H - 78, W - 12, H - 60], fill=DANGER)
    d.text((W - 21, H - 69), "1", font=F(CJK, 11), fill=(255, 255, 255), anchor="mm")

    # ---------- 决策浮层 ----------
    cw, ch = 540, 560
    cx, cy = W - cw - 28, (H - ch) // 2 - 20
    d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=14, fill=PANEL, outline=ACCENT2, width=1)

    d.rounded_rectangle([cx + 22, cy + 22, cx + 56, cy + 56], radius=6, fill=DANGER)
    d.text((cx + 39, cy + 39), "奏", font=F(SERIF, 18), fill=(255, 255, 255), anchor="mm")
    d.text((cx + 70, cy + 22), "催哥舒翰出战", font=F(CJK_BD, 24), fill=TEXT)
    d.text((cx + 72, cy + 56), "756-07-01", font=F(SERIF, 13), fill=MUTED)
    d.text((cx + cw - 150, cy + 30), "决断后本月结算", font=F(CJK, 11), fill=MUTED)

    body = (
        "哥舒翰守潼关，坚壁不出，奏称「利在坚守，不利轻出」。"
        "杨国忠疑其拥兵自重，力请催促出战。"
    )
    d.multiline_text((cx + 24, cy + 82), body, font=F(SERIF, 15), fill=(198, 214, 226), spacing=8)

    # 朝议
    d.line([cx + 24, cy + 140, cx + 24, cy + 250], fill=LINE, width=2)
    adv = [
        ("李光弼", "军中之事，臣请令其坚守。", "主令其坚守 · 老于兵事"),
        ("李泌", "度支所系，臣以为当换将出战。", "主换将出战 · 练于政事"),
        ("郭子仪", "军中之事，臣请令其坚守。", "主令其坚守 · 老于兵事"),
    ]
    y = cy + 146
    for who, say, meta in adv:
        d.text((cx + 36, y), who, font=F(CJK, 14), fill=TEXT)
        d.text((cx + 36, y + 20), f"「{say}」", font=F(SERIF, 13), fill=(198, 214, 226))
        d.text((cx + 36, y + 40), meta, font=F(CJK, 10), fill=MUTED)
        y += 62

    # 选项
    opts = [
        ("遣使催战", "按史载：潼关失守，长安门户洞开", False),
        ("令其坚守", "府库 −40 万贯；潼关不失，长安得安", True),
        ("换将出战", "临阵易帅，军心浮动：未必失关，但战力大损", False),
    ]
    y = cy + 268
    for label, detail, favored in opts:
        d.rounded_rectangle(
            [cx + 24, y, cx + cw - 24, y + 78], radius=9,
            fill=PANEL2, outline=ACCENT2 if favored else LINE,
        )
        d.text((cx + 40, y + 14), label, font=F(CJK_BD, 16), fill=TEXT)
        d.text((cx + 40, y + 44), detail, font=F(SERIF, 12), fill=MUTED)
        y += 88

    d.text((cx + 24, cy + ch - 26), "稍后再议", font=F(CJK, 12), fill=MUTED)
    return img


def mobile() -> Image.Image:
    w, h = 420, 900
    img = draw_map((w, h), dim=0.0)
    d = ImageDraw.Draw(img)

    # HUD
    d.text((16, 14), "756-07-01", font=F(SERIF, 15), fill=TEXT)
    d.text((16, 36), "唐廷", font=F(SERIF, 10), fill=DANGER)
    d.text((w - 130, 14), "府库 145 万", font=F(CJK, 11), fill=MUTED)
    d.text((w - 130, 32), "河北 0.32 阳奉阴违", font=F(CJK, 10), fill=ACCENT2)

    # 底部动作条（两行）
    d.rectangle([0, h - 116, w, h], fill=(10, 14, 18))
    d.line([0, h - 116, w, h - 116], fill=LINE)
    d.line([14, h - 96, w - 14, h - 96], fill=LINE, width=3)
    d.line([14, h - 96, 14 + (w - 28) * 0.2, h - 96], fill=ACCENT, width=3)
    d.text((14, h - 84), "距广德元年还有 79 月", font=F(CJK, 9), fill=MUTED)

    bx = 14
    for label, primary in (("1 月", False), ("3 月", False), ("1 年", True), ("朝局", False)):
        bw = 78
        d.rounded_rectangle([bx, h - 66, bx + bw, h - 26], radius=8,
                            fill=DANGER if primary else PANEL2,
                            outline=DANGER if primary else LINE)
        d.text((bx + bw // 2, h - 46), label, font=F(CJK, 12),
               fill=(255, 255, 255) if primary else TEXT, anchor="mm")
        bx += bw + 8
    d.ellipse([w - 24, h - 74, w - 8, h - 58], fill=DANGER)
    d.text((w - 16, h - 66), "1", font=F(CJK, 9), fill=(255, 255, 255), anchor="mm")

    # 抽屉（升起一半，示意）
    top = h - 400
    d.rounded_rectangle([0, top, w, h - 116], radius=16, fill=PANEL, outline=LINE)
    d.text((18, top + 14), "决断  ·  军事  ·  人物  ·  史实", font=F(CJK, 12), fill=MUTED)
    d.text((18, top + 46), "五月，河北道请赈", font=F(CJK_BD, 15), fill=TEXT)
    d.text((18, top + 74), "府库 −90 万贯，民变 −0.22", font=F(CJK, 11), fill=MUTED)
    return img


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    desktop().save(OUT)
    mobile().save(OUT_M)
    print(f"saved {OUT}")
    print(f"saved {OUT_M}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())