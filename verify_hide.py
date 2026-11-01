# -*- coding: utf-8 -*-
"""真实 ListView 隐藏/恢复验证（一次性，脚本内保证 finally 恢复）。

这不是单元测试：它会短暂隐藏真实桌面图标，用来确认音乐模式实际
走的两个 API 在当前会话里真的有效。任何异常都会在 finally 里恢复。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jellyicons import music_mode  # noqa: E402
from jellyicons.logutil import get_logger  # noqa: E402

log = get_logger()


def main():
    hwnd = music_mode.find_listview_hwnd()
    if not hwnd:
        log.error("[verify] 找不到 SysListView32（explorer 没跑？）")
        return 1
    u32 = music_mode.user32
    log.info("[verify] ListView=0x%X 初始可见=%s",
             hwnd, bool(u32.IsWindowVisible(hwnd)))
    if not u32.IsWindowVisible(hwnd):
        log.error("[verify] 初始就是隐藏状态，跳过测试以免搞混")
        return 1

    mode = music_mode.MusicMode(enabled=True)
    mode._last_hide_attempt = float("-inf")
    ok = False
    try:
        ok = mode._enter_hidden()
        time.sleep(0.3)
        hidden_now = not u32.IsWindowVisible(hwnd)
        log.info("[verify] 隐藏调用返回=%s 实际隐藏=%s", ok, hidden_now)
        if not hidden_now:
            log.error("[verify] 隐藏没有生效")
            return 1
        mode.state = music_mode.STATE_HIDDEN
        mode._hide_succeeded = True
    finally:
        restored = mode.restore()
        time.sleep(0.2)
        visible_now = bool(u32.IsWindowVisible(hwnd))
        log.info("[verify] 恢复返回=%s 实际可见=%s", restored, visible_now)

    if not visible_now:
        log.error("[verify] 恢复失败！请手动右键桌面→查看→显示桌面图标")
        return 1
    log.info("[verify] 通过：隐藏/恢复都真实生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
