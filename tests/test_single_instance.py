# -*- coding: utf-8 -*-
"""单实例互斥：两个实例同时跑会互相覆盖心跳、互相恢复图标。

单测必须用**独立**的互斥体名字——用生产名会撞上用户正在跑的实例，
那时 acquire() 返回 False 是互斥体按设计生效，不是 bug。
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jellyicons.single_instance import DEFAULT_MUTEX_NAME, SingleInstance  # noqa: E402


def _test_name(tag):
    return "Local\\JellyIcons.Test.%s.%d" % (tag, os.getpid())


class SingleInstanceTests(unittest.TestCase):
    def test_second_acquire_fails(self):
        name = _test_name("second")
        first = SingleInstance(name)
        second = SingleInstance(name)
        try:
            self.assertTrue(first.acquire(), "第一个实例应拿到互斥量")
            self.assertFalse(second.acquire(), "第二个实例必须被拒绝")
        finally:
            first.release()
            second.release()

    def test_release_allows_reacquire(self):
        name = _test_name("reacquire")
        first = SingleInstance(name)
        self.assertTrue(first.acquire())
        first.release()
        second = SingleInstance(name)
        try:
            self.assertTrue(second.acquire(), "释放后应能重新获取")
        finally:
            second.release()

    def test_acquire_is_idempotent(self):
        inst = SingleInstance(_test_name("idempotent"))
        try:
            self.assertTrue(inst.acquire())
            self.assertTrue(inst.acquire(), "重复 acquire 不应自杀")
        finally:
            inst.release()

    def test_release_without_acquire_is_safe(self):
        SingleInstance(_test_name("noop")).release()

    def test_default_name_is_production(self):
        """默认名必须是生产名，否则真实运行不会互斥。"""
        self.assertEqual(SingleInstance()._name, DEFAULT_MUTEX_NAME)
        self.assertIn("JellyIcons", DEFAULT_MUTEX_NAME)


if __name__ == "__main__":
    unittest.main(verbosity=2)
