# -*- coding: utf-8 -*-
"""看门狗：主进程被强杀（taskkill /F、断电重启 explorer 等）后恢复图标。

设计（吸收旧工程强杀测试的教训）：
  - 主进程启动时以 DETACHED_PROCESS 拉起本脚本作为独立子进程。
  - 心跳文件记录：主 PID、listview 是否处于"被我们隐藏"状态、时间戳。
  - 主进程每帧刷新心跳；看门狗发现心跳停止（主进程死亡/挂死）且
    listview 处于隐藏态时，重查句柄并 ShowWindow(SW_SHOW) 恢复。
  - 主进程正常退出时删除心跳文件并显式唤醒看门狗退出，看门狗
    0.5s 内跟随退出；异常路径下最多 _PATIENCE_S 秒后自恢复。
  - 看门狗自己绝不做任何其他事：不写注册表、不碰其他窗口。

用法（被 app.py 以子进程方式启动）：
  python -X utf8 -m jellyicons.watchdog
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .logutil import get_logger
from . import paths

log = get_logger()

WATCHDOG_TICK_S = 0.5       # 轮询周期
HEARTBEAT_STALE_S = 1.5     # 心跳过期阈值：主进程超过此时间未刷新视为死亡
EXIT_GRACE_S = 2.0          # 主进程退出标记出现后看门狗最长存活

# 心跳文件：主进程写、看门狗读。JSON 单行，覆盖写。
# 必须在可写目录（exe 下是 exe 同级或 %LOCALAPPDATA%），主进程与看门狗
# 各自调用 paths.data_dir() 会得到同一个答案。
WATCH_DIR = paths.data_dir()
HEARTBEAT_PATH = Path(WATCH_DIR) / ".heartbeat.json"


def read_heartbeat():
    """返回 dict 或 None。字段：pid, hidden, ts。

    注意：主进程每帧（60fps）都在重写这个文件。非原子写入会让读端
    抓到"已截断但还没写完"的空文件，从而误判成"主进程正常退出"，
    看门狗就会提前退出、失去强杀保护。所以写入走临时文件 + 原子
    替换（见 write_heartbeat），这里再补一次重试兜底。
    """
    for _attempt in (0, 1):
        try:
            import json
            text = HEARTBEAT_PATH.read_text(encoding="utf-8").strip()
            if not text:
                return None
            data = json.loads(text)
            if not isinstance(data, dict):
                return None
            return data
        except FileNotFoundError:
            return None
        except Exception:
            continue      # 可能撞上并发写入，重试一次
    return None


def write_heartbeat(pid: int, hidden: bool):
    """主进程调用；失败静默（心跳文件不可用时不影响功能）。

    必须原子：先写临时文件再 os.replace。直接 write_text 会先截断，
    并发读到空文件的看门狗会误判主进程已退出。
    """
    try:
        import json
        tmp = HEARTBEAT_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"pid": pid, "hidden": bool(hidden),
                       "ts": time.time()}),
            encoding="utf-8")
        os.replace(str(tmp), str(HEARTBEAT_PATH))
    except Exception:
        pass


def clear_heartbeat():
    try:
        HEARTBEAT_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def main():
    log.info("[watchdog] 看门狗启动，监控 %s", HEARTBEAT_PATH)
    if not HEARTBEAT_PATH.exists():
        # 主进程还没来得及写第一次心跳 —— 等一小段时间，超时退出
        deadline = time.time() + 5.0
        while time.time() < deadline and not HEARTBEAT_PATH.exists():
            time.sleep(WATCHDOG_TICK_S)
        if not HEARTBEAT_PATH.exists():
            log.info("[watchdog] 无心跳文件，退出")
            return

    last_pid_alive_check = 0.0
    while True:
        time.sleep(WATCHDOG_TICK_S)
        hb = read_heartbeat()
        if hb is None:
            if HEARTBEAT_PATH.exists():
                # 文件在但读不出来 = 主进程正在写（并发/半截）。
                # 绝不能当成"主进程已退出"，否则强杀保护会提前失效。
                continue
            log.info("[watchdog] 心跳已清除（主进程正常退出），看门狗退出")
            return
        ts = float(hb.get("ts", 0))
        pid = int(hb.get("pid", 0))
        hidden = bool(hb.get("hidden", False))
        now = time.time()
        # 系统休眠唤醒后时钟可能回拨/跳变，用文件时间戳做绝对基准
        stale = (now - ts) > HEARTBEAT_STALE_S
        if not stale:
            last_pid_alive_check = now
            continue
        # 主进程疑似死亡/挂死
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            h = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if h:
                kernel32.CloseHandle(h)
                alive = True
            else:
                alive = False
        except Exception:
            alive = False
        if alive and (now - last_pid_alive_check) < EXIT_GRACE_S:
            continue  # 进程在但心跳挂了：给一个宽限期让主进程自救
        if hidden:
            log.warning("[watchdog] 主进程失联且图标处于隐藏态，恢复显示")
            from .music_mode import find_listview_hwnd
            import ctypes
            u = ctypes.windll.user32
            hwnd = find_listview_hwnd()
            if hwnd:
                u.ShowWindow(hwnd, 5)  # SW_SHOW
                log.info("[watchdog] 已恢复显示（hwnd=%s）", hwnd)
            else:
                log.error("[watchdog] 找不到桌面 ListView，"
                          "请手动右键桌面→查看→显示桌面图标")
        clear_heartbeat()
        return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("[watchdog] 异常退出")
    sys.exit(0)
