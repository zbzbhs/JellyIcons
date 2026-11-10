# -*- coding: utf-8 -*-
"""8 个动画模式 + 切换器：有界性、引擎契约、轮换与归位。

这一层是"会不会把图标甩出屏幕/画出 NaN"的最后一道闸门 —— 模式里的
数学一旦发散，overlay 窗口就会跑到屏幕外或者画布越界裁边。所以每个
模式都要在极端输入下（bass=1.0、presence=1.0、连续 600 帧）保证：
    - sx/sy 落在 [MIN_SCALE, JELLY_MAX_W] 里（画布按上限预留，超了会裁边）
    - overlay 引擎的 dx/dy 必须恒 0（这是"不位移"承诺的代码级保证）
    - 所有值都是有限数（不能有 nan/inf，否则 UpdateLayeredWindow 会失败）
"""
import math
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from jellyicons import config, jelly                       # noqa: E402
from jellyicons.modes import (ALL_MODES, BY_NAME, ENGINE_OVERLAY,  # noqa: E402
                              ENGINE_TAKEOVER, ModeContext, Transform,
                              create, names)
from jellyicons.modes.switcher import ModeSwitcher         # noqa: E402


class _Icon:
    def __init__(self, key, rect):
        self.key = key
        self.name = key
        self.rect = rect


def _icons(n=5):
    out = []
    for i in range(n):
        left = 60 + i * 130
        top = 80 + (i % 2) * 150
        out.append((("K%d" % i),
                    _Icon("K%d" % i, (left, top, left + 60, top + 76))))
    return out


def _ctx(presence=0.7, bass=0.9, bands=None, now=10.0, n=5):
    if bands is None:
        bands = [min(1.0, 0.2 + 0.5 * math.sin(i * 0.4)) for i in range(64)]
    return ModeContext(icons=_icons(n), bands=bands, bass=bass,
                       presence=presence, jelly=jelly.make_state(),
                       screen=(1920, 1080), now=now)


class RegistrationTests(unittest.TestCase):
    def test_eight_modes_registered(self):
        self.assertEqual(len(ALL_MODES), 8)
        self.assertEqual(len(names()), 8)
        self.assertEqual(len(set(names())), 8, "模式名不能重复")

    def test_expected_order(self):
        # 面板按钮顺序 = 这个顺序，改顺序要同步改 README
        self.assertEqual(names(), ["jelly", "free", "kun", "heart",
                                   "bands", "wave", "ring", "firework"])

    def test_every_mode_has_metadata(self):
        for cls in ALL_MODES:
            self.assertTrue(cls.name)
            self.assertTrue(cls.title)
            self.assertIn(cls.engine, (ENGINE_OVERLAY, ENGINE_TAKEOVER))

    def test_create_unknown_raises(self):
        with self.assertRaises(KeyError):
            create("不存在")


