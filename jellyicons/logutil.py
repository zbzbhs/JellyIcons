# -*- coding: utf-8 -*-
"""日志：同时写控制台和 JellyIcons.log（静默启动时唯一可追溯途径）。

RotatingFileHandler：单文件 1 MB、保留 3 个备份，长期运行不会无限增长。
"""
import logging
import logging.handlers
import os
import sys

from . import paths

# 打包成 exe 后 __file__ 在只读的临时目录里，日志必须写到 paths.data_dir()。
_LOG_PATH = os.path.join(paths.data_dir(), "JellyIcons.log")
_MAX_BYTES = 1_000_000
_BACKUPS = 3


def log_path() -> str:
    return _LOG_PATH


def get_logger():
    logger = logging.getLogger("jellyicons")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt_file = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    fmt_cons = logging.Formatter("%(message)s")
    try:
        fh = logging.handlers.RotatingFileHandler(
            _LOG_PATH, maxBytes=_MAX_BYTES, backupCount=_BACKUPS,
            encoding="utf-8")
        fh.setFormatter(fmt_file)
        logger.addHandler(fh)
    except OSError:
        pass  # 日志文件都写不进去时至少还有控制台
    # --windowed 打包时 sys.stdout 是 None，StreamHandler(None) 会在
    # emit() 里对 None 调 write → 每条日志抛 AttributeError。只有真的
    # 有控制台流时才挂这个 handler。
    stream = sys.stdout or sys.stderr
    if stream is not None:
        sh = logging.StreamHandler(stream)
        sh.setFormatter(fmt_cons)
        logger.addHandler(sh)
    return logger


def new_session(title: str):
    """在日志文件里划一条会话分隔线。"""
    logger = get_logger()
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)
