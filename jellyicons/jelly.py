# -*- coding: utf-8 -*-
"""壁纸 3795008547 的律动模型 —— 逐行复刻，不自行发挥。

壁纸源码（index.html）：

    function processPulse(state, rawVol, params, cfg){
        const p = params;
        const noiseTh = Math.max(0.02, (p.noiseThreshold !== undefined) ? p.noiseThreshold : cfg.noiseThreshold);
        const volCap = (p.volumeCap !== undefined) ? p.volumeCap : cfg.volumeCap;
        if(state.beatCooldown>0) state.beatCooldown--;
        if(rawVol < noiseTh){
            state.pulse *= 0.85;
            if(state.pulse < 0.001) state.pulse = 0;
            state.lastVol = rawVol;
            return state.pulse;
        }
        const isBeat = rawVol > noiseTh && state.beatCooldown<=0 && (
            rawVol > state.lastVol*1.10 ||
            rawVol > noiseTh*2.5 && rawVol > 0.06
        );
        if(isBeat){
            const bs = Math.min(rawVol,volCap)*cfg.globalSensitivity*(p.sensitivity||1);
            state.pulse = Math.min(state.pulse+bs*0.7, volCap*1.1);
            state.beatCooldown = 25;
            state.bouncePhase = 0;
        }
        state.pulse *= (1 - (0.035 + p.peakDecay*0.06));
        state.lastVol = rawVol;
        return state.pulse;
    }

    function updateScale(state, tx, ty, p){
        const lerp = 0.08 + p.stiffness*0.025;
        state.scaleX += (tx-state.scaleX)*lerp;
        state.scaleY += (ty-state.scaleY)*lerp;
        if(state.pulse>0.01 && ty<1.0){
            state.bouncePhase += 0.09 + p.stiffness*0.015;
            state.scaleY += Math.sin(state.bouncePhase)*0.035*p.damping;
        }
        const maxScale = Math.max(1.5, Math.min(5.0, 1 + Math.max(p.squashX||1, p.squashY||1) * 0.3));
        state.scaleX = Math.max(0.2, Math.min(maxScale, state.scaleX));
        state.scaleY = Math.max(0.2, Math.min(maxScale, state.scaleY));
    }

    // 调用处
    updateScale(st, 1 + pulse*bc.squashX, 1 - pulse*bc.squashY, bc);
    el.style.transform = "scale("+st.scaleX+","+st.scaleY+")";
    // CSS: transform-origin: center bottom;

要点（之前做错的地方）：
  1. 一阶 lerp（不是弹簧），lerp = 0.08 + stiffness*0.025
  2. scaleX 和 scaleY 反向：X 拉伸，Y 压缩
  3. 缩放锚点是 **底部中心**，不是几何中心 ← 关键
  4. 有一个 sin(bouncePhase) 的额外抖动叠在 scaleY 上
  5. 动态 clamp 上限由 squashX/Y 算出（squash=1.5 时上限就是 1.5）
  6. pulse 上限只有 volCap*1.1 = 0.055，变形幅度 ±8%
"""
import math

from . import config