class BoundedTests(unittest.TestCase):
    """每个模式单独跑 600 帧，检查数值边界。"""

    FRAMES = 600

    def _run(self, name):
        mode = create(name)
        ctx = _ctx()
        mode.attach(ctx)
        worst = {"sx": 0.0, "sy": 0.0, "dx": 0.0, "dy": 0.0}
        bad = []
        min_sy = 0.55
        max_sy = 1.45
        for _ in range(self.FRAMES):
            raw = mode.tick(ctx, 1.0 / 60.0)
            for key, tf in raw.items():
                # 先验原始输出必须全是有限数（nan/inf 会让绘制直接失败）
                for field in ("sx", "sy", "dx", "dy", "alpha"):
                    v = getattr(tf, field)
                    if not isinstance(v, float) or not math.isfinite(v):
                        bad.append((key, field, v))
                # 再按 app 的做法规整，检查界内
                tf = tf.clamp(BY_NAME[name].engine, config.JELLY_MAX_W, 0.45)
                worst["sx"] = max(worst["sx"], tf.sx)
                worst["sy"] = max(worst["sy"], tf.sy)
                worst["dx"] = max(worst["dx"], abs(tf.dx))
                worst["dy"] = max(worst["dy"], abs(tf.dy))
                if not (config.MIN_SCALE <= tf.sx <= config.JELLY_MAX_W):
                    bad.append((key, "sx-range", tf.sx))
                if not (min_sy <= tf.sy <= max_sy):
                    bad.append((key, "sy-range", tf.sy))
                if not (0.0 <= tf.alpha <= 1.0):
                    bad.append((key, "alpha-range", tf.alpha))
        return worst, bad

    def test_all_modes_bounded(self):
        for name in names():
            with self.subTest(mode=name):
                worst, bad = self._run(name)
                self.assertEqual(bad, [], "%s 越界: %r" % (name, bad[:3]))

    def test_numpy_bands_do_not_break_modes(self):
        """回归：audio.bands() 返回 numpy 数组，模式里 `if ctx.bands` 会炸。

        真机日志出现过 `free tick 异常: ValueError('The truth value of an
        array with more than one element is ambiguous')` —— 单元测试一直用
        list 喂数据，所以从没复现。ModeContext 现在把 bands 转成 list，
        这里直接用 numpy 数组构造上下文，确保 8 个模式都能跑。
        """
        try:
            import numpy as np
        except ImportError:  # pragma: no cover - numpy 是硬依赖
            self.skipTest("numpy 不可用")
        arr = np.array([min(1.0, 0.2 + 0.5 * math.sin(i * 0.4))
                        for i in range(64)], dtype=np.float64)
        ctx = ModeContext(icons=_icons(), bands=arr, bass=0.9, presence=0.7,
                          jelly=jelly.make_state(), screen=(1920, 1080),
                          now=10.0)
        self.assertIsInstance(ctx.bands, list, "ModeContext 必须把 bands 转成 list")
        for name in names():
            with self.subTest(mode=name):
                mode = create(name)
                mode.attach(ctx)
                out = mode.tick(ctx, 1.0 / 60.0)
                self.assertTrue(out, "%s 在有频段时不应返回空" % name)
                for tf in out.values():
                    self.assertTrue(math.isfinite(tf.sx))
                    self.assertTrue(math.isfinite(tf.sy))

    def test_empty_bands_fall_back_to_still(self):
        """没有频段时（音频未就绪）模式要么静止要么给 1:1，不能抛异常。"""
        ctx = ModeContext(icons=_icons(), bands=[], bass=0.0, presence=0.0,
                          jelly=jelly.make_state(), screen=(1920, 1080),
                          now=10.0)
        for name in names():
            with self.subTest(mode=name):
                mode = create(name)
                mode.attach(ctx)
                out = mode.tick(ctx, 1.0 / 60.0)
                for key, tf in out.items():
                    self.assertLess(abs(tf.sx - 1.0), 0.35,
                                    "%s/%s 静音时形变过大" % (name, key))

    def test_overlay_modes_never_move(self):
        """overlay 引擎的位移必须是硬 0 —— 这是不打扰桌面的根基。"""
        for name in names():
            if BY_NAME[name].engine != ENGINE_OVERLAY:
                continue
            with self.subTest(mode=name):
                worst, _bad = self._run(name)
                self.assertEqual(worst["dx"], 0.0, name)
                self.assertEqual(worst["dy"], 0.0, name)

    def test_takeover_modes_actually_move(self):
        """反过来，takeover 模式如果一动不动，说明它就是坏掉的。"""
        for name in names():
            if BY_NAME[name].engine != ENGINE_TAKEOVER:
                continue
            with self.subTest(mode=name):
                worst, _bad = self._run(name)
                self.assertGreater(worst["dx"] + worst["dy"], 0.5, name)

    def test_silence_is_calm(self):
        """没有音乐时任何模式都不该大幅形变（否则切回真图标会看到跳）。"""
        for name in names():
            mode = create(name)
            ctx = _ctx(presence=0.0, bass=0.0, bands=[0.0] * 64)
            mode.attach(ctx)
            peak = 0.0
            for _ in range(180):
                for tf in mode.tick(ctx, 1.0 / 60.0).values():
                    peak = max(peak, abs(tf.sx - 1.0) + abs(tf.sy - 1.0))
            with self.subTest(mode=name):
                self.assertLess(peak, 0.25, "%s 静音时形变太大" % name)


