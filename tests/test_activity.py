# -*- coding: utf-8 -*-
"""ActivityDetector：逐频段 AGC、包络、presence 判定单测。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jellyicons import config  # noqa: E402
from jellyicons.activity import ActivityDetector  # noqa: E402

N = 64
DT = 1.0 / 60.0


def _bands(bass=0.0, mid=0.0, rest=0.0):
    out = [rest] * N
    out[0] = out[1] = out[2] = bass
    for i in range(8, 24):
        out[i] = mid
    return out


class AgcTests(unittest.TestCase):
    def test_silence_gives_zero(self):
        det = ActivityDetector()
        for _ in range(30):
            bass, presence = det.update([0.0] * N, DT)
        self.assertEqual(bass, 0.0)
        self.assertEqual(presence, 0.0)

    def test_weak_music_still_normalized(self):
        """AGC 的意义：很轻的音乐也要被拉到可用的 0..1 区间。

        旧实现用 64 段全局峰值归一化，低频被中高频压到 0.011，
        形变只有 ±1.5%（用户看到的"几乎没效果"）。

        实测校准（55Hz 正弦，WASAPI loopback）：amp=0.30 → 低频段
        幅度 0.0459；amp=0.05（很轻）→ 0.00946。AGC_FLOOR=0.02 是噪声门，
        低于它的信号最多被放大到 floor 的倒数倍，所以 0.00946 归一化后
        约 0.47、0.004 约 0.20 —— 都远高于 MUSIC_OFF_THRESHOLD(0.008)，
        音乐开关判得出来，形变也有 rawVol≈0.011~0.026 可用。
        """
        det = ActivityDetector()
        bass = presence = 0.0
        for _ in range(180):        # 3 秒
            bass, presence = det.update(_bands(bass=0.00946, mid=0.30), DT)
        self.assertGreater(bass, 0.4, "轻音乐的低频没有被 AGC 拉到可用区间")
        self.assertGreater(bass, config.MUSIC_OFF_THRESHOLD * 10)

    def test_floor_is_noise_gate(self):
        """底噪不该被 AGC 放大成满幅（否则静音也会触发音乐模式）。"""
        det = ActivityDetector()
        bass = 1.0
        for _ in range(180):
            bass, _p = det.update(_bands(bass=0.0005), DT)
        self.assertLess(bass, config.MUSIC_ON_THRESHOLD,
                        "AGC 把底噪放大到能触发音乐模式了")

    def test_agc_ignores_global_peak(self):
        """中高频再响，也不该压低低频的归一化结果。"""
        quiet_mid = ActivityDetector()
        loud_mid = ActivityDetector()
        a = b = 0.0
        for _ in range(180):
            a, _ = quiet_mid.update(_bands(bass=0.01, mid=0.02), DT)
            b, _ = loud_mid.update(_bands(bass=0.01, mid=0.90), DT)
        self.assertAlmostEqual(a, b, delta=0.15,
                               msg="低频归一化被中高频影响了")

    def test_peak_decays_back_down(self):
        """音乐停止后峰值缓慢回落，presence 才能降到静音判定以下。"""
        det = ActivityDetector()
        for _ in range(120):
            det.update(_bands(bass=0.3), DT)
        presence = 1.0
        for _ in range(int(6.0 / DT)):    # 静音 6 秒
            _bass, presence = det.update([0.0] * N, DT)
        self.assertLess(presence, config.MUSIC_OFF_THRESHOLD)

    def test_reset(self):
        det = ActivityDetector()
        for _ in range(60):
            det.update(_bands(bass=0.3), DT)
        det.reset()
        self.assertEqual(det.update([0.0] * N, DT), (0.0, 0.0))


class EnvelopeTests(unittest.TestCase):
    def test_attack_faster_than_release(self):
        """起音 0.06s、释放 0.5s：包络上升明显快于下降。"""
        det = ActivityDetector()
        for _ in range(120):
            det.update(_bands(bass=0.3), DT)
        _bass, peak_presence = det.update(_bands(bass=0.3), DT)

        # 突然静音，1 帧后应只掉一点点（释放慢）
        _bass, after1 = det.update([0.0] * N, DT)
        self.assertGreater(after1, peak_presence * 0.95,
                           "释放太快：单帧就掉了超过 5%")

        # 从静音开始，1 帧上升幅度应远大于释放幅度（起音快）
        det2 = ActivityDetector()
        _b0, p0 = det2.update([0.0] * N, DT)
        _b1, p1 = det2.update(_bands(bass=0.3), DT)
        self.assertGreater(p1 - p0, peak_presence - after1)

    def test_beat_gaps_filled(self):
        """节拍间隙（3 帧静音）不应让 presence 掉到 0 —— 这是"秒级延迟"的根因。"""
        det = ActivityDetector()
        for _ in range(120):
            det.update(_bands(bass=0.3), DT)
        lo = 1.0
        for _ in range(12):
            for _ in range(3):
                _b, p = det.update([0.0] * N, DT)
                lo = min(lo, p)
            for _ in range(20):
                _b, p = det.update(_bands(bass=0.3), DT)
                lo = min(lo, p)
        self.assertGreater(lo, config.MUSIC_OFF_THRESHOLD * 3,
                           "节拍间隙把 presence 打到静音阈值附近了")


class PresenceTests(unittest.TestCase):
    def test_presence_bounded(self):
        det = ActivityDetector()
        for _ in range(300):
            _b, p = det.update(_bands(bass=5.0, mid=5.0), DT)
        self.assertLessEqual(p, 1.0)
        self.assertGreaterEqual(p, 0.0)

    def test_presence_tracks_bass(self):
        det = ActivityDetector()
        for _ in range(120):
            _b, p = det.update(_bands(bass=0.2), DT)
        self.assertGreater(p, config.MUSIC_ON_THRESHOLD)

    def test_mid_only_also_detected(self):
        """只有中高频（无低频）的内容也算"有声音"，避免漏判。"""
        det = ActivityDetector()
        for _ in range(180):
            _b, p = det.update(_bands(bass=0.0, mid=0.4), DT)
        self.assertGreater(p, config.MUSIC_ON_THRESHOLD)


if __name__ == "__main__":
    unittest.main(verbosity=2)
