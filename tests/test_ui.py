# -*- coding: utf-8 -*-
"""自绘面板的可测部分：布局、命中区、点击语义、渲染产物。

Tk 窗口本身需要真实桌面会话才能点，这里直接驱动 ControlPanel 的状态机：
  * `_measure()` 给出的高度必须装得下所有区块（footer 被裁过一次，设了回归）
  * 每个可点区域都要在 `_hits` 里，且不重叠到别人的动作上
  * `_on_release()` 必须把正确命令投进 app.post()
  * `render_preview()` 能离线出一张 PNG（README/文档用的那张）
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jellyicons import ui  # noqa: E402

MODES = [
    ("jelly", "律动", "overlay"),
    ("free", "自由", "takeover"),
    ("kun", "两年半", "takeover"),
    ("heart", "心动", "takeover"),
    ("bands", "音浪", "overlay"),
    ("wave", "海浪", "takeover"),
    ("ring", "星环", "takeover"),
    ("firework", "烟花", "overlay"),
    ("spell", "拼字", "takeover"),
    ("ball", "弹球", "takeover"),
    ("gravity", "鼠标引力", "takeover"),
    ("lens", "放大镜", "takeover"),
    ("domino", "多米诺", "overlay"),
    ("breath", "呼吸", "overlay"),
]


def _snap(**kw):
    base = dict(
        version="1.8.0", mode="jelly", mode_title="律动", engine="overlay",
        hidden=False, icons=38, fps=60, audio_ok=True, auto=True,
        device="耳机 (Senary Audio) [Loopback]", bands=[0.3] * 64,
        bass=0.3, presence=0.3, mode_count=14, gain=1.0,
        hotkeys=["Ctrl+Alt+F9  退出"], )
    base.update(kw)
    return base


class _FakeApp:
    mode_list = MODES

    def __init__(self, snap=None):
        self._snap = snap or _snap()
        self.posted = []

    def snapshot(self):
        return self._snap

    def post(self, cmd):
        self.posted.append(cmd)


def _render(panel, snap):
    """跑一遍完整绘制，返回 (hits, height)。"""
    from PIL import ImageDraw

    hits = []
    height = panel._measure(snap)
    img = ui._paint_bg((ui.WIDTH, height))
    d = ImageDraw.Draw(img)
    y = panel._draw_sections(d, snap, hits)
    return hits, height, y


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.app = _FakeApp()
        self.panel = ui.ControlPanel(self.app)

    def test_height_fits_every_section(self):
        """高度必须真的装下所有区块（footer 热键行曾被裁掉）。"""
        for kw in ({}, {"mode_count": 14}, {"mode_count": 4},
                   {"mode_count": 12}):
            with self.subTest(**kw):
                snap = _snap(**kw)
                hits, height, y_end = _render(self.panel, snap)
                self.assertGreaterEqual(
                    height, y_end, "%r 时画到 %d 但窗口只有 %d"
                    % (kw, y_end, height))
                for x0, y0, x1, y1, action in hits:
                    self.assertLessEqual(
                        y1, height, "%s 超出窗口下沿" % action)

    def test_collapsed_is_short(self):
        self.panel._collapsed = True
        hits, height, _y = _render(self.panel, _snap())
        self.assertLess(height, 100)
        actions = [h[4] for h in hits]
        self.assertIn("expand", actions)
        self.assertNotIn("mode:jelly", actions)   # 折叠后不该还有模式按钮

    def test_hits_are_inside_canvas(self):
        hits, height, _y = _render(self.panel, _snap())
        for x0, y0, x1, y1, action in hits:
            self.assertGreaterEqual(x0, 0, action)
            self.assertGreaterEqual(y0, 0, action)
            self.assertLessEqual(x1, ui.WIDTH, action)
            self.assertLessEqual(y1, height, action)


class HitTests(unittest.TestCase):
    def setUp(self):
        self.app = _FakeApp()
        self.panel = ui.ControlPanel(self.app)
        hits, _h, _y = _render(self.panel, self.app.snapshot())
        self.panel._hits = hits

    def _center(self, action):
        for x0, y0, x1, y1, name in self.panel._hits:
            if name == action:
                return (x0 + x1) // 2, (y0 + y1) // 2
        raise AssertionError("命中表里没有 %r" % action)

    def test_every_mode_button_is_clickable(self):
        for name, _title, _engine in MODES:
            x, y = self._center("mode:" + name)
            self.assertEqual(self.panel._hit(x, y), "mode:" + name)

    def test_click_mode_posts_select(self):
        x, y = self._center("mode:ring")
        self.panel._on_release(type("E", (), {"x": x, "y": y})())
        self.assertEqual(self.app.posted, [{"type": "select_mode",
                                            "name": "ring"}])

    def test_click_auto_posts_toggle(self):
        x, y = self._center("auto")
        self.panel._on_release(type("E", (), {"x": x, "y": y})())
        self.assertEqual(self.app.posted, [{"type": "toggle_auto"}])

    def test_click_quit_posts_quit(self):
        x, y = self._center("quit")
        self.panel._on_release(type("E", (), {"x": x, "y": y})())
        self.assertEqual(self.app.posted, [{"type": "quit"}])

    def test_click_outside_does_nothing(self):
        self.panel._on_release(type("E", (), {"x": 2, "y": 2})())
        self.assertEqual(self.app.posted, [])

    def test_release_after_drag_is_not_a_click(self):
        """拖动窗口后松手不能当成点击（否则拖一下就把面板关了）。"""
        x, y = self._center("quit")
        self.panel._on_press(type("E", (), {"x": x, "y": y,
                                            "x_root": 0, "y_root": 0})())
        self.panel._drag = (0, 0, 100, 100)
        self.panel._on_release(type("E", (), {"x": x, "y": y})())
        self.assertEqual(self.app.posted, [])

    def test_drag_region_covers_titlebar(self):
        x, y = self._center("drag")
        self.assertGreater(y, 0)
        self.assertLess(y, ui.ControlPanel.HEADER_H)

    # ---- Q 弹程度滑块 ----

    def test_gain_row_hit_exists(self):
        self._center("gain")   # 找不到会 AssertionError

    def test_click_gain_posts_set_gain(self):
        from jellyicons import settings
        x, y = self._center("gain")
        self.panel._on_release(type("E", (), {"x": x, "y": y})())
        self.assertEqual(len(self.app.posted), 1)
        cmd = self.app.posted[0]
        self.assertEqual(cmd["type"], "set_gain")
        # 点在轨道中点，倍率应落在区间中部
        mid = (settings.GAIN_MIN + settings.GAIN_MAX) / 2.0
        self.assertAlmostEqual(cmd["value"], mid, delta=0.15)

    def test_gain_at_maps_ends(self):
        from jellyicons import settings
        self.panel._render_for_test = True
        _hits, _h, _y = _render(self.panel, _snap())
        self.panel._hits = _hits
        tx0, tx1 = self.panel._gain_track[0], self.panel._gain_track[1]
        self.assertAlmostEqual(self.panel._gain_at(tx0), settings.GAIN_MIN,
                               places=5)
        self.assertAlmostEqual(self.panel._gain_at(tx1), settings.GAIN_MAX,
                               places=5)
        # 越界点击夹到区间端点，不能跑出 GAIN_MIN..GAIN_MAX
        self.assertAlmostEqual(self.panel._gain_at(tx0 - 500),
                               settings.GAIN_MIN, places=5)
        self.assertAlmostEqual(self.panel._gain_at(tx1 + 500),
                               settings.GAIN_MAX, places=5)

    def test_gain_row_shows_current_value(self):
        """快照里的 gain 必须被画出来（否则拖完看不出变化）。"""
        panel = ui.ControlPanel(_FakeApp())
        for value in (0.3, 1.0, 1.45, 2.0):
            with self.subTest(gain=value):
                hits, _h, _y = _render(panel, _snap(gain=value))
                self.assertTrue(any(h[4] == "gain" for h in hits))
                self.assertIsNotNone(panel._gain_track)


class WaveTests(unittest.TestCase):
    def test_peak_hold_decays(self):
        """波形峰值保持：掉得比上升慢，否则看起来像噪声。"""
        panel = ui.ControlPanel(_FakeApp())
        panel._peaks = [1.0] * 64
        _hits, _h, _y = _render(panel, _snap(bands=[0.0] * 64))
        self.assertLess(panel._peaks[0], 1.0)
        self.assertGreater(panel._peaks[0], 0.9)

    def test_survives_wrong_band_count(self):
        """频段数不是 64、或者干脆没有，都必须画得出来。"""
        panel = ui.ControlPanel(_FakeApp())
        for bands in ([], [0.5] * 8, [0.2] * 200, None):
            with self.subTest(bands=bands):
                _hits, height, _y = _render(panel, _snap(bands=bands))
                self.assertGreater(height, 0)


class PreviewTests(unittest.TestCase):
    def test_render_preview_writes_png(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "p.png")
            ui.render_preview(out, _snap(), MODES)
            self.assertTrue(os.path.exists(out))
            from PIL import Image
            with Image.open(out) as im:
                self.assertEqual(im.size, (ui.WIDTH, ui.ControlPanel(_FakeApp())
                                           ._measure(_snap())))

    def test_palette_contrast(self):
        """文字和底色的亮度差要够，否则暗色面板看不清。"""
        def lum(c):
            r, g, b = [v / 255.0 for v in c]
            return 0.2126 * r + 0.7152 * g + 0.0722 * b
        self.assertGreater(lum(ui.TEXT) - lum(ui.BG_TOP), 0.5)
        self.assertGreater(lum(ui.ACCENT) - lum(ui.BG_TOP), 0.3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