class TransformTests(unittest.TestCase):
    def test_is_rest(self):
        self.assertTrue(Transform().is_rest())
        self.assertTrue(Transform(1.001, 0.999).is_rest(eps=0.01))
        self.assertFalse(Transform(1.05).is_rest())
        self.assertFalse(Transform(dx=3.0).is_rest())

    def test_blended_endpoints(self):
        tf = Transform(sx=1.2, sy=0.8, dx=40.0, dy=-20.0, alpha=0.5)
        self.assertEqual(tf.blended(1.0), tf)
        rest = tf.blended(0.0)
        self.assertAlmostEqual(rest.sx, 1.0)
        self.assertAlmostEqual(rest.sy, 1.0)
        self.assertAlmostEqual(rest.dx, 0.0)
        self.assertAlmostEqual(rest.dy, 0.0)
        self.assertAlmostEqual(rest.alpha, 1.0)

    def test_blended_is_linear(self):
        tf = Transform(sx=1.4, dx=100.0)
        half = tf.blended(0.5)
        self.assertAlmostEqual(half.sx, 1.2)
        self.assertAlmostEqual(half.dx, 50.0)

    def test_clamp_drops_displacement_for_overlay(self):
        tf = Transform(sx=1.1, sy=0.9, dx=500.0, dy=-500.0)
        out = tf.clamp(ENGINE_OVERLAY, config.JELLY_MAX_W, 0.45)
        self.assertEqual(out.dx, 0.0)
        self.assertEqual(out.dy, 0.0)

    def test_clamp_keeps_displacement_for_takeover(self):
        tf = Transform(sx=1.1, sy=0.9, dx=500.0, dy=-500.0)
        out = tf.clamp(ENGINE_TAKEOVER, config.JELLY_MAX_W, 0.45)
        self.assertEqual(out.dx, 500.0)
        self.assertEqual(out.dy, -500.0)

    def test_clamp_bounds_scale(self):
        tf = Transform(sx=9.0, sy=0.01)
        out = tf.clamp(ENGINE_OVERLAY, config.JELLY_MAX_W, 0.45)
        self.assertLessEqual(out.sx, config.JELLY_MAX_W)
        self.assertGreaterEqual(out.sy, 0.45)


