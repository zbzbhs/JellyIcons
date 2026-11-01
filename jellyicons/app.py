# -*- coding: utf-8 -*-
"""JellyIcons 主循环。

架构约束（区别于旧 DesktopJelly 的全部事故来源）：
  - 只创建本进程拥有的窗口（OverlayWindow），绝不碰 shell 窗口
  - 桌面布局只通过 UI Automation 只读读取
  - 不 SendMessage 给 explorer、不读写 explorer 内存、不碰注册表、无全局钩子
  - 唯一改动外部状态的是音乐模式：ShowWindow(SysListView32, SW_HIDE/SW_SHOW)，
    与系统自带"显示桌面图标"开关操作同一个窗口，退出必恢复

v1.3 的连贯性设计（解决"要等好几秒才隐藏""隐藏后图标左右乱动"）：
  1. 静音/无音乐时：overlay 窗口**整体隐藏**，屏幕上只有 explorer 的原生图标，
     一个像素都不参与，没有任何接缝与错位风险。
  2. 检测到音乐：先按"缩放=1.0 + 文字标签"把副本画好，再隐藏真图标。
     画的是逐像素同尺寸的副本，所以隐藏那一帧画面零变化。
  3. 音乐模式中：副本接管全部像素，Q 弹形变完整可见（真图标已不在，
     不会出现"缩放后露出后面大图标"的问题）。
  4. 音乐停止且缩放回落到 1.0：先显示真图标，再隐藏副本 —— 同样零变化。
  5. 每个图标一块**固定尺寸画布**，窗口坐标只由 icon.rect 决定，与缩放无关，
     横向锚点恒为格子中心 → 不可能左右漂。
"""
from __future__ import annotations

import ctypes
import math
import os
import subprocess
import sys
import time

from . import click_open, config, jelly, shell_icons
from .activity import ActivityDetector
from .audio_engine import AudioEngine
from .desktop_reader import DesktopReader, IntegrityError
from .logutil import get_logger, new_session, log_path
from .music_mode import MusicMode, STATE_HIDDEN
from .overlay import OverlayWindow
from . import watchdog
from .single_instance import SingleInstance

from PIL import Image

log = get_logger()

REFRESH_INTERVAL = 0.25   # 秒；重读桌面布局
# 视为"未变化"的缩放差值：低于此值不重绘（静音时完全跳过）
SCALE_EPS = 0.001
# 退出音乐模式前要求缩放已回落到 1.0（否则显示真图标会有一下跳变）
REST_SCALE_EPS = 0.004
# 恢复真图标后继续保留副本的时长：explorer 重绘有延迟，这段窗口里副本
# 与真图标逐像素重合，撤掉不会闪空桌面。
EXIT_HOLD_S = 0.12


def _user_hides_icons() -> bool:
    """用户平时是否手动勾掉"显示桌面图标"（HideIcons=1）。

    只读注册表一个值；绝不写。为 True 时音乐模式禁用——
    我们不代用户做"显示图标"的决定，只在他选择显示的前提下
    才做"音乐时暂时隐藏"。
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced")
        try:
            value, _type = winreg.QueryValueEx(key, "HideIcons")
        finally:
            key.Close()
        return bool(value)
    except OSError:
        return False
    except Exception:
        return False


def enable_dpi_awareness() -> bool:
    """让本进程使用物理像素坐标。

    UIA 返回的 BoundingRectangle 是物理像素；若进程不做 DPI 声明，
    Windows 会虚拟化我们的窗口坐标，在缩放屏（125%/150%）上 overlay
    必然错位。必须在创建任何窗口之前调用。
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PER_MONITOR_DPI_AWARE
        return True
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            return True
        except Exception:
            return False


