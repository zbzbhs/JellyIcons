# -*- coding: utf-8 -*-
"""用户设置：Q 弹程度、自动轮换、音频设备、模式、面板位置。

为什么需要这一层：v1.7 之前所有手感参数都是 `config.py` 里的常量，
用户想调"再弹一点/再稳一点"只能改代码。现在把**真正需要现场调**的
那几个做成运行时可变，并且落盘到 `%LOCALAPPDATA%\\JellyIcons\\settings.json`
（跟着 `paths.data_dir()` 走，源码运行时就在项目根）。

只存"用户意图"，不存派生值：`gain` 是一个倍率（1.0 = 出厂手感），
不是算好的像素宽度。这样以后改 `config.JELLY_GAIN_X` 的基准值时，
老用户的 settings.json 依然有意义。
"""
from __future__ import annotations

import json
import os
from . import paths
from .logutil import get_logger

log = get_logger()

FILE_NAME = "settings.json"

# Q 弹倍率的可调范围。上限受画布预留宽度约束（见 app._max_w）：
# 1.0 = 出厂（横向峰值 +16%）；2.0 = 明显夸张（横向 +30% 左右）；
# 0.3 = 只有轻微呼吸，适合长时间开着的场景。
GAIN_MIN = 0.3
GAIN_MAX = 2.0
GAIN_PRESETS = (("温柔", 0.55), ("标准", 1.0), ("Q 弹", 1.45), ("暴走", 2.0))

DEFAULTS = {
    "gain": 1.0,          # Q 弹程度倍率
    "auto": None,         # 自动轮换；None = 用 config.AUTO_SWITCH
    "mode": None,         # 上次用的模式；None = 用 config.DEFAULT_MODE
    "device": None,       # 上次的 loopback 设备索引
    "music_mode": None,   # 音乐模式开关；None = 按系统"隐藏图标"推断
    "panel_x": None,      # 面板位置（拖过才存）
    "panel_y": None,
}


def _path():
    return paths.data_path(FILE_NAME)


def _clamp_gain(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULTS["gain"]
    if v != v:                      # NaN
        return DEFAULTS["gain"]
    return max(GAIN_MIN, min(GAIN_MAX, v))


class Settings(dict):
    """带类型规整的 dict：读坏值不会崩，写出去永远是合法 JSON。"""

    def __init__(self, data=None):
        super().__init__()
        self.update(DEFAULTS)
        if data:
            self.update(data)
        self["gain"] = _clamp_gain(self.get("gain"))

    # ---- 读写 ----

    @classmethod
    def load(cls):
        path = _path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("settings.json 顶层不是对象")
            return cls(data)
        except FileNotFoundError:
            return cls()
        except Exception as exc:
            # 配置文件坏了不该阻止程序启动：记一行日志、用默认值继续。
            log.warning("[settings] 读取失败（%r），用默认值", exc)
            return cls()

    def save(self):
        path = _path()
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(dict(self), fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp, path)
            return True
        except Exception as exc:
            log.warning("[settings] 保存失败（%r）", exc)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            return False

    # ---- 便捷属性 ----

    @property
    def gain(self):
        return _clamp_gain(self.get("gain"))

    def set_gain(self, value):
        self["gain"] = _clamp_gain(value)
        return self["gain"]

    def clear_position(self):
        self["panel_x"] = None
        self["panel_y"] = None
