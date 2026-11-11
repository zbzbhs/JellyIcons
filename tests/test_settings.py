# -*- coding: utf-8 -*-
"""设置持久化：Q 弹程度能不能记住、坏了会不会崩、越界会不会夹住。

这一层是"用户拖了滑块、下次打开还是那个手感"的保证。写盘用
tmp + os.replace 原子替换 —— 直接 write_text 会在写到一半断电时
留下半个 JSON，下次启动就回落默认值，用户会觉得"设置又丢了"。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from jellyicons import settings  # noqa: E402


class _TempHome:
    """把 data_path 指到临时目录，避免测试污染真机 settings.json。"""

    def __enter__(self):
        self._dir = tempfile.mkdtemp(prefix="jelly_settings_")
        self._orig = settings.paths.data_path

        def fake_data_path(*parts):
            return os.path.join(self._dir, *parts)

        settings.paths.data_path = fake_data_path
        return self._dir

    def __exit__(self, *exc):
        settings.paths.data_path = self._orig
        shutil.rmtree(self._dir, ignore_errors=True)
        return False


class LoadSaveTests(unittest.TestCase):
    def test_defaults_when_missing(self):
        with _TempHome():
            s = settings.Settings.load()
            self.assertEqual(s.gain, 1.0)
            self.assertFalse(os.path.exists(
                settings.paths.data_path(settings.FILE_NAME)))

    def test_roundtrip(self):
        with _TempHome():
            s = settings.Settings.load()
            s.set_gain(1.45)
            s["mode"] = "spell"
            s.save()
            again = settings.Settings.load()
            self.assertAlmostEqual(again.gain, 1.45)
            self.assertEqual(again["mode"], "spell")

    def test_broken_file_falls_back(self):
        """半个 JSON / 乱码不能让程序起不来。"""
        with _TempHome():
            path = settings.paths.data_path(settings.FILE_NAME)
            with io.open(path, "w", encoding="utf-8") as f:
                f.write('{"gain": 1.9, "mode": ')   # 故意截断
            s = settings.Settings.load()
            self.assertEqual(s.gain, 1.0)

    def test_unknown_keys_survive(self):
        """以后加的新键不该被旧版本抹掉（前向兼容）。"""
        with _TempHome():
            path = settings.paths.data_path(settings.FILE_NAME)
            with io.open(path, "w", encoding="utf-8") as f:
                json.dump({"gain": 1.2, "future_key": [1, 2, 3]}, f)
            s = settings.Settings.load()
            self.assertEqual(s["future_key"], [1, 2, 3])
            s.save()
            with io.open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["future_key"], [1, 2, 3])


class GainTests(unittest.TestCase):
    def test_clamped_to_range(self):
        with _TempHome():
            s = settings.Settings.load()
            self.assertEqual(s.set_gain(-5.0), settings.GAIN_MIN)
            self.assertEqual(s.set_gain(99.0), settings.GAIN_MAX)

    def test_step_is_small(self):
        """滑块拖一格不能跳一大截（否则手感是"抖"不是"柔"）。"""
        with _TempHome():
            s = settings.Settings.load()
            s.set_gain(1.0)
            s.set_gain(1.0 + 0.01)
            self.assertAlmostEqual(s.gain, 1.01, places=6)

    def test_presets_are_in_range(self):
        for name, value in settings.GAIN_PRESETS:
            self.assertTrue(name)
            self.assertGreaterEqual(value, settings.GAIN_MIN)
            self.assertLessEqual(value, settings.GAIN_MAX)

    def test_bad_value_does_not_raise(self):
        with _TempHome():
            s = settings.Settings.load()
            self.assertEqual(s.set_gain(None), 1.0)
            self.assertEqual(s.set_gain("abc"), 1.0)


class PositionTests(unittest.TestCase):
    def test_clear_position(self):
        with _TempHome():
            s = settings.Settings.load()
            s["panel_x"], s["panel_y"] = 500, 300
            s.save()
            s.clear_position()
            self.assertIsNone(s["panel_x"])
            self.assertIsNone(s["panel_y"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