class App:
    def __init__(self):
        self.reader = DesktopReader()
        self.overlays = {}         # key -> entry dict
        self.jelly = jelly.make_state()
        self.audio = AudioEngine()
        self.detector = ActivityDetector()
        self.icon_cache = {}       # name -> RGBA Image（屏幕实际边长）
        self.icon_base = {}        # name -> 256px 基图
        self._running = False
        self._uia_warned = False
        self._icon_warned = False
        self._icon_reload_t = 0.0
        self._uia_fail_streak = 0
        self._side_est = None      # 校准出的图标本体边长
        self._cell_w_est = None    # 校准出的格子宽度（标签折行用）
        self._last_sx = 1.0
        self._last_sy = 1.0
        self._label_font = None
        self._label_font_px = None
        self._label_cache = {}
        self._scaled_cache = {}    # (id(img), w, h) -> 缩放副本
        # ---- 音乐模式 ----
        self.music_mode = MusicMode(enabled=not _user_hides_icons())
        self._watchdog_proc = None
        self._watcher = click_open.DoubleClickWatcher(self._hit_test)
        self._visible_mode = None  # None/shown/hidden：上次的绘制模式
        self._exit_hold = None     # 退出音乐模式后保留副本的截止时刻
        self._hb_t = 0.0
        self._hb_hidden = False
        self._desktop_keys = []
        self._has_snapshot = False
        self._needs_resync = True
        self._single_instance = SingleInstance()
        self._next_audio_retry = 0.0

    # ---- 图标源 ----

    def _load_icons(self):
        try:
            cache = shell_icons.build_icon_cache(config.ICON_PIXMAP)
        except Exception as exc:
            log.warning("[icons] 图标缓存构建失败: %r", exc)
            cache = {}
        self.icon_base = cache
        log.info("[icons] 位图缓存 %d 项", len(cache))
        if not cache:
            log.warning("[icons] 位图为空 —— 桌面项一个都没取到！"
                        "将不会有任何视觉效果。")

    def _calibrate_side(self, snapshot):
        """从 UIA 快照估计图标本体边长（格子高的 ~55%，夹到 24..96）。"""
        heights = [icon.rect[3] - icon.rect[1] for icon in snapshot]
        widths = [icon.rect[2] - icon.rect[0] for icon in snapshot]
        if not heights:
            return
        cell_h = sorted(heights)[len(heights) // 2]
        side = int(cell_h * 0.55)
        new_side = max(24, min(96, side))
        new_cell_w = sorted(widths)[len(widths) // 2] if widths else None
        if self._side_est != new_side:
            if self._side_est is not None:
                log.info("[geom] 图标尺寸变化 %s -> %s，重建缓存",
                         self._side_est, new_side)
                self.icon_cache.clear()
                self._label_cache.clear()
                self._scaled_cache.clear()
                self._label_font = None
            self._side_est = new_side
            log.info("[geom] cell_h=%d cell_w=%s -> icon side=%d",
                     cell_h, new_cell_w, new_side)
        if new_cell_w and new_cell_w != self._cell_w_est:
            self._cell_w_est = new_cell_w
            self._label_cache.clear()
    def _ensure_screen_icons(self):
        """把 256px 基图缩放到屏幕实际边长（只做一次）。"""
        if self._side_est is None:
            self._side_est = 48
        side = self._side_est
        for name, img in self.icon_base.items():
            if name not in self.icon_cache:
                if img.size != (side, side):
                    self.icon_cache[name] = img.resize(
                        (side, side), Image.LANCZOS)
                else:
                    self.icon_cache[name] = img

    # ---- 文字标签 ----

    def _font(self):
        if self._label_font is None:
            self._label_font, self._label_font_px = \
                shell_icons.system_icon_font(config.TEXT_FONT_PX)
        return self._label_font

    def _get_label(self, name):
        """带缓存的标签位图；音乐模式接管时由我们画（真标签已隐藏）。"""
        if name in self._label_cache:
            return self._label_cache[name]
        font = self._font()
        cell_w = self._cell_w_est or (int(self._side_est or 48) * 2)
        img = shell_icons.render_label(
            name, font,
            max_width=max(24, cell_w - 8),
            max_lines=config.TEXT_MAX_LINES)
        self._label_cache[name] = img
        return img

    # ---- 桌面同步 ----

    def _icon_for(self, key, name):
        """按唯一 key 取位图；重名项各用自己的位图，不再串图。"""
        img = self.icon_cache.get(key)
        if img is None:
            img = self.icon_cache.get(name)
        return img

    @staticmethod
    def _dedupe(snapshot):
        """重名桌面项加序号后缀，保证 key 唯一（同名互串会错位）。

        编号规则必须与 shell_icons.build_icon_cache 完全一致：
        第一次出现用原名，之后依次 name#1、name#2……否则位图对不上。
        """
        counts: dict[str, int] = {}
        totals: dict[str, int] = {}
        for icon in snapshot:
            totals[icon.name] = totals.get(icon.name, 0) + 1
        result = []
        for icon in snapshot:
            if totals[icon.name] > 1:
                n = counts.get(icon.name, 0)
                counts[icon.name] = n + 1
                key = icon.name if n == 0 else "%s#%d" % (icon.name, n)
            else:
                key = icon.name
            result.append((key, icon))
        return result

    def _layout(self, icon, img, label):
        """算一个图标的固定画布几何（与缩放无关）。

        返回 dict：
            side     本体边长
            body_x   本体槽位左上角（画布内坐标）
            body_y
            label_y  标签槽位顶部（画布内坐标，无标签为 None）
            w, h     画布尺寸
            x, y     窗口屏幕坐标
            cx       格子中心（画布内）
            body_left/top 本体在屏幕上的基准位置（缩放锚点用）
        """
        left, top, right, bottom = icon.rect
        side = img.size[0]
        cx_screen = (left + right) // 2
        body_left = cx_screen - side // 2
        body_top = top + config.ICON_TOP_PAD

        label_w = label.size[0] if label is not None else 0
        label_h = label.size[1] if label is not None else 0
        # 画布宽度要按"本体最大横向放大"预留，否则 Q 弹拉伸时右边缘被裁掉。
        # 宽度仍与 sx 无关（用 JELLY_MAX_W 这个常量上限），不破坏固定画布。
        body_slot_w = int(math.ceil(side * config.JELLY_MAX_W))
        w = max(body_slot_w + 2 * config.CANVAS_MARGIN, label_w)
        h = (2 * config.CANVAS_MARGIN + side
             + (config.LABEL_GAP + label_h if label is not None else 0))
        body_x = (w - side) // 2
        body_y = config.CANVAS_MARGIN
        label_y = (body_y + side + config.LABEL_GAP
                   if label is not None else None)
        return dict(side=side, body_x=body_x, body_y=body_y,
                    label_y=label_y, label_w=label_w, label_h=label_h,
                    w=w, h=h, cx=w // 2,
                    x=body_left - body_x, y=body_top - body_y,
                    body_left=body_left, body_top=body_top,
                    rect=icon.rect)

    def _sync_overlays(self):
        # 音乐模式隐藏真图标期间，UIA 快照可能为空/失败 —— 此时
        # **保留现有 overlay**（它们正在代替真图标显示），只跳过同步。
        hidden = self.music_mode.state == STATE_HIDDEN
        try:
            snapshot = self.reader.snapshot()
        except IntegrityError as exc:
            self._uia_fail_streak += 1
            if not hidden and not self._uia_warned:
                log.error("[desktop] %s", exc)
                self._uia_warned = True
            if not hidden and self._uia_fail_streak % 20 == 0:
                log.info("[desktop] UIA 仍失败（第 %d 次），详见日志: %s",
                         self._uia_fail_streak, log_path())
            return False
        except Exception as exc:
            log.warning("[desktop] snapshot 异常: %r", exc)
            return False

        self._uia_warned = False
        self._uia_fail_streak = 0

        if not snapshot:
            if hidden:
                return True   # 预期：真图标隐藏导致读不到；副本继续
            log.warning("[desktop] 快照为空（0 个图标）")
            self._has_snapshot = False
            self._desktop_keys = []
            return False
        self._calibrate_side(snapshot)
        self._ensure_screen_icons()

        entries = self._dedupe(snapshot)
        self._desktop_keys = [key for key, _icon in entries]
        self._has_snapshot = True
        self._needs_resync = False
        by_key = {key: icon for key, icon in entries}

        # 移除消失的
        for key in list(self.overlays):
            if key not in by_key:
                try:
                    self.overlays[key]["win"].close()
                except Exception:
                    pass
                del self.overlays[key]

        # 新增/更新（只更新几何，不移动已存在的窗口 —— 位置由几何算出，
        # 布局没变就不该动窗口，这是"左右乱动"的另一个来源）
        missing = [icon.name for key, icon in entries
                   if self._icon_for(key, icon.name) is None]
        if missing:
            # 桌面上新出现/重命名的图标，位图缓存里还没有：
            # 按 5 秒节奏重载一次（不重启程序也能补上），别每帧重建缓存。
            now = time.perf_counter()
            if now - self._icon_reload_t >= 5.0:
                self._icon_reload_t = now
                log.info("[icons] 发现 %d 个新桌面项，重载位图缓存", len(missing))
                self._load_icons()
                self._ensure_screen_icons()
            if not self._icon_warned:
                log.warning("[icons] 桌面项 %r 暂无位图，跳过绘制"
                            "（音乐模式将因此不隐藏真图标）", missing[0])
                self._icon_warned = True
        added = 0
        for key, icon in entries:
            img = self._icon_for(key, icon.name)
            if img is None:
                continue  # 无位图则不画（真图标仍在原位）
            label = self._get_label(icon.name)
            geom = self._layout(icon, img, label)
            entry = self.overlays.get(key)
            if entry is not None:
                if entry["geom"] != geom:
                    entry["geom"] = geom
                    entry["icon"] = icon
                    entry["dirty"] = True
                continue
            try:
                win = OverlayWindow()
            except Exception as exc:
                log.warning("[overlay] 创建失败: %r", exc)
                continue
            self.overlays[key] = {"key": key, "icon": icon, "win": win,
                                  "geom": geom, "dirty": True,
                                  "ready": False, "_last_state": None}
            added += 1
        if added:
            log.info("[overlay] 新增 %d 个窗口（共 %d）", added,
                     len(self.overlays))
        return True

    # ---- 绘制 ----

    def _scaled_image(self, img, sx, sy):
        """sx>1 拉宽、sy<1 压扁 = 果冻落地。"""
        w, h = img.size
        new_w = max(1, int(round(w * sx)))
        new_h = max(1, int(round(h * sy)))
        if (new_w, new_h) == (w, h):
            return img
        # 缩放结果按尺寸缓存：60fps 下 sx/sy 只有几十个取值，
        # 每帧 resize 36 张图是纯浪费（而且 resize 在 56px 上有可见锯齿）。
        key = (id(img), new_w, new_h)
        cached = self._scaled_cache.get(key)
        if cached is not None:
            return cached
        if len(self._scaled_cache) > 512:
            self._scaled_cache.clear()
        scaled = img.resize((new_w, new_h), Image.BILINEAR)
        self._scaled_cache[key] = scaled
        return scaled

    def _compose(self, entry, sx, sy):
        """把缩放本体 + 标签画进固定尺寸画布，返回 (canvas, x, y)。

        画布尺寸固定 ⇒ 窗口坐标固定 ⇒ 横向绝不漂移。
        缩放锚点 = 本体槽位底部中心（对应 CSS transform-origin:center bottom）。
        """
        geom = entry["geom"]
        img = self._icon_for(entry.get("key", entry["icon"].name),
                             entry["icon"].name)
        if img is None:
            return None
        label = self._get_label(entry["icon"].name)
        canvas = Image.new("RGBA", (geom["w"], geom["h"]), (0, 0, 0, 0))

        scaled = self._scaled_image(img, sx, sy)
        new_w, new_h = scaled.size
        bx = geom["cx"] - new_w // 2
        by = geom["body_y"] + geom["side"] - new_h
        canvas.paste(scaled, (bx, by), scaled)

        if label is not None and geom["label_y"] is not None:
            lx = (geom["w"] - label.size[0]) // 2
            canvas.paste(label, (lx, geom["label_y"]), label)
        return canvas, geom["x"], geom["y"]

    def _draw_all(self, hidden, sx, sy):
        """按当前模式绘制全部图标。返回重绘个数。"""
        drawn = 0
        # 画布尺寸固定（这是不横移的前提），所以"内容变没变"不能只看尺寸，
        # 必须把缩放值也带进状态里 —— 否则 Q 弹动画会被跳帧逻辑整个吃掉。
        qx = round(sx, 3)
        qy = round(sy, 3)
        for entry in self.overlays.values():
            try:
                if hidden:
                    made = self._compose(entry, sx, sy)
                    if made is None:
                        continue
                    canvas, x, y = made
                    state = (x, y, canvas.size, qx, qy)
                    if (not entry.get("dirty")
                            and entry.get("_last_state") == state):
                        continue
                    entry["win"].draw(canvas, x, y)
                    entry["_last_state"] = state
                    entry["dirty"] = False
                    entry["ready"] = True
                    drawn += 1
                else:
                    # 非音乐模式：overlay 整体隐藏，屏幕上只有原生图标
                    if entry.get("_last_state") is not None:
                        entry["win"].hide()
                        entry["_last_state"] = None
                        entry["dirty"] = True
            except Exception as exc:
                entry["ready"] = False
                log.warning("[draw] 绘制失败: %r", exc)
        return drawn

    def _prime_before_hide(self, sx, sy) -> bool:
        """预绘制并检查覆盖率；任何缺口都保留真实图标。"""
        if (not self._has_snapshot or not self._desktop_keys
                or set(self._desktop_keys) != set(self.overlays)
                or len(self.overlays) != len(self._desktop_keys)):
            log.warning("[music] 副本布局不完整，保留真实图标")
            return False
        for entry in self.overlays.values():
            entry["dirty"] = True
            entry["ready"] = False
        self._draw_all(True, sx, sy)
        if not all(entry.get("ready", False)
                   for entry in self.overlays.values()):
            log.warning("[music] 副本绘制未全部成功，保留真实图标")
            return False
        self._last_sx, self._last_sy = sx, sy
        return True

    def _set_mode(self, hidden):
        """切换绘制模式；返回是否发生了变化。"""
        mode = "hidden" if hidden else "shown"
        if self._visible_mode == "hidden":
            self._needs_resync = True
        if self._visible_mode == mode:
            return False
        self._visible_mode = mode
        self._exit_hold = None    # 重新计时：进入由 before_enter 预绘制，退出由主循环延后撤
        for entry in self.overlays.values():
            entry["dirty"] = True
        return True

    # ---- 双击打开 ----

    def _hit_test(self, x, y):
        """屏幕坐标落在哪个图标的格子里 → 返回该副本的唯一 key。"""
        for key, entry in self.overlays.items():
            left, top, right, bottom = entry["geom"]["rect"]
            if left <= x <= right and top <= y <= bottom:
                return key
        return None

    # ---- 主循环 ----

    def run(self, duration=None):
        new_session("JellyIcons 会话开始")
        if not self._single_instance.acquire():
            log.error("[main] JellyIcons 已在运行；为避免心跳和图标状态"
                      "互踩，本次不启动")
            return 0
        from . import __version__
        log.info("[main] JellyIcons v%s，日志文件: %s", __version__,
                 log_path())
        if not enable_dpi_awareness():
            log.warning("[main] DPI 感知设置失败：缩放屏上 overlay 可能错位")

        if not self.audio.open():
            log.warning("[audio] 无音频输入，动画按静音处理")

        self._load_icons()
        if not self._sync_overlays():
            log.error("[desktop] 初始同步失败；继续重试中")
        if not self.overlays:
            log.error("[main] 没有任何 overlay 窗口被创建 —— 无视觉效果。"
                      "最可能原因见上方 [desktop] / [icons] 日志。")

        self._running = True
        frame_time = 1.0 / config.FPS
        current_fps = config.FPS
        start = time.perf_counter()
        last_frame = start
        next_layout = 0.0
        frames = 0
        drawn = 0
        next_report = 5.0
        report_start = start
        self._start_watchdog()
        watchdog.write_heartbeat(os.getpid(), False)
        bass = 0.0
        presence = 0.0
        sx = sy = 1.0

        while self._running:
            now = time.perf_counter()
            elapsed = now - start
            if duration is not None and elapsed > duration:
                break
            dt = max(1e-4, min(0.25, now - last_frame))
            last_frame = now

            # 音频 → 逐频段 AGC → 低频/活动度
            bands = self.audio.bands()
            bass, presence = self.detector.update(bands, dt)
            # AGC 后的低频（典型 0.3~1.0）换算成壁纸量级（volumeCap=0.05），
            # 否则 pulse 恒饱和，形变永远是最大值
            sx, sy = self.jelly.step(bass * config.AGC_TO_VOL)

            # 音乐模式：presence 判定（包络平滑过，不再受节拍间隙影响）
            # 退出闸门：缩放必须先回落到 1.0，否则把真图标显示出来的
            # 那一帧会看到一下跳变（副本还在形变中）。
            at_rest = (abs(sx - 1.0) < REST_SCALE_EPS
                       and abs(sy - 1.0) < REST_SCALE_EPS)
            self.music_mode.feed(
                presence, time.time(), allow_exit=at_rest,
                before_enter=lambda: self._prime_before_hide(sx, sy))
            hidden = self.music_mode.state == STATE_HIDDEN
            # 心跳限频：看门狗的失联阈值是 1.5s，没必要 60fps 写文件
            # （高频覆写会让看门狗读到半截文件）。状态变化时立即写。
            if hidden != self._hb_hidden or now - self._hb_t >= 0.25:
                watchdog.write_heartbeat(os.getpid(), hidden)
                self._hb_t = now
                self._hb_hidden = hidden
            self._set_mode(hidden)
            self._watcher.enabled = hidden
            desired_fps = config.FPS if hidden else config.IDLE_FPS
            if desired_fps != current_fps:
                current_fps = desired_fps
                frame_time = 1.0 / current_fps
            if (not self.audio.available
                    and elapsed >= self._next_audio_retry):
                self._next_audio_retry = elapsed + config.AUDIO_RETRY_S
                self.audio.close()
                if self.audio.open():
                    log.info("[audio] 输出设备已恢复")

            if elapsed >= next_layout or (self._needs_resync and not hidden):
                next_layout = elapsed + REFRESH_INTERVAL
                self._sync_overlays()

            if hidden:
                if (abs(sx - self._last_sx) >= SCALE_EPS
                        or abs(sy - self._last_sy) >= SCALE_EPS
                        or any(e.get("dirty") for e in self.overlays.values())):
                    drawn += self._draw_all(True, sx, sy)
                    self._last_sx, self._last_sy = sx, sy
            else:
                # 退出音乐模式：explorer 刚收到 SW_SHOW，重绘要一小会儿。
                # 这段时间继续保留副本（此时它已经和真图标逐像素重合），
                # 等真图标画上去再撤，就不会闪出一帧空桌面。
                if self._exit_hold is None:
                    self._exit_hold = now + EXIT_HOLD_S
                if now >= self._exit_hold:
                    self._draw_all(False, 1.0, 1.0)

            if hidden:
                self._watcher.poll(now)

            spent = time.perf_counter() - now
            sleep = frame_time - spent
            if sleep > 0:
                time.sleep(sleep)
            frames += 1

            if elapsed >= next_report:
                win_elapsed = now - report_start
                fps = frames / max(1e-6, win_elapsed)
                log.info("[stat] %.0fs: overlays=%d bass=%.3f presence=%.3f "
                         "scale=(%.3f,%.3f) music=%s fps=%.0f redraw/s=%.0f",
                         elapsed, len(self.overlays), bass, presence,
                         sx, sy, self.music_mode.state, fps,
                         drawn / max(1e-6, win_elapsed))
                frames = 0
                drawn = 0
                report_start = now
                next_report = elapsed + 5.0

        log.info("[main] 退出，清理 overlay 窗口")
        self.close()

    # ---- 看门狗 ----

    def _start_watchdog(self):
        """以 DETACHED_PROCESS 启动独立看门狗：主进程被强杀时恢复图标。"""
        try:
            creationflags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            self._watchdog_proc = subprocess.Popen(
                [sys.executable, "-X", "utf8", "-m", "jellyicons.watchdog"],
                cwd=os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))),
                creationflags=creationflags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            log.info("[watchdog] 看门狗已启动 pid=%s",
                     self._watchdog_proc.pid)
        except Exception as exc:
            log.warning("[watchdog] 启动失败（不影响动画）: %r", exc)

    def close(self):
        # 正常退出也走无感路径：归位、1:1 重绘、恢复真图标、短暂保留副本。
        self._running = False
        restored = True
        was_hidden = self.music_mode.state == STATE_HIDDEN
        try:
            if was_hidden:
                self.jelly.scaleX = self.jelly.scaleY = 1.0
                self._prime_before_hide(1.0, 1.0)
            restored = self.music_mode.restore()
            if restored:
                watchdog.clear_heartbeat()
            else:
                watchdog.write_heartbeat(os.getpid(), True)
        except Exception as exc:
            log.error("[exit] 恢复流程异常: %r", exc)
            restored = False
        # 恢复成功后 state 已变回 shown，所以这里要用 was_hidden 判断：
        # 继续保留一会儿副本，等 explorer 把真图标画上去再撤，避免闪空桌面。
        if restored and was_hidden:
            time.sleep(EXIT_HOLD_S)
        for entry in self.overlays.values():
            try:
                entry["win"].close()
            except Exception:
                pass
        self.overlays.clear()
        self.audio.close()
        self._single_instance.release()
        return restored


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    duration = None
    if argv and argv[0].isdigit():
        duration = float(argv[0])
        argv = argv[1:]
    if argv and argv[0] == "--diagnose":
        from diagnose import run_diagnose
        return run_diagnose(duration)
    app = App()
    try:
        app.run(duration=duration)
    except KeyboardInterrupt:
        app.close()
    except Exception as exc:
        log.exception("主循环异常: %r", exc)
        app.close()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
