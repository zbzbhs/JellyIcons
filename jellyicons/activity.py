# -*- coding: utf-8 -*-
"""音频活动度检测 + 逐频段自动增益。

为什么需要这一层（v1.2.0 实测数据）：
    AudioEngine 把 64 段频谱除以"全频段最大峰值"归一化，低频段被中高频
    压住，音乐播放时 bass 中位数只有 0.011、p75 才 0.040。
    - 拿它当音乐开关 → 要连续 0.75s 高于 0.03，实际要好几秒才凑够，
      用户看到的就是"播放了一会才隐藏"。
    - 拿它当 Q 弹驱动 → 壁纸公式要 rawVol≈0.05 才顶到形变上限，
      0.011 只做出 ±1.5% 的形变，看着像没反应。

Wallpaper Engine 给壁纸的 audioData 是它自己做过 AGC 的 64 段数据，
低频常年在 0.3~1.0。这里复刻那一步：每个频段各自跟踪自己的峰值、
慢衰减、再归一化。于是
    - 有音乐时 bass 稳定落在 0.3~1.0（律动做得出来）
    - 静音时全部趋 0（开关判得准）
"""
from __future__ import annotations

import numpy as np

from . import config


class ActivityDetector(object):
    """输入原始 64 段频谱，输出 (bass, presence)。

    bass     —— 逐频段 AGC 之后的低频能量（0..1），喂给 jelly 做形变。
    presence —— 包络平滑后的"有没有声音"（0..1），喂给音乐模式做开关。
    """

    def __init__(self, num_bands: int = 64):
        self.num_bands = num_bands
        self._peak = np.full(num_bands, config.AGC_FLOOR, dtype=np.float32)
        self._bass_env = 0.0
        self._level_env = 0.0
        self.bass = 0.0
        self.presence = 0.0
        # 每帧（60fps）衰减换算成每秒衰减
        self._decay_per_s = float(config.AGC_DECAY) ** 60.0

    def reset(self) -> None:
        self._peak[:] = config.AGC_FLOOR
        self._bass_env = 0.0
        self._level_env = 0.0
        self.bass = 0.0
        self.presence = 0.0

    def _agc(self, bands: np.ndarray, dt: float) -> np.ndarray:
        """逐频段归一化：峰值快跟、慢衰减，等价壁纸拿到的 audioData。"""
        if bands.size != self._peak.size:
            self._peak = np.full(bands.size, config.AGC_FLOOR,
                                 dtype=np.float32)
        decay = self._decay_per_s ** max(1e-4, dt)
        np.multiply(self._peak, decay, out=self._peak)
        np.maximum(self._peak, bands, out=self._peak)
        np.maximum(self._peak, config.AGC_FLOOR, out=self._peak)
        norm = np.clip(bands / self._peak, 0.0, 1.0)
        # 绝对噪声门：AGC 的增益是相对的，耳机底噪(~0.0005)也会被放大到
        # 0.025 并越过开阈值。门在归一化之后、按原始幅度判。
        norm[bands < config.AGC_GATE] = 0.0
        return norm

    @staticmethod
    def _envelope(current: float, target: float, dt: float) -> float:
        """attack 快、release 慢：节拍间隙里不会瞬间掉到 0。"""
        span = (config.ENV_ATTACK_S if target > current
                else config.ENV_RELEASE_S)
        alpha = 1.0 if span <= 0 else min(1.0, dt / span)
        return current + (target - current) * alpha

    def update(self, bands: np.ndarray, dt: float) -> tuple[float, float]:
        if bands is None or not len(bands):
            return self.bass, self.presence
        norm = self._agc(np.asarray(bands, dtype=np.float32), dt)
        bass_now = float(norm[:config.BASS_BINS].mean())
        level_now = float(norm.mean())

        self._bass_env = self._envelope(self._bass_env, bass_now, dt)
        self._level_env = self._envelope(self._level_env, level_now, dt)
        self.bass = min(1.0, self._bass_env)
        self.presence = min(1.0, max(self._bass_env,
                                     self._level_env * config.LEVEL_WEIGHT))
        return self.bass, self.presence
