# -*- coding: utf-8 -*-
"""音频中断保护：拔耳机/切设备后不能永远重复最后一帧。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from jellyicons import config  # noqa: E402
from jellyicons.audio_engine import AudioEngine, NUM_BANDS  # noqa: E402


class StaleCallbackTests(unittest.TestCase):
    """_compute_bands 必须按回调时间戳判活，而不是相信缓冲里的旧数据。"""

    def setUp(self):
        self.eng = AudioEngine()
        self.eng._build_band_map(self.eng.block)
        self.eng._window = np.hanning(self.eng.block).astype(np.float32)

    def _feed(self, level=0.3):
        n = self.eng.block
        t = np.arange(n, dtype=np.float32) / float(self.eng.rate)
        self.eng._buf[:] = (level * np.sin(2 * np.pi * 55.0 * t)).astype(
            np.float32)
        self.eng._last_callback = 1e18      # 视作"刚刚回调过"
        self.eng._callback_count = 1

    def test_live_signal_produces_energy(self):
        self._feed()
        bands = self.eng._compute_bands()
        self.assertEqual(bands.shape, (NUM_BANDS,))
        self.assertGreater(float(bands[:3].mean()), 0.0)

    def test_never_called_returns_zeros(self):
        bands = self.eng._compute_bands()
        self.assertEqual(float(np.abs(bands).sum()), 0.0,
                         "没有回调过就必须全零")

    def test_stale_callback_returns_zeros(self):
        self._feed()
        # 模拟回调停了很久（拔耳机/切设备）
        self.eng._last_callback = -1e9
        bands = self.eng._compute_bands()
        self.assertEqual(float(np.abs(bands).sum()), 0.0,
                         "回调超时后必须归零，不能重复旧缓冲")

    def test_close_clears_buffer(self):
        self._feed()
        self.eng.close()
        self.assertEqual(float(np.abs(self.eng._buf).sum()), 0.0)
        self.assertEqual(self.eng._callback_count, 0)
        self.assertFalse(self.eng.available)

    def test_stale_threshold_is_short(self):
        # 阈值必须明显短于音乐模式的恢复延迟，否则 presence 掉不下来
        self.assertLess(config.AUDIO_STALE_S, config.MUSIC_OFF_HOLD_S)


if __name__ == "__main__":
    unittest.main(verbosity=2)
