# -*- coding: utf-8 -*-
"""单实例互斥：两个实例同时跑会互相覆盖心跳、互相恢复图标。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jellyicons.single_instance import SingleInstance  # noqa: E402


class SingleInstanceTests(unittest.TestCase):
    def test_second_acquire_fails(self):
        first = SingleInstance()
        second = SingleInstance()
        try:
            self.assertTrue(first.acquire(), "第一个实例应拿到互斥量")
            self.assertFalse(second.acquire(), "第二个实例必须被拒绝")
        finally:
            first.release()
            second.release()

    def test_release_allows_reacquire(self):
        first = SingleInstance()
        self.assertTrue(first.acquire())
        first.release()
        second = SingleInstance()
        try:
            self.assertTrue(second.acquire(), "释放后应能重新获取")
        finally:
            second.release()

    def test_acquire_is_idempotent(self):
        inst = SingleInstance()
        try:
            self.assertTrue(inst.acquire())
            self.assertTrue(inst.acquire(), "重复 acquire 不应自杀")
        finally:
            inst.release()

    def test_release_without_acquire_is_safe(self):
        SingleInstance().release()


if __name__ == "__main__":
    unittest.main(verbosity=2)