class SwitcherTests(unittest.TestCase):
    def test_start_mode(self):
        sw = ModeSwitcher(start="heart")
        self.assertEqual(sw.name, "heart")
        self.assertEqual(sw.engine, ENGINE_TAKEOVER)

    def test_bad_start_falls_back(self):
        sw = ModeSwitcher(start="不存在")
        self.assertIn(sw.name, names())

    def test_select_returns_change_flag(self):
        sw = ModeSwitcher(start="jelly")
        self.assertFalse(sw.select("jelly"), "同一个模式不该算切换")
        self.assertTrue(sw.select("wave"))
        self.assertEqual(sw.name, "wave")

    def test_select_unknown_raises(self):
        sw = ModeSwitcher()
        with self.assertRaises(KeyError):
            sw.select("nope")

    def test_next_prev_cycle(self):
        sw = ModeSwitcher(start="jelly")
        order = sw.order
        for _ in range(len(order)):
            sw.next()
        self.assertEqual(sw.name, "jelly", "转一圈应该回到起点")
        sw.prev()
        self.assertEqual(sw.name, order[-1])

    def test_auto_rotation_respects_dwell(self):
        sw = ModeSwitcher(start="jelly", auto=True)
        first = sw.name
        ctx = _ctx()
        # jelly 的 dwell 是 10 秒；跑 9 秒不该换
        for _ in range(int(9.0 * 60)):
            sw.tick(ctx, 1.0 / 60.0, active=True)
        self.assertEqual(sw.name, first)
        # 再跑 2 秒应该换掉了
        for _ in range(int(2.0 * 60)):
            sw.tick(ctx, 1.0 / 60.0, active=True)
        self.assertNotEqual(sw.name, first)

    def test_auto_off_never_rotates(self):
        sw = ModeSwitcher(start="jelly", auto=False)
        ctx = _ctx()
        for _ in range(int(30.0 * 60)):
            sw.tick(ctx, 1.0 / 60.0, active=True)
        self.assertEqual(sw.name, "jelly")

    def test_kun_is_long_and_looping(self):
        """两年半是"跳完一轮才走"，不能按 10 秒硬切。"""
        from jellyicons.modes import kun as kun_mod
        self.assertIsNone(BY_NAME["kun"].dwell_s)
        self.assertGreater(kun_mod.LOOP_S, 5.0)

    def test_inactive_winds_down_to_rest(self):
        """音乐停下后形变必须回到 1:1，否则切回真图标会看到图标"跳"。"""
        sw = ModeSwitcher(start="free", auto=False)
        ctx = _ctx()
        for _ in range(120):
            sw.tick(ctx, 1.0 / 60.0, active=True)
        last = None
        for _ in range(120):
            transforms, _engine, k = sw.tick(ctx, 1.0 / 60.0, active=False)
            last = (transforms, k)
        transforms, k = last
        self.assertEqual(k, 0.0, "下坡结束后 k 必须归零")
        for key, tf in transforms.items():
            self.assertTrue(tf.is_rest(eps=1e-6),
                            "%s 没有完全归位: %r" % (key, tf))

    def test_blend_starts_near_rest(self):
        """刚切模式的第一帧不能把形变一步到位（那是"突跳"）。"""
        sw = ModeSwitcher(start="jelly", auto=False)
        ctx = _ctx()
        for _ in range(60):
            sw.tick(ctx, 1.0 / 60.0, active=True)
        sw.select("heart")
        transforms, _engine, k = sw.tick(ctx, 1.0 / 60.0, active=True)
        self.assertLess(k, 1.0)
        for tf in transforms.values():
            self.assertLess(abs(tf.dx), 60.0, "第一帧不该已经飞出去")

    def test_failing_mode_does_not_crash(self):
        """模式 tick 抛异常时必须退化成静止，连续三次后自动跳过。"""
        sw = ModeSwitcher(start="jelly", auto=False)

        class _Boom:
            name = "boom"
            title = "炸"
            engine = ENGINE_OVERLAY
            dwell_s = 10.0

            def attach(self, ctx):
                pass

            def detach(self):
                pass

            def tick(self, ctx, dt):
                raise RuntimeError("boom")

            def wants_exit(self, ctx):
                return False

        sw._mode = _Boom()
        ctx = _ctx()
        first = sw.name
        for i in range(3):
            transforms, engine, _k = sw.tick(ctx, 1.0 / 60.0, active=True)
            # 异常帧必须退化成"什么都没画"，而不是崩掉整个程序
            self.assertEqual(transforms, {}, "第 %d 帧应该退回静止" % (i + 1))
            self.assertIn(engine, (ENGINE_OVERLAY, ENGINE_TAKEOVER))
        # 连续三次后切到一个真模式，说明坏模式被跳过了
        self.assertNotEqual(sw.name, "boom")
        self.assertIn(sw.name, names())
        self.assertNotEqual(sw.name, first if first != "boom" else "boom")

    def test_restart_resets_elapsed(self):
        sw = ModeSwitcher(start="kun", auto=True)
        ctx = _ctx()
        for _ in range(300):
            sw.tick(ctx, 1.0 / 60.0, active=True)
        sw.restart()
        self.assertEqual(sw._elapsed, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
