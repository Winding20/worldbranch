"""WorldBranch 宣传片：纯代码逐帧渲染 + numpy 合成配乐 + FFmpeg 编码。

遵循 code-video-showcase 技能的创作规范（绯墨剧场主题 / 120 BPM / 大字卡 + 风格段结构 /
确定性渲染），但因本机浏览器在沙箱内无法启动（crashpad 被拒），
渲染器从 HTML/Canvas 换成了 Pillow —— 每一帧仍是 t 的纯函数。

    python tools/promo/build_promo.py                # 出成片
    python tools/promo/build_promo.py --frames-only  # 只出帧，便于检查
    python tools/promo/build_promo.py --stills       # 只出几张静帧

产物：dist-promo/worldbranch-promo.mp4（1920×1080 / 30fps / H.264 + AAC）
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent.parent
WORK = ROOT / ".tmp" / "promo"
OUT = ROOT / "dist-promo"
GEO = ROOT / "backend" / "app" / "seed" / "data" / "tang_755_geo.json"

W, H = 1920, 1080
FPS = 30
BPM = 120
BEAT = 60 / BPM  # 0.5s

# ---------------- 主题：08 绯墨剧场 crimson-theater ----------------
BG = (10, 10, 10)
BG_DEEP = (6, 6, 6)
INK = (239, 239, 239)
MUTED = (150, 146, 142)
ACCENT = (177, 18, 38)      # #b11226
ACCENT_SOFT = (198, 62, 74)
PAPER = (239, 239, 239)

F_SERIF = r"C:\Windows\Fonts\simsun.ttc"
F_SANS = r"C:\Windows\Fonts\msyh.ttc"
F_SANS_BD = r"C:\Windows\Fonts\msyhbd.ttc"
F_MONO = r"C:\Windows\Fonts\consola.ttf"
F_DISPLAY = r"C:\Windows\Fonts\timesbd.ttf"

_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def F(path: str, size: int) -> ImageFont.FreeTypeFont:
    key = (path, size)
    if key not in _cache:
        try:
            _cache[key] = ImageFont.truetype(path, size)
        except OSError:
            _cache[key] = ImageFont.load_default()
    return _cache[key]


# ---------------- 缓动 ----------------
def clamp(v: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, v))


def out_cubic(x: float) -> float:
    x = clamp(x)
    return 1 - (1 - x) ** 3


def out_expo(x: float) -> float:
    x = clamp(x)
    return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)


def in_out(x: float) -> float:
    x = clamp(x)
    return 3 * x * x - 2 * x * x * x


def progress(t: float, start: float, dur: float) -> float:
    """t 在 [start, start+dur] 内的归一化进度。"""
    if dur <= 0:
        return 1.0 if t >= start else 0.0
    return clamp((t - start) / dur)


# ---------------- 背景 ----------------
def stage_background(t: float, pulse: float = 0.0) -> Image.Image:
    """绯墨剧场：顶光偏红 + 四周压暗，轻微颗粒。"""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # 竖向渐变
    for y in range(H):
        k = y / H
        c = tuple(int(BG[i] + (BG_DEEP[i] - BG[i]) * k) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)
    # 顶部聚光
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    alpha = 0.46 + 0.12 * pulse
    cx, cy = W * 0.5, -H * 0.25
    for r in range(18, 0, -1):
        rr = W * 0.62 * r / 18
        a = alpha * (1 - r / 18) ** 1.4
        gd.ellipse(
            [cx - rr, cy - rr * 0.7, cx + rr, cy + rr * 0.7],
            fill=(int(ACCENT[0] * a), int(ACCENT[1] * a), int(ACCENT[2] * a)),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(150))
    img = Image.blend(img, Image.blend(img, glow, 0.85), 0.9)
    # 暗角
    vig = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse([-W * 0.25, -H * 0.35, W * 1.25, H * 1.35], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(260))
    dark = Image.new("RGB", (W, H), BG_DEEP)
    img = Image.composite(img, Image.blend(img, dark, 0.55), vig)
    return img


def grain(img: Image.Image, t: float, amount: int = 6) -> Image.Image:
    """确定性颗粒：用 t 生成种子，同一 t 出同一帧。"""
    rng = np.random.default_rng(int(t * 1000) & 0xFFFFFFFF)
    noise = rng.integers(-amount, amount + 1, size=(H // 4, W // 4, 1), dtype=np.int16)
    noise = np.repeat(np.repeat(noise, 4, axis=0), 4, axis=1)[:H, :W]
    arr = np.asarray(img).astype(np.int16) + noise
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ---------------- 排版 ----------------
def text_c(d: ImageDraw.ImageDraw, xy, s, font, fill, anchor="mm"):
    d.text(xy, s, font=font, fill=fill, anchor=anchor)


def typewriter(s: str, t: float, start: float, cps: float = 18.0) -> str:
    n = int(clamp((t - start) * cps, 0, len(s)))
    return s[:n]


def bar(d, x0, y0, x1, y1, fill, r=8):
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill)


# ---------------- 场景 ----------------
def scene_opening(u: float) -> Image.Image:
    """0–6s：品牌字逐字出现 + 一行说明 + 代码列上滚。"""
    pulse = 1 - abs(u / 3.0 - 1)
    img = stage_background(u, pulse)
    d = ImageDraw.Draw(img)

    # 代码列上滚（背景层）
    code = [
        "class HistoricalEvent:",
        "    conditions = {...}",
        "    effects = {...}",
        "engine.advance(months=12)",
        "fork = history.check(branch)",
        "if not conditions: diverge()",
    ]
    for i, line in enumerate(code):
        y = (i * 120 - u * 90) % (H + 240) - 120
        text_c(d, (260, y), line, F(F_MONO, 30), (38, 26, 28), "lm")
        text_c(d, (W - 300, y + 60), line, F(F_MONO, 26), (30, 22, 24), "rm")

    # 标题逐字
    title = "WorldBranch"
    shown = typewriter(title, u, 0.35, 11)
    big = F(F_DISPLAY, 190)
    tw = d.textlength(title, font=big)
    x = W / 2 - tw / 2
    for i, ch in enumerate(shown):
        appear = clamp((u - 0.35 - i * 0.09) * 6)
        if appear <= 0:
            continue
        dy = (1 - out_cubic(appear)) * 40
        d.text((x, H * 0.42 + dy), ch, font=big, fill=INK, anchor="lm")
        x += d.textlength(ch, font=big)

    # 中文副标
    sub_a = out_cubic(progress(u, 2.3, 0.6))
    if sub_a > 0:
        y = H * 0.42 + 150
        text_c(d, (W / 2, y), "唐 史 推 演 器", F(F_SERIF, 64),
               (int(INK[0] * sub_a), int(INK[1] * sub_a), int(INK[2] * sub_a)))

    # 一行说明
    line_a = out_cubic(progress(u, 3.2, 0.7))
    if line_a > 0:
        text_c(d, (W / 2, H * 0.42 + 236),
               "给定真实的历史起点，你替唐廷做决定",
               F(F_SANS, 40), (int(200 * line_a), int(196 * line_a), int(192 * line_a)))

    # 红色细线
    lw = out_expo(progress(u, 3.9, 0.5))
    if lw > 0:
        half = 260 * lw
        d.line([(W / 2 - half, H * 0.42 + 300), (W / 2 + half, H * 0.42 + 300)],
               fill=ACCENT, width=3)
    return img


CARDS = [
    ("天宝十四载", "21 件史实", "每一件都有前提条件与出处"),
    ("潼关", "三种走法", "同一次危机，三种原因不同的结局"),
    ("河北", "权重最高", "真正的后果不是平定，是割据"),
    ("八年之后", "克复 75.4", "赢了战争，输了河北"),
    ("开源", "双击即跑", "SQLite 内置，不需要数据库"),
]


def scene_bigcard(idx: int, u: float) -> Image.Image:
    """1s 一张：砸入 + 速度线。"""
    line1, line2, note = CARDS[idx]
    img = stage_background(u, pulse=1.0 if u < 0.2 else 0)
    d = ImageDraw.Draw(img)

    # 速度线
    for i in range(14):
        yy = 140 + i * 62
        ln = out_expo(clamp((u - 0.05 - i * 0.012) * 8)) * W
        a = int(60 * (1 - u))
        if a > 0:
            d.line([(0, yy), (ln, yy)], fill=(a // 2, 8, 10), width=3)

    z = out_expo(progress(u, 0, 0.22))
    scale = 1.22 - 0.22 * z
    alpha = z

    f1 = F(F_SERIF, int(72 * scale))
    f2 = F(F_SANS_BD, int(150 * scale))
    f3 = F(F_SANS, 34)

    y1 = H * 0.36 - (1 - z) * 30
    y2 = H * 0.36 + 100
    c1 = (int(MUTED[0] * alpha), int(MUTED[1] * alpha), int(MUTED[2] * alpha))
    c2 = (int(INK[0] * alpha), int(INK[1] * alpha), int(INK[2] * alpha))
    c3 = (int(ACCENT[0] * alpha), int(ACCENT[1] * alpha), int(ACCENT[2] * alpha))

    text_c(d, (W / 2, y1), line1, f1, c1)
    text_c(d, (W / 2, y2), line2, f2, c2)

    # 关键词下划
    uw = out_expo(progress(u, 0.12, 0.3)) * 420
    if uw > 0:
        d.line([(W / 2 - uw / 2, y2 + 96), (W / 2 + uw / 2, y2 + 96)], fill=c3, width=5)

    if u > 0.25:
        na = out_cubic(progress(u, 0.25, 0.3))
        text_c(d, (W / 2, H * 0.72), note, f3,
               (int(190 * na), int(186 * na), int(182 * na)))

    # 角落编号
    text_c(d, (W - 90, H - 70), f"0{idx + 1} / 05", F(F_MONO, 30), (90, 84, 82), "rm")
    return img


# ---------------- 风格段 ----------------
def seg_conditions(u: float) -> Image.Image:
    """史实是条件句：显示 conditions → 判定 → 应验/改道。"""
    img = stage_background(u)
    d = ImageDraw.Draw(img)
    a = out_cubic(progress(u, 0, 0.5))
    text_c(d, (160, 150), "史实不是剧本，是条件句", F(F_SANS_BD, 56),
           (int(INK[0] * a), int(INK[1] * a), int(INK[2] * a)), "lm")

    rows = [
        ("region_held", "tongguan", "潼关尚在我手"),
        ("character_alive", "geshu_han", "哥舒翰尚在"),
        ("region_lost", "changan", "长安未失"),
    ]
    y0 = 300
    for i, (k, v, desc) in enumerate(rows):
        p = out_cubic(progress(u, 0.25 + i * 0.16, 0.35))
        if p <= 0:
            continue
        y = y0 + i * 96
        d.rectangle([160, y + 60, 160 + 18 * p, y + 64], fill=ACCENT)
        text_c(d, (200, y), f"{k} = {v!r}", F(F_MONO, 40), (206, 202, 200), "lm")
        text_c(d, (980, y), desc, F(F_SANS, 36), (150, 146, 142), "lm")

    # 判定结果
    rp = out_cubic(progress(u, 1.5, 0.5))
    if rp > 0:
        yy = 720
        bar(d, 160, yy, 160 + 1500 * rp, yy + 150,
            (int(24 * rp), int(18 * rp), int(20 * rp)), 14)
        if rp > 0.6:
            text_c(d, (200, yy + 45), "→  前提成立", F(F_SANS_BD, 44), (150, 200, 160), "lm")
            text_c(d, (200, yy + 108), "事件按史载发生，记为「应验」",
                   F(F_SANS, 34), (160, 170, 164), "lm")

    # 分叉箭头
    fp = out_cubic(progress(u, 2.2, 0.6))
    if fp > 0:
        x0, y0b = 1200, 700
        d.line([(x0, y0b + 40), (x0 + 240 * fp, y0b + 40 - 120 * fp)], fill=ACCENT_SOFT, width=4)
        d.line([(x0, y0b + 40), (x0 + 240 * fp, y0b + 40 + 120 * fp)], fill=ACCENT_SOFT, width=4)
        text_c(d, (x0 + 320, y0b - 80), "前提被改", F(F_SANS, 34), (200, 160, 164), "lm")
        text_c(d, (x0 + 320, y0b + 120), "记为「改道」", F(F_SANS, 34), (200, 160, 164), "lm")
    return img


def load_geo():
    dao = json.loads(GEO.read_text(encoding="utf-8"))["dao"]

    def rings(item):
        coords = item.get("coordinates") or []
        if item.get("type") == "Polygon":
            return coords if coords and isinstance(coords[0][0], list) else [coords]
        return [r for poly in coords for r in poly]

    lons, lats = [], []
    for item in dao.values():
        for ring in rings(item):
            for lon, lat in ring:
                lons.append(lon)
                lats.append(lat)
    return dao, rings, (min(lons), max(lons), min(lats), max(lats))


def seg_spotlight(u: float) -> Image.Image:
    """地图聚光：只照亮出事的地方。"""
    img = stage_background(u)
    d = ImageDraw.Draw(img)
    dao, rings, (min_lon, max_lon, min_lat, max_lat) = load_geo()

    # 镜头对准潼关一带：只给这一块，聚光才有意义
    cam_lon, cam_lat = 110.4, 35.2
    scale = min((W - 200) / (max_lon - min_lon), (H - 300) / (max_lat - min_lat)) * 1.55
    ox = W / 2 - (cam_lon - min_lon) * scale
    oy = H / 2 - (max_lat - cam_lat) * scale + 40

    def xy(lon, lat):
        return ox + (lon - min_lon) * scale, oy + (max_lat - lat) * scale

    focus = "tongguan"
    names = {
        "changan": "京兆", "lingwu": "灵武", "luoyang": "河南府", "suiyang": "睢阳",
        "fanyang": "范阳", "hebei_plain": "河北", "taiyuan": "太原", "tongguan": "潼关",
    }
    zoom = 1.0 + 0.05 * in_out(progress(u, 0, 2.6))
    for key, item in dao.items():
        on = key == focus
        fill = (26, 22, 22) if not on else (176, 72, 62)
        for ring in rings(item):
            pts = [xy(lon, lat) for lon, lat in ring]
            if len(pts) >= 3:
                d.polygon(pts, fill=fill, outline=(58, 34, 34))
        if on:
            for ring in rings(item):
                pts = [xy(lon, lat) for lon, lat in ring]
                if len(pts) >= 3:
                    d.line(pts + [pts[0]], fill=ACCENT, width=5)

    for key, item in dao.items():
        pts = [xy(lon, lat) for ring in rings(item) for lon, lat in ring]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        col = INK if key == focus else (88, 80, 78)
        text_c(d, (cx, cy), names[key], F(F_SERIF, 34), col)

    a = out_cubic(progress(u, 0.3, 0.5))
    text_c(d, (140, 150), "地图只照亮出事的地方", F(F_SANS_BD, 52),
           (int(INK[0] * a), int(INK[1] * a), int(INK[2] * a)), "lm")
    b = out_cubic(progress(u, 0.9, 0.5))
    text_c(d, (140, 210), "潼关失守，长安门户洞开", F(F_SANS, 34),
           (int(170 * b), int(120 * b), int(120 * b)), "lm")
    return img


def seg_decision(u: float) -> Image.Image:
    """奏疏浮层：三个选项，各带代价。"""
    img = stage_background(u)
    d = ImageDraw.Draw(img)

    cw, ch = 1080, 600
    cx, cy = (W - cw) / 2, (H - ch) / 2
    p = out_cubic(progress(u, 0, 0.45))
    dy = (1 - p) * 60
    bar(d, cx, cy + dy, cx + cw, cy + ch + dy, (22, 18, 20), 18)
    d.rectangle([cx, cy + dy, cx + cw, cy + dy + 3], fill=ACCENT)

    text_c(d, (cx + 48, cy + 56 + dy), "奏", F(F_SERIF, 44), ACCENT, "lm")
    text_c(d, (cx + 120, cy + 56 + dy), "催哥舒翰出战", F(F_SANS_BD, 56), INK, "lm")
    text_c(d, (cx + 48, cy + 130 + dy), "756-07-01 · 唐廷", F(F_SANS, 28), MUTED, "lm")

    text_c(d, (cx + 48, cy + 196 + dy),
           "守则利在坚守，出则关中必危", F(F_SANS, 34), (196, 190, 186), "lm")

    opts = [
        ("遣使催战", "按史载：潼关失守，长安门户洞开"),
        ("令其坚守", "府库 −40 万贯；潼关不失"),
        ("换将出战", "临阵易帅，军心动摇"),
    ]
    for i, (name, note) in enumerate(opts):
        op = out_cubic(progress(u, 0.14 + i * 0.16, 0.3))
        if op <= 0:
            continue
        y = cy + 270 + i * 108 + dy
        hi = i == 1
        bar(d, cx + 48, y, cx + cw - 48, y + 88,
            (38, 30, 32) if hi else (30, 25, 27), 12)
        if hi:
            d.rounded_rectangle([cx + 48, y, cx + cw - 48, y + 88], radius=12,
                                outline=ACCENT, width=3)
        text_c(d, (cx + 80, y + 30), name, F(F_SANS_BD, 36), INK, "lm")
        text_c(d, (cx + 80, y + 64), note, F(F_SANS, 24), MUTED, "lm")
    return img


def seg_score(u: float) -> Image.Image:
    """八年结局：六项评分条。"""
    img = stage_background(u)
    d = ImageDraw.Draw(img)
    a = out_cubic(progress(u, 0, 0.4))
    text_c(d, (150, 140), "八年之后：克复 75.4", F(F_SANS_BD, 60),
           (int(INK[0] * a), int(INK[1] * a), int(INK[2] * a)), "lm")
    text_c(d, (150, 208), "赢了战争，输了河北", F(F_SANS, 34),
           (int(190 * a), int(120 * a), int(120 * a)), "lm")

    items = [
        ("两京", 1.00, 0.20), ("乱平", 1.00, 0.20), ("河北", 0.40, 0.20),
        ("府库", 0.70, 0.12), ("威望", 0.52, 0.15), ("民心", 0.86, 0.13),
    ]
    y0 = 330
    for i, (name, v, wgt) in enumerate(items):
        p = in_out(progress(u, 0.3 + i * 0.16, 0.7))
        y = y0 + i * 96
        text_c(d, (150, y), name, F(F_SANS, 38), (200, 194, 190), "lm")
        bx0, bx1 = 320, 1400
        d.rectangle([bx0, y - 16, bx1, y + 16], fill=(30, 24, 26))
        fill_w = (bx1 - bx0) * v * p
        col = ACCENT if name == "河北" else (150, 60, 70)
        d.rectangle([bx0, y - 16, bx0 + fill_w, y + 16], fill=col)
        text_c(d, (bx0 + fill_w + 24, y), f"{v * 100:.0f}", F(F_MONO, 34), INK, "lm")
        text_c(d, (1560, y), f"权重 {wgt:.2f}", F(F_SANS, 28), (120, 112, 110), "lm")
    return img


def seg_terminal(u: float) -> Image.Image:
    """命令行：一条命令跑完全部检查。"""
    img = stage_background(u)
    d = ImageDraw.Draw(img)
    x0, y0 = 220, 220
    bw, bh = W - 440, 620
    bar(d, x0, y0, x0 + bw, y0 + bh, (14, 13, 14), 14)
    d.rectangle([x0, y0, x0 + bw, y0 + 46], fill=(26, 22, 24))
    for i, c in enumerate([(200, 60, 60), (200, 160, 60), (110, 180, 110)]):
        d.ellipse([x0 + 26 + i * 30, y0 + 16, x0 + 42 + i * 30, y0 + 32], fill=c)
    text_c(d, (x0 + bw / 2, y0 + 23), "powershell", F(F_SANS, 22), (140, 134, 132))

    lines = [
        ("> python tools/ci.py", INK, 0.15),
        ("==> 后端测试        178 passed", (150, 200, 150), 0.55),
        ("==> 史料数据完整性   21 件 / 7 岔路口", (150, 200, 150), 0.95),
        ("==> 前端构建         built in 717ms", (150, 200, 150), 1.35),
        ("==> 渲染冒烟         桌面 56 项 / 窄屏 12 项", (150, 200, 150), 1.75),
        ("==> 发布包自检       解压后一键启动可用", (150, 200, 150), 2.15),
        ("", INK, 2.45),
        ("✓ 全部通过", (200, 190, 120), 2.5),
    ]
    for i, (line, col, start) in enumerate(lines):
        shown = typewriter(line, u, start, 40)
        if not shown:
            continue
        fnt = F(F_MONO, 32) if line.isascii() else F(F_SANS, 30)
        text_c(d, (x0 + 46, y0 + 96 + i * 62), shown, fnt, col, "lm")
        if shown == line and line.endswith("通过"):
            d.rectangle([x0 + 40, y0 + 96 + i * 62 - 22,
                         x0 + 40 + 10, y0 + 96 + i * 62 + 22], fill=ACCENT)
    return img


SEGMENTS = [seg_conditions, seg_spotlight, seg_decision, seg_score, seg_terminal]


def scene_ending(u: float) -> Image.Image:
    img = stage_background(u, pulse=max(0.0, 1 - u))
    d = ImageDraw.Draw(img)
    a = out_cubic(progress(u, 0.1, 0.6))
    text_c(d, (W / 2, H * 0.38), "WorldBranch", F(F_DISPLAY, 130),
           (int(INK[0] * a), int(INK[1] * a), int(INK[2] * a)))
    text_c(d, (W / 2, H * 0.38 + 110), "唐 史 推 演 器", F(F_SERIF, 52),
           (int(MUTED[0] * a), int(MUTED[1] * a), int(MUTED[2] * a)))
    b = out_cubic(progress(u, 0.7, 0.6))
    if b > 0:
        text_c(d, (W / 2, H * 0.38 + 220), "git clone 后双击 start.bat",
               F(F_SANS, 38), (int(200 * b), int(196 * b), int(192 * b)))
        text_c(d, (W / 2, H * 0.38 + 280), "不需要数据库 · 不需要联网 · MIT",
               F(F_SANS, 30), (int(140 * b), int(134 * b), int(132 * b)))
    c = out_expo(progress(u, 1.4, 0.5))
    if c > 0:
        half = 300 * c
        d.line([(W / 2 - half, H * 0.38 + 340), (W / 2 + half, H * 0.38 + 340)],
               fill=ACCENT, width=3)
    return img


# ---------------- 时间线 ----------------
OPENING = 6.0
ROUND = 4.0
CARD = 1.0
ENDING = 5.0
N = len(CARDS)                       # 5 轮
TOTAL = OPENING + N * ROUND + ENDING  # 6 + 20 + 5 = 31s


def frame_at(t: float) -> Image.Image:
    if t < OPENING:
        img = scene_opening(t)
    elif t < OPENING + N * ROUND:
        rel = t - OPENING
        rnd = int(rel // ROUND)
        u = rel - rnd * ROUND
        if u < CARD:
            img = scene_bigcard(rnd, u)
        else:
            img = SEGMENTS[rnd](u - CARD)
    else:
        img = scene_ending(t - (OPENING + N * ROUND))
    return grain(img, t)


# ---------------- 音频 ----------------
def synth_audio(path: Path) -> None:
    """120 BPM / A 小调：底鼓 + 八分音符 hat + 每小节和弦垫 + 段落扫频 + 结尾长音。"""
    sr = 48000
    n = int(TOTAL * sr)
    mix = np.zeros((n, 2), dtype=np.float32)
    tt = np.arange(n) / sr

    def add(sig: np.ndarray, start: float) -> None:
        i = int(start * sr)
        j = min(n, i + len(sig))
        if i < n:
            mix[i:j, 0] += sig[: j - i]
            mix[i:j, 1] += sig[: j - i]

    def env(length: float, attack: float, decay: float) -> np.ndarray:
        x = np.arange(int(length * sr)) / sr
        a = np.clip(x / max(attack, 1e-4), 0, 1)
        return (a * np.exp(-x / max(decay, 1e-4))).astype(np.float32)

    # 底鼓：每拍
    kicks = int(TOTAL / BEAT)
    for k in range(kicks):
        t0 = k * BEAT
        dur = 0.28
        x = np.arange(int(dur * sr)) / sr
        f = 120 * np.exp(-x * 26) + 42
        sig = np.sin(2 * np.pi * np.cumsum(f) / sr) * env(dur, 0.002, 0.10)
        add(0.9 * sig, t0)

    # hat：八分音符，弱
    eighths = int(TOTAL / (BEAT / 2))
    rng = np.random.default_rng(7)
    for k in range(eighths):
        t0 = k * (BEAT / 2)
        dur = 0.05
        sig = (rng.standard_normal(int(dur * sr)) * env(dur, 0.001, 0.012)).astype(np.float32)
        add(0.12 * sig, t0)

    # 和弦垫：每 2 秒一个（A小调 i–VI–III–VII）
    chords = [
        [220.00, 261.63, 329.63],  # Am
        [174.61, 220.00, 261.63],  # F
        [261.63, 329.63, 392.00],  # C
        [196.00, 246.94, 293.66],  # G
    ]
    bars = int(TOTAL / 2) + 1
    for b in range(bars):
        t0 = b * 2.0
        dur = 2.0
        x = np.arange(int(dur * sr)) / sr
        fade = np.minimum(1, x / 0.25) * np.minimum(1, (dur - x) / 0.35)
        sig = np.zeros_like(x)
        for f in chords[b % len(chords)]:
            sig += np.sin(2 * np.pi * f * x) * 0.10
            sig += np.sin(2 * np.pi * f * 2 * x) * 0.03
        add((sig * fade).astype(np.float32), t0)

    # 段落切换扫频（每次轮到风格段开始）
    for r in range(N):
        t0 = OPENING + r * ROUND + CARD
        dur = 0.9
        x = np.arange(int(dur * sr)) / sr
        f = np.linspace(180, 1400, len(x))
        sig = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-x * 3.2) * 0.22
        add(sig.astype(np.float32), t0)

    # 大字卡重音
    for r in range(N):
        t0 = OPENING + r * ROUND
        dur = 0.5
        x = np.arange(int(dur * sr)) / sr
        sig = np.sin(2 * np.pi * 880 * x) * np.exp(-x * 9) * 0.16
        add(sig.astype(np.float32), t0)

    # 结尾长音
    dur = ENDING
    x = np.arange(int(dur * sr)) / sr
    fade = np.minimum(1, x / 0.4) * np.exp(-x * 0.6)
    tail = (np.sin(2 * np.pi * 110 * x) + 0.5 * np.sin(2 * np.pi * 220 * x)) * 0.18 * fade
    add(tail.astype(np.float32), OPENING + N * ROUND)

    peak = float(np.max(np.abs(mix))) or 1.0
    mix = (mix / peak) * 0.89

    import wave

    pcm = (mix * 32767).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# ---------------- 编码 ----------------
def ffmpeg_bin() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-only", action="store_true")
    ap.add_argument("--stills", action="store_true")
    args = ap.parse_args()

    frames_dir = WORK / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    total_frames = int(round(TOTAL * FPS))

    if args.stills:
        picks = [1.2, 7.0, 9.5, 12.0, 15.5, 19.0, 22.5, 27.0, 29.5]
        for i, t in enumerate(picks):
            frame_at(t).save(WORK / f"still-{i:02d}.png")
            print(f"  still {i:02d} t={t}")
        return 0

    print(f"渲染 {total_frames} 帧（{TOTAL:.1f}s @ {FPS}fps）…")
    for i in range(total_frames):
        frame_at(i / FPS).save(frames_dir / f"{i:05d}.png")
        if i % 150 == 0:
            print(f"  {i}/{total_frames}", flush=True)

    wav = WORK / "score.wav"
    print("合成配乐…")
    synth_audio(wav)

    if args.frames_only:
        print(f"帧与音频已就绪：{frames_dir} / {wav}")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    mp4 = OUT / "worldbranch-promo.mp4"
    ff = ffmpeg_bin()
    cmd = [
        ff, "-y",
        "-framerate", str(FPS),
        "-i", str(frames_dir / "%05d.png"),
        "-i", str(wav),
        "-c:v", "libx264", "-preset", "slow", "-crf", "20",
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart",
        str(mp4),
    ]
    print("编码中…")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stderr[-1500:])
        return 1
    print(f"成片：{mp4}  {mp4.stat().st_size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())