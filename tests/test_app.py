# -*- coding: utf-8 -*-
"""App 同步 / 几何 / 帧跳过逻辑的进程内单测（不需要真实桌面）。"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jellyicons.app import App, SCALE_EPS, REST_SCALE_EPS  # noqa: E402
from jellyicons.desktop_reader import DesktopIcon  # noqa: E402
from jellyicons import config  # noqa: E402

from PIL import Image  # noqa: E402

_STUB_IMG = Image.new("RGBA", (256, 256), (255, 0, 0, 255))


class _FakeReader:
    def __init__(self, icons):
        self.icons = icons

    def snapshot(self):
        return list(self.icons)


class _FakeWin:
    """替掉 OverlayWindow：只记录 draw/hide/close，不建真实窗口。"""

    instances = []

    def __init__(self):
        self.drawn = []
        self.hidden = 0
        self.closed = False
        self._last_state = None
        _FakeWin.instances.append(self)

    def draw(self, img, x, y):
        self.drawn.append((x, y, img.size))

    def hide(self):
        self.hidden += 1

    def close(self):
        self.closed = True


def _patch_overlay(testcase):
    import jellyicons.app as app_mod
    orig = app_mod.OverlayWindow
    _FakeWin.instances = []
    app_mod.OverlayWindow = _FakeWin
    testcase.addCleanup(setattr, app_mod, "OverlayWindow", orig)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.app = App()
        self.app.icon_base = {"A": _STUB_IMG, "B": _STUB_IMG}
        self.app._side_est = 40

    def _fake_snapshot(self, icons):
        self.app.reader = _FakeReader(icons)

    def test_dedupe_same_names(self):
        """两个同名图标必须得到不同 key，各自独立 overlay。"""
        _patch_overlay(self)
        icons = [DesktopIcon("A", "A", (10, 10, 120, 79)),
                 DesktopIcon("A", "A", (10, 100, 120, 169))]
        self._fake_snapshot(icons)
        self.assertTrue(self.app._sync_overlays())
        self.assertEqual(len(self.app.overlays), 2)
        # key 编号必须与 build_icon_cache 一致：首个同名项用原名
        self.assertEqual(sorted(self.app.overlays), ["A", "A#1"])
        keys = list(self.app.overlays)
        self.assertNotEqual(keys[0], keys[1])
        # 二次同步：布局没变，不应重建窗口也不应重新绘制
        self.assertTrue(self.app._sync_overlays())
        self.assertEqual(len(self.app.overlays), 2)
        self.assertEqual(len(_FakeWin.instances), 2)

    def test_removal(self):
        _patch_overlay(self)
        icons = [DesktopIcon("A", "A", (10, 10, 120, 79)),
                 DesktopIcon("B", "B", (10, 100, 120, 169))]
        self._fake_snapshot(icons)
        self.app._sync_overlays()
        self.assertEqual(len(self.app.overlays), 2)
        self._fake_snapshot([icons[0]])
        self.app._sync_overlays()
        self.assertEqual(len(self.app.overlays), 1)
        self.assertIn("A", self.app.overlays)
        self.assertNotIn("B", self.app.overlays)
        self.assertTrue(_FakeWin.instances[1].closed)

    def test_side_recalibration_clears_cache(self):
        """图标尺寸变化（用户改 DPI/图标大小）应重建缩放缓存。"""
        self.app._side_est = 37
        self.app.icon_cache = {"A": "old", "B": "old"}
        icons = [DesktopIcon("A", "A", (10, 10, 120, 80))]  # cell_h=70
        self._fake_snapshot(icons)
        self.app._calibrate_side(icons)
        self.assertEqual(self.app._side_est, 38)  # 70*0.55=38.5 -> 38
        self.assertEqual(self.app.icon_cache, {})  # 被清空待重建
        self.app._ensure_screen_icons()
        self.assertEqual(self.app.icon_cache["A"].size, (38, 38))


class GeometryTests(unittest.TestCase):
    """固定画布：窗口坐标与缩放无关，横向锚点恒为格子中心。"""

    def setUp(self):
        self.app = App()
        self.app._side_est = 40
        self.app.icon_cache = {"A": Image.new("RGBA", (40, 40), (0, 255, 0, 255))}
        self.app.icon_base = {"A": _STUB_IMG}
        self.app._label_cache = {}
        self.app._label_font = None

    def _entry(self, rect=(100, 200, 200, 269)):
        icon = DesktopIcon("A", "A", rect)
        img = self.app.icon_cache["A"]
        label = self.app._get_label("A")
        geom = self.app._layout(icon, img, label)
        return {"icon": icon, "win": _FakeWin(), "geom": geom,
                "dirty": True, "ready": False, "_last_state": None}

    def test_canvas_independent_of_scale(self):
        """核心回归：sx 在 0.95~1.22 全区间变化，画布尺寸与窗口坐标必须完全不变。

        这正是 v1.2 "隐藏后图标左右乱动"的根因：旧实现用
        `x0 = cx - int(side*sx)//2` 算窗口 x，随 sx 抖 1~2px。
        """
        entry = self._entry()
        geom = entry["geom"]
        made = [self.app._compose(entry, sx, 1.0) for sx in
                (1.0, 1.02, 1.05, 1.0825, 1.10, 1.22, 0.95, 0.88)]
        xs = {m[1] for m in made}
        ys = {m[2] for m in made}
        sizes = {m[0].size for m in made}
        self.assertEqual(len(xs), 1, "窗口 x 随缩放漂移了: %s" % xs)
        self.assertEqual(len(ys), 1, "窗口 y 随缩放漂移了: %s" % ys)
        self.assertEqual(len(sizes), 1, "画布尺寸随缩放变了: %s" % sizes)
        self.assertEqual(xs.pop(), geom["x"])

    def test_canvas_fits_max_stretch(self):
        """最大横向拉伸时本体不得被画布裁掉（左右各留 CANVAS_MARGIN）。"""
        entry = self._entry()
        geom = entry["geom"]
        side = geom["side"]
        widest = int(math.ceil(side * config.JELLY_MAX_W))
        self.assertGreaterEqual(geom["w"], widest)
        canvas, _x, _y = self.app._compose(entry, config.JELLY_MAX_W, 1.0)
        self.assertEqual(canvas.size[0], geom["w"])
        bbox = canvas.getbbox()
        self.assertIsNotNone(bbox)
        self.assertGreaterEqual(bbox[0], 0)
        self.assertLessEqual(bbox[2], geom["w"])

    def test_body_anchored_bottom_center(self):
        """缩放锚点 = 本体槽位底部中心（等价 CSS center bottom）。"""
        entry = self._entry()
        geom = entry["geom"]
        full, _x, _y = self.app._compose(entry, 1.0, 1.0)
        wide, _x, _y = self.app._compose(entry, 1.10, 0.90)
        # 本体底边（画布内）在两种缩放下一致
        self.assertEqual(geom["body_y"] + geom["side"],
                         config.CANVAS_MARGIN + 40)
        # 拉宽后本体像素确实更宽（bbox 右边界右移、左边界左移）
        def _bbox(img):
            return img.getbbox()
        b1 = _bbox(full)
        b2 = _bbox(wide)
        self.assertGreater(b2[2] - b2[0], b1[2] - b1[0])

    def test_window_xy_from_rect_only(self):
        """窗口坐标只由 icon.rect 与画布尺寸决定。"""
        entry = self._entry(rect=(300, 500, 400, 569))
        geom = entry["geom"]
        self.assertEqual(geom["x"], (300 + 400) // 2 - geom["side"] // 2
                         - geom["body_x"])
        self.assertEqual(geom["y"], 500 + config.ICON_TOP_PAD - geom["body_y"])

    def test_hit_test_uses_cell_rect(self):
        """双击命中判定用整个格子矩形。"""
        entry = self._entry(rect=(100, 200, 200, 269))
        self.app.overlays = {"A": entry}
        self.assertEqual(self.app._hit_test(150, 230), "A")
        self.assertIsNone(self.app._hit_test(50, 230))


class ModeSwitchTests(unittest.TestCase):
    """无感切换：切模式时全置 dirty；shown 态隐藏窗口。"""

    def setUp(self):
        self.app = App()
        self.app._side_est = 40
        self.app.icon_cache = {"A": Image.new("RGBA", (40, 40), (0, 255, 0, 255))}
        self.app.icon_base = {"A": _STUB_IMG}
        self.app._label_cache = {}
        self.app._label_font = None
        icon = DesktopIcon("A", "A", (100, 200, 200, 269))
        self.app.overlays = {"A": {"key": "A", "icon": icon, "win": _FakeWin(),
                                   "geom": self.app._layout(
                                       icon, self.app.icon_cache["A"],
                                       self.app._get_label("A")),
                                   "dirty": True, "ready": False,
                                   "_last_state": None}}
        self.app._has_snapshot = True
        self.app._desktop_keys = ["A"]

    def test_set_mode_marks_dirty(self):
        self.assertTrue(self.app._set_mode(True))
        self.assertTrue(all(e["dirty"] for e in self.app.overlays.values()))
        self.assertFalse(self.app._set_mode(True))  # 同模式不重复
        self.assertTrue(self.app._set_mode(False))

    def test_shown_mode_hides_windows(self):
        self.app._set_mode(True)
        self.app._draw_all(True, 1.0, 1.0)
        win = self.app.overlays["A"]["win"]
        self.assertEqual(len(win.drawn), 1)
        # 切回 shown：overlay 必须隐藏（屏幕上只剩原生图标）
        self.app._set_mode(False)
        self.app._draw_all(False, 1.0, 1.0)
        self.assertGreaterEqual(win.hidden, 1)

    def test_static_frame_skipped(self):
        """同一状态重复绘制应被跳过（静音稳态不耗 CPU）。"""
        self.app._set_mode(True)
        self.app._draw_all(True, 1.0, 1.0)
        drawn = self.app._draw_all(True, 1.0, 1.0)
        self.assertEqual(drawn, 0)

    def test_scale_change_forces_redraw(self):
        """缩放变化必须重绘 —— 画布尺寸固定，若跳帧只看尺寸，动画会被吃掉。"""
        self.app._set_mode(True)
        self.assertEqual(self.app._draw_all(True, 1.0, 1.0), 1)
        self.assertEqual(self.app._draw_all(True, 1.0, 1.0), 0)
        self.assertEqual(self.app._draw_all(True, 1.06, 0.94), 1)
        self.assertEqual(self.app._draw_all(True, 1.06, 0.94), 0)
        self.assertEqual(self.app._draw_all(True, 1.10, 0.90), 1)

    def test_prime_draws_before_hiding(self):
        """隐藏真图标之前必须先把副本画满（否则会闪一帧空桌面）。"""
        win = self.app.overlays["A"]["win"]
        self.app._visible_mode = "shown"
        self.assertEqual(len(win.drawn), 0)
        self.assertTrue(self.app._prime_before_hide(1.0, 1.0))
        self.assertEqual(len(win.drawn), 1)
        # 预绘制后 last_sx/sy 已同步，下一帧不会重复画同一状态
        drawn = self.app._draw_all(True, 1.0, 1.0)
        self.assertEqual(drawn, 0)
        self.assertEqual(self.app._last_sx, 1.0)

    def test_prime_refuses_when_overlay_missing(self):
        """副本不全（有桌面项没有 overlay）时必须拒绝隐藏真实图标。"""
        self.app._desktop_keys = ["A", "B"]      # B 没有 overlay
        self.assertFalse(self.app._prime_before_hide(1.0, 1.0))

    def test_prime_refuses_without_snapshot(self):
        """没有有效桌面快照时不许隐藏。"""
        self.app._has_snapshot = False
        self.assertFalse(self.app._prime_before_hide(1.0, 1.0))

    def test_prime_refuses_when_draw_fails(self):
        """任一副本绘制失败就保留真实图标，避免部分桌面消失。"""
        def boom(_img, _x, _y):
            raise RuntimeError("draw failed")
        self.app.overlays["A"]["win"].draw = boom
        self.assertFalse(self.app._prime_before_hide(1.0, 1.0))


class ThresholdTests(unittest.TestCase):
    def test_eps_values(self):
        self.assertLess(SCALE_EPS, 0.005)
        self.assertGreater(SCALE_EPS, 0)
        # 回落判定必须比帧跳过阈值宽，否则退出会卡住
        self.assertGreater(REST_SCALE_EPS, SCALE_EPS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
