# -*- coding: utf-8 -*-
"""参数与几何 —— 全部取自壁纸 3795008547 的 project.json（实际生效值）。

关键：project.json 里的 value 才是用户实际使用的值，index.html 里的
GLOBAL_CONFIG 只是代码默认值，两者不同。之前用错的就是这一点。

    dollvolumecap        = 0.05     (index.html 默认 0.20)
    bignoisethreshold    = 0.05
    globalSensitivity    = 0.9      (index.html 默认 1.0)
    dollSensitivity      = 0.95
    dollSquashX/Y        = 1.5
    dollStiffness        = 3
    dollDamping          = 0.85
    dollPeakDecay        = 0.32

pulse 上限 = volCap*1.1 = 0.055
=> scaleX 最大 1 + 0.055*1.5 = 1.0825
=> scaleY 最小 1 - 0.055*1.5 = 0.9175

也就是说壁纸的真实变形幅度只有 ±8%，非常克制。之前把 MAX_SCALE 设成 1.9、
把 pulse 撑到 0.2，所以看起来像乱抖而不是 Q 弹。
"""

# ---- 壁纸实际生效参数（来自 project.json）----
DOLL = dict(
    squashX=1.5,
    squashY=1.5,
    stiffness=3.0,
    damping=0.85,
    peakDecay=0.32,
    sensitivity=0.95,
    noiseThreshold=0.02,     # 代码里 Math.max(0.02, ...) 兜底
    volumeCap=0.05,          # ★ project.json 实际值
)

BIG = dict(
    squashX=1.4,
    squashY=1.4,
    stiffness=2.8,
    damping=0.85,
    peakDecay=0.30,
    sensitivity=1.0,
    noiseThreshold=0.05,
    volumeCap=0.05,          # ★ project.json 实际值
)

GLOBAL_SENSITIVITY = 0.9     # ★ project.json 实际值

# 壁纸里 beat 冷却 25 帧
BEAT_COOLDOWN_FRAMES = 25

# 壁纸取 audioData[0..2] 的均值当低频
BASS_BINS = 3


def max_scale(params):
    """壁纸自己的动态 clamp：max(1.5, min(5.0, 1 + max(squashX,squashY)*0.3))。"""
    return max(1.5, min(5.0, 1.0 + max(params["squashX"], params["squashY"]) * 0.3))


MIN_SCALE = 0.2

# ---- 桌面图标几何 ----
# 壁纸用 transform-origin:center bottom —— 底部中心固定，顶部往下压。
# 这是"果冻落地"感觉的来源，不是中心缩放。
ANCHOR = "center bottom"

ICON_PIXMAP = 256
# 图标本体在格子里的顶部内边距（像素）。原生桌面图标顶部留白固定，
# 不随图标尺寸/DPI 变化；用来定位本体底边 = 格子顶 + 该值 + 本体边长。
ICON_TOP_PAD = 6
TEXT_FONT_FAMILY = "Microsoft YaHei UI"
TEXT_FONT_PX = 15
TEXT_LINE_GAP = 2
TEXT_MAX_LINES = 2
TEXT_COLOR = (255, 255, 255)

FPS = 60
IDLE_FPS = 15           # 真图标显示时不做动画，降低 UIA/音频/消息处理频率
AUDIO_STALE_S = 0.5     # 回调中断超过这个时间就按静音，不能重复旧缓冲
AUDIO_RETRY_S = 2.0

# ---- 音乐模式（自动隐藏真实图标，音乐停止后恢复）----
# 输入不再是瞬时 bass，而是 ActivityDetector 输出的 presence（0..1）。
# 它已经过 attack/release 包络 + 逐频段 AGC，中位数从 0.011 提到 0.3+，
# 所以这里的阈值可以直接卡在"有声音/没声音"的分界上，不用等好几秒。
# 开：presence ≥ ON 持续 ON_HOLD 秒（约 0.15s，几乎无延迟）
# 关：presence ≤ OFF 持续 OFF_HOLD 秒（防节拍间隙闪烁）
MUSIC_ON_THRESHOLD = 0.02
MUSIC_ON_HOLD_S = 0.15
MUSIC_OFF_THRESHOLD = 0.008
MUSIC_OFF_HOLD_S = 1.0

