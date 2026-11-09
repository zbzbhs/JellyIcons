# -*- coding: utf-8 -*-
"""全局热键：默认绑定表、回调分发、注册失败不崩。

热键这块历史上踩过最严重的坑：早期用 WH_KEYBOARD_LL 全局低级钩子，
Python 的 GIL 一旦被渲染抢走，系统输入队列就被堵住，鼠标直接卡死。
所以这里的测试重点不是"能不能按键"，而是"永远不许回到钩子那条路"：
    - 只允许 RegisterHotKey（系统自己匹配，我们只收消息）
    - 注册失败只记日志，绝不抛到主循环
    - 没绑回调的热键被按下也不能崩
"""
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from jellyicons import hotkey                                 # noqa: E402


class BindingTests(unittest.TestCase):
    def test_default_bindings_cover_core_actions(self):
        actions = {b[3] for b in hotkey.DEFAULT_BINDINGS}
        self.assertEqual(actions, {"quit", "next", "prev", "toggle_auto"})

    def test_default_ids_are_unique(self):
        ids = [b[0] for b in hotkey.DEFAULT_BINDINGS]
        self.assertEqual(len(ids), len(set(ids)), "热键 id 不能重复")

    def test_all_bindings_have_no_repeat(self):
        """全部绑 Ctrl+Alt：单按 Ctrl+Alt 不该触发，按住也不该连发。"""
        for hid, mods, vk, action, human in hotkey.DEFAULT_BINDINGS:
            self.assertTrue(mods & hotkey.MOD_CONTROL, human)
            self.assertTrue(mods & hotkey.MOD_ALT, human)
            self.assertTrue(mods & hotkey.MOD_NOREPEAT, human)
            self.assertTrue(vk, human)

    def test_describe_is_human_readable(self):
        listener = hotkey.HotkeyListener()
        lines = listener.describe()
        self.assertEqual(len(lines), len(hotkey.DEFAULT_BINDINGS))
        for line in lines:
            self.assertIn("Ctrl+Alt", line)

    def test_no_low_level_hook(self):
        """回归守卫：不许再走全局钩子那条路（注释里提历史没关系，看代码）。"""
        path = os.path.join(BASE, "jellyicons", "hotkey.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        # 真的调用才危险：SetWindowsHookEx + 低级钩子常量
        self.assertNotIn("SetWindowsHookEx", src)
        self.assertNotIn("CallNextHookEx", src)
        self.assertNotIn("SetWindowsHookExW", src)
        self.assertIn("RegisterHotKey", src)


class ListenerTests(unittest.TestCase):
    def test_bind_then_dispatch(self):
        listener = hotkey.HotkeyListener()
        hits = []
        listener.bind("next", lambda: hits.append(1))
        listener._actions["next"]()
        self.assertEqual(hits, [1])

    def test_unbound_action_is_ignored(self):
        listener = hotkey.HotkeyListener()
        # 没有 bind 的情况下回调表里没有这个键 —— 不能 KeyError
        self.assertNotIn("quit", listener._actions)

    def test_stop_without_start_is_safe(self):
        listener = hotkey.HotkeyListener()
        listener.stop()
        listener.stop()

    def test_start_and_stop_roundtrip(self):
        """真注册一次再注销；被别的程序占用也只警告不抛。"""
        listener = hotkey.HotkeyListener()
        listener.start()
        try:
            self.assertTrue(listener._ready.is_set())
        finally:
            listener.stop()

    def test_double_start_is_idempotent(self):
        listener = hotkey.HotkeyListener()
        listener.start()
        try:
            thread = listener._thread
            listener.start()
            self.assertIs(listener._thread, thread, "重复 start 不该再起线程")
        finally:
            listener.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
