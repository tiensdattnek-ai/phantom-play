from __future__ import annotations

import math
import time
from PIL import Image, ImageDraw, ImageFont


class DemoScene:
    """Synthetic screen used by --demo. It never captures or controls the real OS."""

    def __init__(self, width: int, height: int):
        self.w = width
        self.h = height
        self.font = self._font(28)
        self.small = self._font(16)
        self.tiny = self._font(13)
        self.bg = self._background()

    def _font(self, size: int):
        for name in ("DejaVuSans.ttf", "Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _background(self) -> Image.Image:
        im = Image.new("RGB", (self.w, self.h), "#0a0e14")
        d = ImageDraw.Draw(im)
        for y in range(self.h):
            k = y / max(1, self.h)
            r = int(8 + 8 * k)
            g = int(12 + 18 * k)
            b = int(20 + 30 * k)
            d.line([(0, y), (self.w, y)], fill=(r, g, b))
        step = max(32, self.w // 24)
        for x in range(0, self.w, step):
            d.line([(x, 0), (x, self.h)], fill=(24, 36, 50))
        for y in range(0, self.h, step):
            d.line([(0, y), (self.w, y)], fill=(24, 36, 50))
        return im

    def render(self, t: float, cursor=None, keys=None, gamepad=None) -> bytes:
        im = self.bg.copy()
        d = ImageDraw.Draw(im, "RGBA")
        w, h = self.w, self.h
        # Moving glow orbs.
        for i, color in enumerate(((94, 234, 212), (34, 211, 238), (245, 158, 11))):
            x = w * (0.5 + 0.32 * math.sin(t * 0.7 + i * 2.1))
            y = h * (0.45 + 0.25 * math.cos(t * 0.9 + i * 1.7))
            r = int(min(w, h) * (0.10 + 0.03 * math.sin(t + i)))
            for k in range(6, 0, -1):
                rr = r * k / 6
                alpha = int(10 + 8 * (6 - k))
                d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(*color, alpha))
        # Fake desktop window.
        pad = int(w * 0.06)
        top = int(h * 0.16)
        d.rounded_rectangle([pad, top, w - pad, h - top], radius=18, fill=(13, 20, 30, 235), outline=(56, 80, 100, 255), width=2)
        d.text((pad + 24, top + 20), "PHANTOMPLAY  /  DEMO SCREEN", font=self.font, fill="#e6f1ff")
        d.text((pad + 24, top + 62), "Màn hình giả lập an toàn — input không chạm máy thật.", font=self.small, fill="#94a3b8")
        d.text((pad + 24, top + 92), f"Render {time.strftime('%H:%M:%S')}  •  {w}x{h}", font=self.small, fill="#5eead4")
        # HUD bars.
        bx, by = pad + 24, top + 140
        for i, label in enumerate(("GPU", "NET", "DEC")):
            val = 0.35 + 0.3 * math.sin(t * 1.3 + i)
            d.text((bx, by + i * 34), label, font=self.tiny, fill="#94a3b8")
            d.rounded_rectangle([bx + 50, by + i * 34 + 4, bx + 350, by + i * 34 + 16], radius=6, fill=(30, 41, 59))
            d.rounded_rectangle([bx + 50, by + i * 34 + 4, bx + 50 + int(300 * val), by + i * 34 + 16], radius=6, fill=(94, 234, 212))
        if keys:
            chips = list(keys)[-8:]
            x = pad + 24
            y = h - top - 60
            for code in chips:
                tw = int(d.textlength(code, font=self.tiny)) + 18
                d.rounded_rectangle([x, y, x + tw, y + 26], radius=6, fill=(34, 211, 238, 70), outline=(34, 211, 238, 180))
                d.text((x + 9, y + 5), code, font=self.tiny, fill="#e0f2fe")
                x += tw + 8
        # Cursor from demo input, or autonomous path.
        if cursor is not None:
            cx, cy = cursor[0] * w, cursor[1] * h
        else:
            cx, cy = w * (0.5 + 0.25 * math.sin(t)), h * (0.5 + 0.2 * math.cos(t * 1.2))
        d.polygon([(cx, cy), (cx, cy + 22), (cx + 6, cy + 17), (cx + 11, cy + 27), (cx + 15, cy + 25), (cx + 10, cy + 15), (cx + 18, cy + 15)], fill="#ffffff", outline="#0f172a")
        d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], outline=(94, 234, 212, 160), width=2)
        return im.tobytes()