# ---- 音频活动度检测 ----
# attack 快、release 慢：节拍间隙里包络不会立刻掉到 0
ENV_ATTACK_S = 0.06
ENV_RELEASE_S = 0.50
# 全频段能量对 presence 的贡献权重（低频为主，高频辅助判"有没有声音"）
LEVEL_WEIGHT = 0.8
# 逐频段 AGC：每段各自跟踪峰值，慢衰减。等价于 Wallpaper Engine 对
# audioData 做过的自动增益 —— 壁纸拿到的低频常年在 0.3~1.0，我们原来
# 除以 64 段全局峰值，低频被中高频压住只剩 0.011，效果当然出不来。
AGC_DECAY = 0.9993        # 每帧峰值衰减（60fps 下约 2.4 秒半衰）
AGC_FLOOR = 0.02          # 峰值下限，避免静音时把噪声放大成满幅
# 绝对噪声门：AGC 会把任何信号拉到 floor 的倒数倍，耳机底噪（~0.0005）
# 会被放大到 0.025，正好越过 MUSIC_ON_THRESHOLD(0.02) 造成误触发。
# 实测 55Hz 正弦 amp=0.05（很轻的音乐）低频段幅度是 0.00946，
# 所以 0.0015 的门既能砍掉底噪，又不会误伤轻音乐。
AGC_GATE = 0.0015
# AGC 之后的低频（典型 0.3~1.0）要换算成壁纸量级的 rawVol（volumeCap=0.05），
# 否则 pulse 每帧饱和，形变永远是最大值、看不出律动。
#
# 0.055 时 pulse 峰值只有 0.0297，仅用到壁纸 pulse 上限（0.055）的 54% ——
# 实测横向只做出 +2.9%，比壁纸设定的 ±8% 还小一半。0.10 让 pulse 打到
# 0.0377（68% 上限），既能看出幅度又保留衰减余量、不会每帧顶死。
AGC_TO_VOL = 0.10

# ---- 变形增益（相对壁纸原版）----
# 壁纸是整张背景在动，桌面图标只有 56px，同样的百分比在图标上更不显眼；
# 而且壁纸的 squashX/Y 相等时，视觉上横向拉伸远不如纵向压扁明显
# （纵向压扁改变轮廓高度，横向拉伸只是变宽）。实测 v1.3 横向峰峰只有
# 2.6px、纵向 5.8px —— 所以 X 需要比 Y 大得多的增益。
JELLY_GAIN_X = 4.2        # 横向拉伸增益（实测峰峰 4.2px，最大 +16%）
JELLY_GAIN_Y = 1.8        # 纵向压扁增益（实测峰峰 6.1px，最大 -19%）

# ---- 固定画布几何 ----
# 每个图标一块固定尺寸画布，窗口坐标只由 icon.rect 决定、与缩放无关，
# 这是"隐藏后图标左右乱动"的根治办法。
CANVAS_MARGIN = 4         # 画布四周留白（抗锯齿溢出）
LABEL_GAP = 2             # 本体底边到标签顶部的间距
# 本体最大横向放大。理论上限 = 1 + volumeCap*1.1*squashX*JELLY_GAIN_X
# = 1.3465（pulse 顶到 volCap*1.1 的极端情形）。实际稳态峰值约 1.16，
# 但画布必须按**理论上限**预留，否则极端帧会裁掉本体右边缘；
# 多出来的透明像素不显示、只是窗口略宽，代价可忽略。
JELLY_MAX_W = 1.35
# 纵向只压扁（scaleY ≤ 1），画布高度不需要额外预留：
# h = 2*margin + side + (LABEL_GAP + label_h)

# 画布宽度可以到多宽（相对本体边长）。用户把 Q 弹程度拉满时，画布必须
# 跟着变宽，否则极端帧会裁掉右边缘；但也不能无限宽 —— 2.2 已经能让
# 56px 图标在峰值帧占满 123px，再宽就明显盖住左右邻居了。
JELLY_MAX_W_CAP = 2.2


def jelly_max_w(gain=1.0):
    """按 Q 弹倍率算出"画布宽度 / 本体边长"应该预留多少。

    理论上限 = 1 + volumeCap*1.1*squashX*JELLY_GAIN_X*gain（pulse 顶死）。
    gain=1.0 时正好回到 JELLY_MAX_W（1.3465 → 留到 1.35），
    所以老行为一个像素都不变。
    """
    pulse_cap = DOLL["volumeCap"] * 1.1
    need = 1.0 + pulse_cap * DOLL["squashX"] * JELLY_GAIN_X * max(0.1, gain)
    return min(JELLY_MAX_W_CAP, max(JELLY_MAX_W, need))

# ---- 动画模式（双引擎）----
# 每种模式用 engine 字段声明自己属于哪一档：
#   overlay   原位果冻，只缩放不位移（最稳，永不错位）
#   takeover  副本接管，可以聚拢/绕圈/拼人形（位移的是我们自己的窗口，
#             绝不写 explorer 的图标坐标，退出必归位）
DEFAULT_MODE = "jelly"
AUTO_SWITCH = True        # 自动轮换（每种模式 dwell_s 秒；两年半跳完一轮才切）
