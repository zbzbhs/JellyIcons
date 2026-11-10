# -*- coding: utf-8 -*-
"""生成 exe 图标：一颗被压扁又弹起的方块（和面板强调色一致）。

纯 PIL 画，不依赖外部素材，多尺寸一起写进同一个 .ico。
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

ACCENT = (75, 214, 160)
ACCENT_DARK = (30, 104, 78)
BASE = (17, 20, 26)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets",
                   "jellyicons.ico")
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _draw(size: int) -> Image.Image:
    """按尺寸画一张：s 超采样 4 倍再缩，边缘才不毛。"""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(s * 0.06)
    d.rounded_rectangle([pad, pad, s - pad - 1, s - pad - 1],
                        radius=int(s * 0.22), fill=BASE + (255,))
    # 三颗并排的方块：中间那颗被压扁拉宽 —— 就是产品要表达的那一下
    cx = s // 2
    gap = int(s * 0.045)
    w = int(s * 0.20)
    h = int(s * 0.30)
    for dx, sq in ((-1, 1.0), (0, 0.72), (1, 1.0)):
        bw = int(w * (1.0 if dx == 0 else 0.86))
        bh = int(h * sq)
        x0 = cx + dx * (w + gap) - bw // 2
        y1 = int(s * 0.76)
        y0 = y1 - bh
        color = ACCENT if dx == 0 else ACCENT_DARK
        d.rounded_rectangle([x0, y0, x0 + bw, y1],
                            radius=int(bw * 0.24), fill=color + (255,))
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    frames = [_draw(n) for n in SIZES]
    frames[-1].save(OUT, format="ICO",
                    sizes=[(n, n) for n in SIZES])
    print("[icon] 已生成 %s (%d 字节, 尺寸 %s)"
          % (OUT, os.path.getsize(OUT), ",".join(str(n) for n in SIZES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
