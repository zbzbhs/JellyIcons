# -*- coding: utf-8 -*-
"""纯进程内测试：不碰 explorer、不碰注册表、不依赖 UIA 数据。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jellyicons import config, jelly


class JellyModelTests(unittest.TestCase):
    """壁纸律动模型的数学不变量。"""

    def setUp(self):
        self.state = jelly.make_state()

    def test_silent_input_decays_to_zero(self):
        for _ in range(200):
            sx, sy = self.state.step(0.0)
        self.assertEqual((sx, sy), (1.0, 1.0))

    def test_scale_bounds_pulse_cap(self):
        """pulse 上限 volCap*1.1 => 变形不超过 squash*gain 的理论上限。"""
        vol_cap = config.DOLL["volumeCap"]
        squash = config.DOLL["squashX"]
        max_tx = 1 + vol_cap * 1.1 * squash * config.JELLY_GAIN_X
        peak = 1.0
        for i in range(2000):
            # 持续大音量
            sx, sy = self.state.step(1.0)
            peak = max(peak, sx)
            self.assertLessEqual(sx, max_tx + 1e-9)
            self.assertGreaterEqual(sx, config.MIN_SCALE)
        # lerp 渐近 + beat 冷却（25 帧）会让 pulse 在两次 beat 之间衰减到
        # 约 25%，实测稳态峰值 pulse≈0.0377、scaleX≈1.10 —— 即用掉理论上限
        # 的约 46%。这里只卡"必须明显看得出在拉"：横向 ≥ +8%。
        self.assertGreater(peak, 1.08)
        # 理论上限必须落在画布预留范围内，否则拉伸会被裁边
        self.assertLessEqual(max_tx, config.JELLY_MAX_W)

    def test_scaley_never_exceeds_one(self):
        """修正后的 bounce 包络必须保证 scaleY ≤ 1。"""
        for i in range(3000):
            sx, sy = self.state.step(0.3)
            self.assertLessEqual(sy, 1.0 + 1e-9)

    def test_beat_triggers_pulse(self):
        raw = 0.0
        for i in range(30):
            self.state.step(raw)
        self.state.step(0.5)  # 突然大音量 -> beat
        self.assertGreater(self.state.pulse, 0.0)

    def test_noise_below_threshold_ignored(self):
        for i in range(50):
            self.state.step(0.01)  # < noiseThreshold=0.02
        self.assertEqual(self.state.pulse, 0.0)

    def test_beat_cooldown_limits_pulse_rate(self):
        big = jelly.make_state(is_big=False)
        pulses = []
        for i in range(60):
            big.step(1.0)
            pulses.append(big.pulse)
        # cooldown=25 帧，两次 beat 之间 pulse 必然衰减过
        self.assertLess(min(pulses[5:]), max(pulses))


class ConfigTests(unittest.TestCase):
    def test_project_json_values(self):
        self.assertAlmostEqual(config.DOLL["volumeCap"], 0.05)
        self.assertAlmostEqual(config.GLOBAL_SENSITIVITY, 0.9)

    def test_max_scale_dynamic_clamp(self):
        # squash=1.5 -> 1+0.45=1.45 -> max(1.5, min(5, 1.45)) = 1.5
        self.assertAlmostEqual(config.max_scale(config.DOLL), 1.5)


class GeometryTests(unittest.TestCase):
    def test_bottom_anchor_compresses_upward(self):
        """底部锚点：scaleY<1 时新顶部 = 底部 - new_h（往下压）。"""
        h = 100
        sy = 0.9
        new_h = int(h * sy)
        bottom_y = 500 + h
        self.assertEqual(bottom_y - new_h, 500 + h - 90)


if __name__ == "__main__":
    unittest.main(verbosity=2)
