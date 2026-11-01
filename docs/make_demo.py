# -*- coding: utf-8 -*-
"""生成 README 用的演示 GIF（docs/demo.gif）。

不用真实桌面：拿 Shell 取到的真实图标位图，喂一段合成的低频节拍到
真实的 ActivityDetector + JellyState，按 app.py 的固定画布/底部中心
锚点几何渲染每一帧。所以 GIF 里看到的形变就是程序实际会做的形变。

    python -X utf8 docs/make_demo.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

from jellyicons import config, jelly, shell_icons
from jellyicons.activity import ActivityDetector

W, H = 560, 260
FPS = 30
SECONDS = 5.0
LEAD_IN = 0.6
BG_TOP = (24, 32, 48)
BG_BOTTOM = (12, 16, 26)
ICONS = ["此电脑", "回收站", "下载", "音乐"]
SIDE = 72


def _background():
    img = Image.new("RGB", (W, H), BG_TOP)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        d.line(
            [(0, y), (W, y)],
            fill=(
                int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
                int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
                int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t),
            ),
        )
    return img


def _bands_for(t):
    """合成 64 段频谱：低频跟着 120BPM 的鼓点起伏，中高频给一点稳定底。

    前 LEAD_IN 秒静音，让观众先看到静息轮廓、再看到形变。
    """
    bands = [0.0] * 64
    if t < LEAD_IN:
        return bands
    t = t - LEAD_IN
    beat_period = 0.5
    phase = (t % beat_period) / beat_period
    # 每个鼓点一个指数衰减包络
    kick = math.exp(-phase * 7.0)
    for i in range(8):
        falloff = math.exp(-i * 0.55)
        bands[i] = 0.30 * kick * falloff + 0.02
    for i in range(8, 40):
        bands[i] = 0.012 + 0.006 * math.sin(t * 2.0 + i * 0.3)
    return bands


def main():
    cache = shell_icons.build_icon_cache(256)
    font, px = shell_icons.system_icon_font(config.TEXT_FONT_PX)

    items = []
    slot_w = W // len(ICONS)
    for idx, name in enumerate(ICONS):
        src = cache.get(name)
        if src is None:
            continue
        body = src.resize((SIDE, SIDE), Image.LANCZOS)
        label = shell_icons.render_label(name, font, slot_w - 12, config.TEXT_MAX_LINES)
        items.append({"name": name, "body": body, "label": label, "slot": idx})

    bg = _background()
    det = ActivityDetector()
    state = jelly.make_state(is_big=False)

    frames = []
    dt = 1.0 / FPS
    total = int(SECONDS * FPS)
    for n in range(total):
        t = n * dt
        bands = _bands_for(t)
        bass, _presence = det.update(bands, dt)
        sx, sy = state.step(bass * config.AGC_TO_VOL)

        frame = bg.copy()
        for it in items:
            body = it["body"]
            side = body.size[0]
            new_w = max(1, int(round(side * sx)))
            new_h = max(1, int(round(side * sy)))
            scaled = body.resize((new_w, new_h), Image.LANCZOS)

            cx = it["slot"] * slot_w + slot_w // 2
            bottom_y = 96 + side  # 本体底边（固定 baseline，不随缩放动）
            x = cx - new_w // 2
            y = bottom_y - new_h

            frame.paste(scaled, (x, y), scaled)

            label = it["label"]
            if label is not None:
                frame.paste(
                    label,
                    (cx - label.size[0] // 2, bottom_y + config.LABEL_GAP),
                    label,
                )
        frames.append(frame.convert("P", palette=Image.ADAPTIVE, colors=128))

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo.gif")
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=int(1000 / FPS),
        loop=0,
        optimize=True,
    )
    print("wrote %s (%d frames, %.1fs)" % (out, len(frames), SECONDS))


if __name__ == "__main__":
    main()
