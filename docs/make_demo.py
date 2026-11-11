# -*- coding: utf-8 -*-
"""生成 README 用的演示 GIF（docs/demo.gif 与 docs/modes.gif）。

不用真实桌面：拿 Shell 取到的真实图标位图，喂一段合成的 64 段频谱到
真实的 `ActivityDetector`，再用真实的模式类 + 真实的 `ModeSwitcher`
算出每个图标每一帧的 `Transform`，按 `app.py` 的固定画布 / 底部中心
锚点几何渲染。所以 GIF 里看到的形变就是程序实际会做的形变。

    python -X utf8 docs/make_demo.py          # 两个都生成
    python -X utf8 docs/make_demo.py jelly    # 只生成单模式版

为什么要两个 GIF：
    demo.gif   单看"律动"——能看清 Q 弹的形变细节（慢、大、清楚）。
    modes.gif  依次走 律动 → 音浪 → 烟花 → 心动 → 拼字 → 弹球 →
               鼠标引力 → 多米诺 → 呼吸，用真实的切换器与过渡，一次
               看到"两套引擎"的差别：overlay 档只缩放（原位），
               takeover 档会位移重排。
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

from jellyicons import config, jelly, shell_icons
from jellyicons.activity import ActivityDetector
from jellyicons.modes import ModeContext, Transform, create
from jellyicons.modes.switcher import ModeSwitcher

HERE = os.path.dirname(os.path.abspath(__file__))

BG_TOP = (24, 32, 48)
BG_BOTTOM = (12, 16, 26)


def background(w, h):
    img = Image.new("RGB", (w, h), BG_TOP)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line(
            [(0, y), (w, y)],
            fill=(
                int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
                int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
                int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t),
            ),
        )
    return img


def bands_for(t, lead_in=0.6, bpm=120.0):
    """合成 64 段频谱：低频跟着鼓点起伏，中高频给一点稳定底。"""
    bands = [0.0] * 64
    if t < lead_in:
        return bands
    t = t - lead_in
    beat = 60.0 / bpm
    phase = (t % beat) / beat
    kick = math.exp(-phase * 6.0)
    for i in range(8):
        bands[i] = 0.34 * kick * math.exp(-i * 0.5) + 0.02
    for i in range(8, 40):
        bands[i] = 0.012 + 0.007 * math.sin(t * 2.0 + i * 0.3)
    for i in range(40, 64):
        bands[i] = 0.004 + 0.003 * math.sin(t * 3.1 + i * 0.7)
    return bands


def _icon_set(w, rows, cols, names, side, top):
    """把真实图标位图摆成网格，返回绘制用的数据。"""
    cache = shell_icons.build_icon_cache(256)
    font, _px = shell_icons.system_icon_font(config.TEXT_FONT_PX)
    slot_w = w // cols
    slot_h = side + 34
    items = []
    picked = [n for n in names if n in cache]
    if not picked:                                   # 兜底：随便取几个
        picked = list(cache.keys())[:rows * cols]
    idx = 0
    for r in range(rows):
        for c in range(cols):
            if idx >= len(picked):
                break
            name = picked[idx]
            body = cache[name].resize((side, side), Image.LANCZOS)
            label = shell_icons.render_label(name, font, slot_w - 10,
                                             config.TEXT_MAX_LINES)
            cx = c * slot_w + slot_w // 2
            bottom = top + r * slot_h + side
            items.append({
                "key": "%s#%d" % (name, idx),
                "name": name,
                "body": body,
                "label": label,
                "cell": (cx - slot_w // 2, top + r * slot_h,
                         cx + slot_w // 2, top + r * slot_h + side + 30),
                "cx": cx,
                "bottom": bottom,
            })
            idx += 1
    return items


def _draw_frame(bg, items, transforms, shadow=False):
    frame = bg.copy()
    for it in items:
        tf = transforms.get(it["key"], Transform())
        if tf.alpha < 0.02:
            continue
        body = it["body"]
        side = body.size[0]
        new_w = max(1, int(round(side * tf.sx)))
        new_h = max(1, int(round(side * tf.sy)))
        scaled = body.resize((new_w, new_h), Image.LANCZOS)
        if tf.alpha < 0.999:
            a = scaled.getchannel("A").point(lambda v: int(v * tf.alpha))
            scaled.putalpha(a)
        cx = it["cx"] + tf.dx
        bottom = it["bottom"] + tf.dy
        x = int(round(cx - new_w / 2.0))
        y = int(round(bottom - new_h))

        if shadow:
            # 位移模式里加一条淡影，能看出"浮起来"的层次
            alpha = scaled.getchannel("A").point(lambda v: int(v * 0.18))
            dark = Image.new("RGBA", scaled.size, (0, 0, 0, 255))
            dark.putalpha(alpha)
            frame.paste(dark, (x + 4, y + 6), dark)

        frame.paste(scaled, (x, y), scaled)

        label = it["label"]
        if label is not None:
            frame.paste(label,
                        (int(round(cx - label.size[0] / 2.0)),
                         int(round(bottom + config.LABEL_GAP))),
                        label)
    return frame


def _save(frames, path, fps):
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=int(1000 / fps), loop=0, optimize=True)
    size = os.path.getsize(path) / 1024.0
    print("wrote %s (%d frames, %.0f KB)" % (path, len(frames), size))


def make_jelly(out_name="demo.gif"):
    """单模式特写：律动。慢、大、看得清形变。"""
    w, h, fps, seconds, lead = 560, 260, 30, 5.0, 0.6
    items = _icon_set(w, 1, 4, ["此电脑", "回收站", "下载", "音乐"], 72, 70)
    bg = background(w, h)
    det = ActivityDetector()
    state = jelly.make_state(is_big=False)

    frames = []
    dt = 1.0 / fps
    for n in range(int(seconds * fps)):
        t = n * dt
        bass, _p = det.update(bands_for(t, lead), dt)
        sx, sy = state.step(bass * config.AGC_TO_VOL)
        frames.append(_draw_frame(bg, items,
                                  {it["key"]: Transform(sx, sy) for it in items})
                      .convert("P", palette=Image.ADAPTIVE, colors=128))
    _save(frames, os.path.join(HERE, out_name), fps)


def _orbit(t, w, h):
    """给"鼠标引力/放大镜"造一个绕圈的光标轨迹。"""
    cx, cy = w * 0.5, h * 0.46
    r = min(w, h) * 0.30
    return (cx + r * math.cos(t * 1.15), cy + r * 0.62 * math.sin(t * 1.15))


def make_modes(out_name="modes.gif"):
    """多模式巡礼：走真实的切换器与过渡。"""
    w, h, fps = 520, 350, 16
    names = ["此电脑", "回收站", "下载", "音乐", "文档", "图片",
             "视频", "OneDrive", "控制面板", "记事本", "计算器", "画图"]
    items = _icon_set(w, 3, 4, names, 56, 56)
    bg = background(w, h)

    det = ActivityDetector()
    state = jelly.make_state(is_big=False)
    sw = ModeSwitcher(start="jelly", auto=False)
    # 手动排一段顺序：先用 dwell 短一点，让 GIF 里每个模式都能看清
    plan = [("jelly", 1.9), ("bands", 1.9), ("firework", 1.9),
            ("heart", 1.9), ("spell", 2.1), ("ball", 1.9),
            ("gravity", 1.9), ("domino", 1.9), ("breath", 1.9)]
    mode_titles = {n: create(n).title for n in sw.order}

    frames = []
    dt = 1.0 / fps
    label_font = None
    try:
        label_font = shell_icons.load_font(13)
    except Exception:
        pass

    for mode_name, dwell in plan:
        sw.select(mode_name)
        sw._elapsed = 0.0                     # 每个模式从 0 开始计时
        for n in range(int(dwell * fps)):
            t = n * dt
            bands = bands_for(t, 0.0, bpm=124.0)
            bass, presence = det.update(bands, dt)
            sx, sy = state.step(bass * config.AGC_TO_VOL)
            ctx = ModeContext(
                icons=[(it["key"], _Cell(it)) for it in items],
                bands=bands, bass=bass, presence=presence, jelly=state,
                screen=(w, h), now=t, pointer=_orbit(t, w, h))
            transforms, engine, _k = sw.tick(ctx, dt, active=True)
            transforms = {k: tf.clamp(engine, config.JELLY_MAX_W, 0.45)
                          for k, tf in transforms.items()}
            frame = _draw_frame(bg, items, transforms,
                                shadow=(engine == "takeover"))
            d = ImageDraw.Draw(frame)
            if label_font is not None:
                d.text((12, 10), "%s · %s" % (mode_titles[mode_name], engine),
                       fill=(150, 200, 255), font=label_font)
            frames.append(frame.convert("P", palette=Image.ADAPTIVE, colors=64))
    _save(frames, os.path.join(HERE, out_name), fps)


class _Cell:
    """模式只用到 rect / width / height / center()，这里给个最小实现。"""

    def __init__(self, it):
        self.key = it["key"]
        self.name = it["name"]
        self.rect = it["cell"]

    @property
    def width(self):
        return self.rect[2] - self.rect[0]

    @property
    def height(self):
        return self.rect[3] - self.rect[1]


def main(argv):
    which = argv[1] if len(argv) > 1 else "all"
    if which in ("all", "jelly"):
        make_jelly()
    if which in ("all", "modes"):
        make_modes()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
