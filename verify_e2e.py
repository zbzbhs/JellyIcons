# -*- coding: utf-8 -*-
"""端到端验证：在进程内直接测量「真正画出去的那张图」。

早期版本用 PrintWindow 抓分层窗口，实测预检 False、9 秒只采到 8 帧
（PrintWindow 对 UpdateLayeredWindow 的表面抓不稳），高度序列
[0,1,99] 是"抓到/没抓到"而非形变本身，证据不够硬。

本版改为在 `App._compose` 出口处挂钩：每一帧真正送进
UpdateLayeredWindow 的画布都过一遍，量 alpha 墨迹的行跨度。
这直接度量渲染产物本身，不依赖窗口抓取。

判定（全过才算「确定可用」）：
  1 完整性 = Medium
  2 UIA 读到 >= 10 个图标，overlay 全部建好
  3 播放期间真实图标被隐藏（ListView 不可见）
  4 送出去的画布里，图标墨迹高度有连续变化，峰峰 >= 3px，且至少 3 个不同值
  5 全程 overlay 窗口 x 坐标不变（无横移）
  6 结束后真实图标恢复可见
"""
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np

from jellyicons.app import App
from jellyicons.music_mode import find_listview_hwnd
import ctypes
from ctypes import wintypes as W

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.IsWindowVisible.argtypes = [W.HWND]
user32.IsWindowVisible.restype = W.BOOL

REPORT = os.path.join(HERE, "_verify_report.json")


class FakeAudio:
    """合成低频：每 0.45s 一个强拍，模拟有节奏的音乐。"""
    available = True
    device_index = None
    _t0 = time.monotonic()
    _rng = np.random.default_rng(7)

    def open(self):
        return True

    def close(self):
        pass

    def bands(self):
        phase = ((time.monotonic() - FakeAudio._t0) % 0.45) / 0.45
        b = np.full(64, 0.02, dtype=np.float32)
        if phase < 0.22:
            b[0:10] = 0.50
            b[10:32] = 0.28
        else:
            b[0:10] = 0.05
        b += FakeAudio._rng.normal(0, 0.003, 64).astype(np.float32)
        return np.clip(b, 0.0, 1.0)

    def bass_level(self, bins=3):
        return float(self.bands()[0:bins].mean())

    def rms(self):
        return 0.3


def ink_rows(img):
    """画布里不透明像素的行跨度（alpha>16 才算有内容）。"""
    a = np.asarray(img.getchannel("A"))
    rows = np.where((a > 16).any(axis=1))[0]
    if len(rows) == 0:
        return 0
    return int(rows[-1] - rows[0] + 1)


def main():
    res = {}
    from jellyicons import integrity
    rid, il = integrity.current_integrity()
    res["integrity"] = il
    print("[v] 完整性 = %s" % il)

    def save_and_exit(code):
        with io.open(REPORT, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2, default=str)
        print("[v] 报告:", REPORT)
        return code

    if rid != 0x2000:
        print("[v] 不是 Medium，UIA 必然失败，中止")
        return save_and_exit(2)

    lv = find_listview_hwnd()
    res["listview"] = lv
    res["visible_before"] = bool(user32.IsWindowVisible(lv))
    print("[v] ListView=%s 可见=%s" % (lv, res["visible_before"]))

    # 挂钩 _compose：量真正要送出去的画布
    trace = {"ink": [], "t": [], "key": None, "hidden": []}
    orig_compose = App._compose

    def spy_compose(self, entry, *args, **kwargs):
        canvas, x, y = orig_compose(self, entry, *args, **kwargs)
        if trace["key"] is None or entry["key"] == trace["key"]:
            trace["key"] = entry["key"]
            trace["ink"].append(ink_rows(canvas))
            trace["t"].append(time.monotonic())
            trace["hidden"].append(bool(user32.IsWindowVisible(lv)) is False)
        return canvas, x, y

    App._compose = spy_compose
    try:
        app = App()
        app.audio = FakeAudio()
        xs_ref = None
        ok = app._sync_overlays()
        res["sync_ok"] = bool(ok)
        res["overlays"] = len(app.overlays)
        print("[v] 同步=%s overlays=%d" % (ok, len(app.overlays)))
        if not ok or len(app.overlays) < 10:
            print("[v] overlay 不足，中止")
            for e in app.overlays.values():
                try:
                    e["win"].close()
                except Exception:
                    pass
            return save_and_exit(3)

        xs_ref = {k: app.overlays[k]["geom"]["x"] for k in app.overlays}
        trace["key"] = None  # 让 spy 重新选一个样本
        app.run(duration=9.0)
        res["visible_after"] = bool(user32.IsWindowVisible(lv))
        res["xs_stable"] = all(
            app.overlays[k]["geom"]["x"] == xs_ref[k]
            for k in xs_ref if k in app.overlays)
    finally:
        App._compose = orig_compose

    ink = trace["ink"]
    res["sample_key"] = trace["key"]
    res["compose_frames"] = len(ink)
    print("[v] 采样画布 %d 帧（图标 %s）" % (len(ink), trace["key"]))
    if ink:
        res["ink_min"] = min(ink)
        res["ink_max"] = max(ink)
        res["swing"] = max(ink) - min(ink)
        res["distinct"] = len(set(ink))
        res["hidden_frames"] = sum(1 for h in trace["hidden"] if h)
        # 打印去重序列，肉眼能看出是连续起伏
        seq = []
        for h in ink:
            if not seq or seq[-1] != h:
                seq.append(h)
        res["ink_seq"] = seq[:40]
        print("[v] 墨迹 峰=%d 谷=%d 摆幅=%d 不同值=%d 隐藏帧=%d/%d"
              % (res["ink_max"], res["ink_min"], res["swing"],
                 res["distinct"], res["hidden_frames"], len(ink)))
        print("[v] 墨迹序列(去重相邻):", seq[:20])

    checks = {
        "完整性Medium": rid == 0x2000,
        "overlay足够": res.get("overlays", 0) >= 10,
        "音乐期隐藏真图标": res.get("hidden_frames", 0) > 0,
        "墨迹连续起伏>=3px": res.get("swing", 0) >= 3,
        "至少3个不同高度": res.get("distinct", 0) >= 3,
        "无横移": res.get("xs_stable", False),
        "退出后恢复": res.get("visible_after") is True,
    }
    res["checks"] = checks
    print()
    for k, v in checks.items():
        print("  %-20s %s" % (k, "OK" if v else "FAIL"))
    res["all_ok"] = all(checks.values())
    print("\n[v] 结论:", "确定可用" if res["all_ok"] else "未通过")
    return save_and_exit(0 if res["all_ok"] else 1)


if __name__ == "__main__":
    sys.exit(main())
