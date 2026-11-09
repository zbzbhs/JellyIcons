# -*- coding: utf-8 -*-
"""端到端冒烟：真 overlay 窗口 + 假桌面快照 + 假音乐检测。

沙箱里 UIA 读不到桌面（Low 完整性），所以布局用假数据驱动；
窗口、绘制、模式切换、双击命中全部走真实代码路径。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image

import jellyicons.app as app_mod
from jellyicons import music_mode
from jellyicons.desktop_reader import DesktopIcon

from jellyicons.logutil import get_logger
log = get_logger()


class FakeReader:
    def __init__(self, icons):
        self.icons = icons

    def snapshot(self):
        return list(self.icons)


class FakeMode(music_mode.MusicMode):
    """只翻转状态，不碰真实 ListView。"""

    def _enter_hidden(self):
        self.state = music_mode.STATE_HIDDEN
        log.info("[smoke] enter hidden")

    def _exit_hidden(self):
        self.state = music_mode.STATE_SHOWN
        log.info("[smoke] exit hidden")


def main():
    app = app_mod.App()
    app_mod.enable_dpi_awareness()
    app.reader = FakeReader([
        DesktopIcon("A", "记事本", (100, 100, 210, 169)),
        DesktopIcon("B", "此电脑", (220, 100, 330, 169)),
        DesktopIcon("C", "回收站", (340, 100, 450, 169)),
    ])
    app.icon_base = {n: Image.new("RGBA", (256, 256), (60, 140, 220, 255))
                     for n in ("记事本", "此电脑", "回收站")}
    app._side_est = 40
    app.music_mode = FakeMode(enabled=True)
    app._load_icons = lambda: None

    assert app._sync_overlays(), "同步失败"
    log.info("[smoke] overlays=%d", len(app.overlays))
    assert len(app.overlays) == 3
    assert app._desktop_keys == ["记事本", "此电脑", "回收站"]

    # 副本不完整时必须拒绝隐藏（宁可没特效，也不能空桌面）
    app._desktop_keys = ["记事本", "此电脑"]
    assert app._prime_before_hide(1.0, 1.0) is False, "覆盖率不足却允许隐藏"
    app._desktop_keys = ["记事本", "此电脑", "回收站"]

    # 隐藏前预绘制：窗口必须可见且已画过
    app._set_mode(True)
    assert app._prime_before_hide(1.0, 1.0) is True, "预绘制应成功"
    for key, e in app.overlays.items():
        assert e["_last_state"] is not None, key
        assert e["ready"] is True, key
    log.info("[smoke] 预绘制完成，全部窗口已可见")

    # 形变绘制
    drawn = app._draw_all(True, 1.06, 0.94)
    log.info("[smoke] 形变帧重绘 %d 个", drawn)
    assert drawn == 3

    # 同状态跳帧
    assert app._draw_all(True, 1.06, 0.94) == 0

    # 窗口坐标不随缩放变化
    xs = {e["geom"]["x"] for e in app.overlays.values()}
    app._draw_all(True, 1.10, 0.90)
    xs2 = {e["geom"]["x"] for e in app.overlays.values()}
    assert xs == xs2, "横向漂移"

    # ---- v1.6 双引擎：takeover 模式真的能位移，而且窗口坐标跟着位移走 ----
    from jellyicons.modes import Transform
    moved = {}
    for i, (key, e) in enumerate(app.overlays.items()):
        moved[key] = Transform(1.02, 0.96, dx=40.0 + i * 15, dy=-25.0 * (i + 1))
    base_x = {k: e["geom"]["x"] for k, e in app.overlays.items()}
    drawn = app._draw_all(True, 1.0, 1.0, moved)
    log.info("[smoke] takeover 帧重绘 %d 个", drawn)
    assert drawn == 3, "takeover 帧应该每个图标都重画"
    # 位移必须体现在窗口位置上（合成图的返回坐标 = geom + 位移）
    for key, e in app.overlays.items():
        want_x = base_x[key] + int(round(moved[key].dx))
        got_x = e["_last_state"][0]
        assert got_x == want_x, "%s 位移没生效: %s != %s" % (key, got_x, want_x)
    log.info("[smoke] takeover 位移已生效")

    # 再画同一个 takeover 帧必须跳帧（签名相同）
    assert app._draw_all(True, 1.0, 1.0, moved) == 0, "同签名不该重绘"

    # 归位：所有形变回到 1:1 后，坐标必须回到原始位置
    rest = {k: Transform() for k in app.overlays}
    assert app._all_rest(rest) is True
    app._draw_all(True, 1.0, 1.0, rest)
    for key, e in app.overlays.items():
        assert e["_last_state"][0] == base_x[key], "%s 没有归位" % key
    log.info("[smoke] 归位正确")

    # 双击命中
    assert app._hit_test(150, 130) is not None
    assert app._hit_test(5, 5) is None
    log.info("[smoke] 命中测试通过")

    # 退出：保留 0.12s 后隐藏
    app._set_mode(False)
    app._exit_hold = time.perf_counter() - 1.0
    app._draw_all(False, 1.0, 1.0)
    for e in app.overlays.values():
        assert e["_last_state"] is None
    log.info("[smoke] 退出后副本已隐藏")

    app.close()
    log.info("[smoke] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
