# -*- coding: utf-8 -*-
"""音乐模式滞回判定与心跳文件单测（不碰真实桌面窗口）。"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jellyicons import config, music_mode, watchdog  # noqa: E402


class HysteresisTests(unittest.TestCase):
    """把 _enter_hidden/_exit_hidden 换成纯状态翻转，只测判定时序。"""

    def setUp(self):
        self.transitions = []
        outer = self

        class FakeMode(music_mode.MusicMode):
            def _enter_hidden(self):
                self.state = music_mode.STATE_HIDDEN
                outer.transitions.append(("hide", now[0]))

            def _exit_hidden(self):
                self.state = music_mode.STATE_SHOWN
                outer.transitions.append(("show", now[0]))

        self.FakeMode = FakeMode
        now = [0.0]
        self.now = now

    def feed_span(self, mode, bass, seconds, step=0.05):
        """在 [t, t+seconds] 内以固定步长喂入恒定 bass。"""
        end = self.now[0] + seconds
        while self.now[0] < end:
            self.now[0] += step
            mode.feed(bass, self.now[0])
        return mode.state

    def test_disabled_never_hides(self):
        mode = self.FakeMode(enabled=False)
        self.feed_span(mode, 0.5, 5.0)
        self.assertEqual(mode.state, music_mode.STATE_SHOWN)
        self.assertEqual(self.transitions, [])

    def test_loud_hides_after_hold(self):
        mode = self.FakeMode()
        self.feed_span(mode, 0.05, config.MUSIC_ON_HOLD_S - 0.2)
        self.assertEqual(mode.state, music_mode.STATE_INIT)  # 还不够久
        self.feed_span(mode, 0.05, 0.4)
        self.assertEqual(mode.state, music_mode.STATE_HIDDEN)
        self.assertEqual(self.transitions[0][0], "hide")

    def test_quiet_restores_after_hold(self):
        mode = self.FakeMode()
        self.feed_span(mode, 0.05, config.MUSIC_ON_HOLD_S + 0.3)
        self.assertEqual(mode.state, music_mode.STATE_HIDDEN)
        self.feed_span(mode, 0.001, config.MUSIC_OFF_HOLD_S - 0.3)
        self.assertEqual(mode.state, music_mode.STATE_HIDDEN)  # 还不够久
        self.feed_span(mode, 0.001, 0.6)
        self.assertEqual(mode.state, music_mode.STATE_SHOWN)
        self.assertEqual([t[0] for t in self.transitions], ["hide", "show"])

    def test_beat_gap_does_not_flap(self):
        """节拍间隙（0.3s 静音）不应触发恢复。"""
        mode = self.FakeMode()
        self.feed_span(mode, 0.05, config.MUSIC_ON_HOLD_S + 0.3)
        for _ in range(3):
            self.feed_span(mode, 0.001, 0.3)   # 间隙
            self.feed_span(mode, 0.05, 0.3)    # 下一拍
        self.assertEqual(mode.state, music_mode.STATE_HIDDEN)
        self.assertEqual([t[0] for t in self.transitions], ["hide"])

    def test_threshold_boundary(self):
        """刚好等于 ON 阈值应触发（>=），低于则不算。"""
        mode = self.FakeMode()
        self.feed_span(mode, config.MUSIC_ON_THRESHOLD, config.MUSIC_ON_HOLD_S + 0.3)
        self.assertEqual(mode.state, music_mode.STATE_HIDDEN)

        mode2 = self.FakeMode()
        self.transitions.clear()
        self.now[0] = 0.0
        self.feed_span(mode2, config.MUSIC_ON_THRESHOLD - 1e-6, 3.0)
        # 启动即静音：落到 shown（不能卡在 init，否则主循环的 at_rest 判断会漏）
        self.assertEqual(mode2.state, music_mode.STATE_SHOWN)
        self.assertEqual(self.transitions, [])

    def test_allow_exit_gate_holds_hidden(self):
        """allow_exit=False 时静音也不能退出（等缩放回落到 1.0 再切）。"""
        mode = self.FakeMode()
        self.feed_span(mode, 0.05, config.MUSIC_ON_HOLD_S + 0.3)
        self.assertEqual(mode.state, music_mode.STATE_HIDDEN)
        end = self.now[0] + config.MUSIC_OFF_HOLD_S + 1.0
        while self.now[0] < end:
            self.now[0] += 0.05
            mode.feed(0.0, self.now[0], allow_exit=False)
        self.assertEqual(mode.state, music_mode.STATE_HIDDEN)
        self.assertEqual([t[0] for t in self.transitions], ["hide"])
        # 放开闸门后立即退出
        self.now[0] += 0.05
        mode.feed(0.0, self.now[0], allow_exit=True)
        self.assertEqual(mode.state, music_mode.STATE_SHOWN)

    def test_before_enter_runs_once_before_hide(self):
        """隐藏真图标前必须先执行 before_enter（先画副本，再让图标消失）。"""
        calls = []
        mode = self.FakeMode()
        end = self.now[0] + config.MUSIC_ON_HOLD_S + 0.5
        while self.now[0] < end:
            self.now[0] += 0.05
            mode.feed(0.05, self.now[0],
                      before_enter=lambda: calls.append(self.now[0]))
        self.assertEqual(mode.state, music_mode.STATE_HIDDEN)
        self.assertEqual(len(calls), 1, "before_enter 应只执行一次: %s" % calls)
        self.assertEqual(len(self.transitions), 1)
        # 回调发生在隐藏之前（时间戳不晚于 hide）
        self.assertLessEqual(calls[0], self.transitions[0][1])

    def test_before_enter_failure_keeps_icons_visible(self):
        """副本预绘制失败必须保留真实图标：宁可没特效，也不能空桌面。"""
        def boom():
            raise RuntimeError("draw failed")

        mode = self.FakeMode()
        end = self.now[0] + config.MUSIC_ON_HOLD_S + 0.5
        while self.now[0] < end:
            self.now[0] += 0.05
            mode.feed(0.05, self.now[0], before_enter=boom)
        self.assertEqual(mode.state, music_mode.STATE_INIT)
        self.assertEqual(self.transitions, [])

    def test_before_enter_false_blocks_hide(self):
        """回调明确返回 False（覆盖率不足）时同样不许隐藏。"""
        mode = self.FakeMode()
        end = self.now[0] + config.MUSIC_ON_HOLD_S + 0.5
        while self.now[0] < end:
            self.now[0] += 0.05
            mode.feed(0.05, self.now[0], before_enter=lambda: False)
        self.assertEqual(self.transitions, [])

    def test_hide_attempts_are_throttled(self):
        """隐藏失败后要退避，不能每帧重复预绘制。"""
        calls = []
        mode = self.FakeMode()
        mode._enter_hidden = lambda: calls.append(self.now[0])
        end = self.now[0] + config.MUSIC_ON_HOLD_S + 2.0
        while self.now[0] < end:
            self.now[0] += 0.01          # 100Hz 主循环
            mode.feed(0.05, self.now[0], before_enter=lambda: True)
        # 2 秒内最多 5 次尝试（0.5s 退避）
        self.assertLessEqual(len(calls), 5, "隐藏尝试没有被退避: %d" % len(calls))
        self.assertGreaterEqual(len(calls), 2)


class RestoreTests(unittest.TestCase):
    """退出恢复必须可判定成败：失败要留给看门狗。"""

    def test_restore_reports_failure(self):
        mode = music_mode.MusicMode()
        mode._hide_succeeded = True
        mode._show_listview = lambda: False
        self.assertFalse(mode.restore())
        self.assertTrue(mode._hide_succeeded, "失败时不能清掉所有权")

    def test_restore_reports_success(self):
        mode = music_mode.MusicMode()
        mode._hide_succeeded = True
        mode._show_listview = lambda: True
        self.assertTrue(mode.restore())
        self.assertFalse(mode._hide_succeeded)
        self.assertEqual(mode.state, music_mode.STATE_SHOWN)

    def test_restore_noop_when_never_hidden(self):
        mode = music_mode.MusicMode()
        self.assertTrue(mode.restore())


class HeartbeatTests(unittest.TestCase):
    def tearDown(self):
        watchdog.clear_heartbeat()

    def test_roundtrip(self):
        watchdog.write_heartbeat(1234, True)
        hb = watchdog.read_heartbeat()
        self.assertIsNotNone(hb)
        self.assertEqual(hb["pid"], 1234)
        self.assertTrue(hb["hidden"])
        self.assertAlmostEqual(hb["ts"], time.time(), delta=5.0)

    def test_clear(self):
        watchdog.write_heartbeat(1, False)
        watchdog.clear_heartbeat()
        self.assertIsNone(watchdog.read_heartbeat())

    def test_read_missing_is_none(self):
        watchdog.clear_heartbeat()
        self.assertIsNone(watchdog.read_heartbeat())

    def test_read_garbage_is_none(self):
        watchdog.HEARTBEAT_PATH.write_text("not json", encoding="utf-8")
        self.assertIsNone(watchdog.read_heartbeat())


class WindowChainTests(unittest.TestCase):
    def test_find_listview_returns_int(self):
        """只断言类型：找不到（无 explorer）返回 0 也算正常。"""
        hwnd = music_mode.find_listview_hwnd()
        self.assertIsInstance(hwnd, int)
        self.assertGreaterEqual(hwnd, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
