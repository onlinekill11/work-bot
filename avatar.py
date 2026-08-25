"""Генератор аватарки для бота WORK -> avatar.png (512x512)."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SIZE = 512
SS = 4  # суперсэмплинг для гладких краёв
BASE = SIZE * SS

BG_TOP = (23, 32, 48)
BG_BOTTOM = (9, 12, 19)
RING_BG = (32, 43, 61)
ACCENT = (34, 197, 94)
ACCENT_SOFT = (74, 222, 128)
WHITE = (243, 247, 252)

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\ariblk.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _gradient(w: int, h: int) -> Image.Image:
    grad = Image.new("RGB", (1, h))
    px = grad.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(
            int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)
        )
    return grad.resize((w, h))


def _arc(draw: ImageDraw.ImageDraw, box, start: float, end: float, width: int, color) -> None:
    draw.arc(box, start, end, fill=color, width=width)
    # закруглённые концы
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    r = (box[2] - box[0]) / 2 - width / 2
    for angle in (start, end):
        a = math.radians(angle)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        draw.ellipse(
            [x - width / 2, y - width / 2, x + width / 2, y + width / 2], fill=color
        )


def build(path: Path) -> Path:
    img = _gradient(BASE, BASE)
    draw = ImageDraw.Draw(img)

    # мягкое свечение сверху
    glow = Image.new("RGB", (BASE, BASE), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse(
        [BASE * 0.05, -BASE * 0.35, BASE * 0.95, BASE * 0.55], fill=(18, 42, 30)
    )
    glow = glow.filter(ImageFilter.GaussianBlur(BASE // 12))
    img = Image.blend(img, Image.blend(img, glow, 0.0), 0.0)
    img = Image.composite(
        Image.blend(img, glow, 0.55), img, Image.new("L", (BASE, BASE), 90)
    )
    draw = ImageDraw.Draw(img)

    # кольцо-таймер
    pad = int(BASE * 0.10)
    box = [pad, pad, BASE - pad, BASE - pad]
    ring_w = int(BASE * 0.055)
    draw.ellipse(box, outline=RING_BG, width=ring_w)
    _arc(draw, box, -95, 205, ring_w, ACCENT)
    _arc(draw, box, -95, -10, ring_w, ACCENT_SOFT)

    # деления по кругу (как часовые метки)
    cx = cy = BASE / 2
    r_out = (BASE - 2 * pad) / 2 - ring_w * 1.65
    r_in = r_out - BASE * 0.022
    for i in range(12):
        a = math.radians(-90 + i * 30)
        x1, y1 = cx + r_in * math.cos(a), cy + r_in * math.sin(a)
        x2, y2 = cx + r_out * math.cos(a), cy + r_out * math.sin(a)
        draw.line([x1, y1, x2, y2], fill=(58, 76, 100), width=int(BASE * 0.008))

    # буква W
    font = _font(int(BASE * 0.36))
    text = "W"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = cx - tw / 2 - bbox[0]
    ty = cy - th / 2 - bbox[1] - BASE * 0.055
    draw.text((tx + BASE * 0.006, ty + BASE * 0.008), text, font=font, fill=(6, 10, 16))
    draw.text((tx, ty), text, font=font, fill=WHITE)

    # подпись WORK
    sub_font = _font(int(BASE * 0.085))
    sub = "W O R K"
    sb = draw.textbbox((0, 0), sub, font=sub_font)
    draw.text(
        (cx - (sb[2] - sb[0]) / 2 - sb[0], cy + BASE * 0.135),
        sub,
        font=sub_font,
        fill=ACCENT_SOFT,
    )

    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    img.save(path, "PNG")
    return path


if __name__ == "__main__":
    out = build(Path(__file__).resolve().parent / "avatar.png")
    print(f"Аватарка готова: {out}")