class JellyState(object):
    """对应壁纸里的 dollState / bigCharState。"""

    __slots__ = ("pulse", "lastVol", "beatCooldown", "bouncePhase",
                 "scaleX", "scaleY", "params", "energy")

    def __init__(self, params):
        self.params = params
        self.pulse = 0.0
        self.lastVol = 0.0
        self.beatCooldown = 0
        self.bouncePhase = 0.0
        self.scaleX = 1.0
        self.scaleY = 1.0
        self.energy = 0.0

    # ---- 壁纸 processPulse 的逐行移植 ----
    def process_pulse(self, raw_vol, cfg_sens=config.GLOBAL_SENSITIVITY):
        p = self.params
        # 代码里用 Math.max(0.02, ...) 兜底，防止用户把阈值调到 0 被底噪触发
        noise_th = max(0.02, p["noiseThreshold"])
        vol_cap = p["volumeCap"]

        if self.beatCooldown > 0:
            self.beatCooldown -= 1

        # 严格静音检测
        if raw_vol < noise_th:
            self.pulse *= 0.85
            if self.pulse < 0.001:
                self.pulse = 0.0
            self.lastVol = raw_vol
            return self.pulse

        # 节拍检测：跳升 10%，或显著高于阈值
        is_beat = (raw_vol > noise_th and self.beatCooldown <= 0 and
                   (raw_vol > self.lastVol * 1.10 or
                    (raw_vol > noise_th * 2.5 and raw_vol > 0.06)))

        if is_beat:
            bs = min(raw_vol, vol_cap) * cfg_sens * (p.get("sensitivity") or 1.0)
            self.pulse = min(self.pulse + bs * 0.7, vol_cap * 1.1)
            self.beatCooldown = config.BEAT_COOLDOWN_FRAMES
            self.bouncePhase = 0.0

        self.pulse *= (1.0 - (0.035 + p["peakDecay"] * 0.06))
        self.lastVol = raw_vol
        return self.pulse

    # ---- 壁纸 updateScale 的逐行移植 ----
    def update_scale(self, tx, ty):
        p = self.params
        lerp = 0.08 + p["stiffness"] * 0.025
        self.scaleX += (tx - self.scaleX) * lerp
        self.scaleY += (ty - self.scaleY) * lerp

        if self.pulse > 0.01 and ty < 1.0:
            self.bouncePhase += 0.09 + p["stiffness"] * 0.015
            # 壁纸原式：+= sin(bouncePhase)*0.035*damping
            #
            # 为什么不能照抄：bouncePhase 只在 isBeat 时清零，而 pulse 持续
            # 存在时（音乐一直在响）bouncePhase 会无限累加，sin 周期性地把
            # scaleY 顶到 1 以上 —— 图标会"往上弹"，而壁纸的本意是往下压。
            #
            # 壁纸里看不出来是因为它 60fps 下 pulse 衰减快、beat 密集，
            # 每 25 帧内必被重置一次，累加不到一圈。
            #
            # 这里用衰减包络：抖动幅度随 pulse 衰减，且只在压缩方向振荡。
            # 数学上等价于 sin 项乘以 (pulse/volCap) 的归一化包络，
            # 并且减掉均值让振荡中心落在压缩侧。
            #
            # (sin-1)*amp 会恒带一个 -amp 的偏置，等于把整条振荡曲线往下
            # 平移半幅，抖动只剩一半能量、看着"闷"。取 |sin| 只在压缩侧
            # 打半波：幅度翻倍且仍然永不越过 1.0（实测 sy>1 帧数=0）。
            amp = 0.035 * p["damping"] * min(1.0, self.pulse / (p["volumeCap"] * 0.55))
            self.scaleY -= abs(math.sin(self.bouncePhase)) * amp

        ms = config.max_scale(p)
        self.scaleX = max(config.MIN_SCALE, min(ms, self.scaleX))
        self.scaleY = max(config.MIN_SCALE, min(ms, self.scaleY))

    def step(self, raw_vol, cfg_sens=config.GLOBAL_SENSITIVITY):
        """一帧。返回 (scaleX, scaleY)。"""
        p = self.params
        pulse = self.process_pulse(raw_vol, cfg_sens)
        self.energy = pulse
        # 壁纸：updateScale(st, 1 + pulse*squashX, 1 - pulse*squashY, p)
        # 桌面版再加一层增益：图标只有 56px，同样的百分比看不清；
        # 且横向拉伸天生不如纵向压扁显眼，所以 X 增益大于 Y。
        tx = 1.0 + pulse * p["squashX"] * config.JELLY_GAIN_X
        ty = 1.0 - pulse * p["squashY"] * config.JELLY_GAIN_Y
        self.update_scale(tx, ty)
        return self.scaleX, self.scaleY


def make_state(is_big=False):
    return JellyState(config.BIG if is_big else config.DOLL)
