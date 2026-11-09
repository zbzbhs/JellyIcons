"""模式共用的小工具。"""
from __future__ import annotations

import math


def approach(cur, target, rate, dt):
    """帧率无关的指数逼近：rate 越大追得越快。"""
    if rate <= 0.0:
        return target
    return target + (cur - target) * math.exp(-rate * dt)


def clamp(value, lo, hi):
    return lo if value < lo else (hi if value > hi else value)


def lerp(a, b, t):
    return a + (b - a) * t


def sustain(presence, on, off):
    """把 presence 换成 0..1 的"参与度"目标：过 on 就 1，低于 off 就 0。"""
    if presence >= on:
        return 1.0
    if presence <= off:
        return 0.0
    return (presence - off) / max(1e-6, on - off)
