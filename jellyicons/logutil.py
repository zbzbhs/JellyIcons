# -*- coding: utf-8 -*-
"""日志：同时写控制台和 JellyIcons.log（静默启动时唯一可追溯途径）。

RotatingFileHandler：单文件 1 MB、保留 3 个备份，长期运行不会无限增长。
"""
import logging
import logging.handlers
import os
import sys

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "JellyIcons.log"
)
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
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt_cons)
    logger.addHandler(sh)
    return logger


def new_session(title: str):
    """在日志文件里划一条会话分隔线。"""
    logger = get_logger()
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)
