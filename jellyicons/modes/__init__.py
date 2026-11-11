"""十四种动画模式。

分两档引擎（见 base.py）：

  overlay（不位移，真图标始终可见，鼠标永远点原生图标）
      律动 JellyMode     —— 壁纸原味：压扁、回弹、摇摆
      音浪 BandsMode     —— 八个频段各跳各的
      烟花 FireworkMode  —— 重拍绽放，轻轻收回
      多米诺 DominoMode  —— 骨牌从左上推过去，依次倒下再弹起
      呼吸 BreathMode    —— 同心圆从中心扩散，最安静的一档

  takeover（音乐期间隐藏真图标，副本自己排版；退出必归位）
      自由 FreeMode      —— 随鼓点散开再聚拢，顺时针流动
      心动 HeartMode     —— 沿爱心轨迹流动，一张一弛
      海浪 WaveMode      —— 波峰错开，起伏传递
      星环 RingMode      —— 层层旋转，随节奏舒展
      两年半 KunMode     —— 图标拼小人，运球、左右靠
      拼字 SpellMode     —— 把字渲染成掩膜，图标当像素拼出来
      弹球 BallMode      —— 一颗球四处弹，撞到谁谁歪
      鼠标引力 GravityMode —— 图标被鼠标吸过去、放大
      放大镜 LensMode    —— 只放大不位移，鼠标当透镜
"""
from __future__ import annotations

from .base import (ENGINE_OVERLAY, ENGINE_TAKEOVER, ENGINES, Mode,
                   ModeContext, Transform)
from .ball import BallMode
from .bands import BandsMode
from .breath import BreathMode
from .domino import DominoMode
from .firework import FireworkMode
from .free import FreeMode
from .gravity import GravityMode, LensMode
from .heart import HeartMode
from .jelly import JellyMode
from .kun import KunMode
from .ring import RingMode
from .spell import SpellMode
from .wave import WaveMode

ALL_MODES = (
    JellyMode, FreeMode, KunMode, HeartMode,
    BandsMode, WaveMode, RingMode, FireworkMode,
    SpellMode, BallMode, GravityMode, LensMode,
    DominoMode, BreathMode,
)

BY_NAME = {cls.name: cls for cls in ALL_MODES}


def create(name):
    """按名字造一个模式实例。"""
    cls = BY_NAME.get(name)
    if cls is None:
        raise KeyError("未知模式: %r（可用: %s）"
                       % (name, ", ".join(sorted(BY_NAME))))
    return cls()


def names():
    return [cls.name for cls in ALL_MODES]


__all__ = [
    "ALL_MODES", "BY_NAME", "BallMode", "BandsMode", "BreathMode",
    "DominoMode", "ENGINE_OVERLAY", "ENGINE_TAKEOVER", "ENGINES",
    "FireworkMode", "FreeMode", "GravityMode", "HeartMode", "JellyMode",
    "KunMode", "LensMode", "Mode", "ModeContext", "RingMode", "SpellMode",
    "Transform", "WaveMode", "create", "names",
]
