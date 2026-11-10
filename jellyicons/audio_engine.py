# -*- coding: utf-8 -*-
"""音频采集 —— 复刻壁纸拿到的 audioData。

壁纸的数据来源（index.html）：

    window.wallpaperRegisterAudioListener(function(arr){
        if(!arr || arr.length<16) return;
        for(let i=0;i<arr.length && i<64;i++) audioData[i]=arr[i];
    });

Wallpaper Engine 传的是 **64 个归一化频段**（0..1，对数分布的低到高），
不是原始 FFT，也不是 PCM。所以低频就是 audioData[0..2] 的均值，
不需要任何经验缩放系数。

这里用 WASAPI loopback 抓系统输出，自己做一份等效的 64 段对数频谱：
    - 取 PCM -> 汉宁窗 -> rFFT
    - 按对数频率切成 64 段
    - 每段取均值，再做自适应峰值归一化压到 0..1

关键：不能乘拍脑袋的系数。之前乘 3.2 导致 raw 虚高，beat 判定全乱，
看起来就是"乱抖"而不是 Q 弹。
"""
import threading
import time

import numpy as np

try:
    import pyaudiowpatch as pa
except ImportError:
    pa = None

from . import config
from .logutil import get_logger

log = get_logger()

NUM_BANDS = 64
F_MIN = 20.0
F_MAX = 16000.0


def list_loopback_devices():
    """列出可用的 WASAPI loopback 设备（即"扬声器/耳机"）。

    返回 [{"index": int, "name": str, "rate": int, "channels": int,
           "default": bool}, ...]；枚举失败返回 []。
    只读枚举，不改系统设置。
    """
    if pa is None:
        return []
    out = []
    p = None
    try:
        p = pa.PyAudio()
        wasapi = p.get_host_api_info_by_type(pa.paWASAPI)
        default_index = wasapi["defaultOutputDevice"]
        default_name = ""
        try:
            default_name = p.get_device_info_by_index(default_index)["name"]
        except Exception:
            pass
        for d in p.get_loopback_device_info_generator():
            out.append({
                "index": int(d["index"]),
                "name": str(d["name"]),
                "rate": int(d["defaultSampleRate"]),
                "channels": int(d["maxInputChannels"]),
                "default": bool(default_name and default_name in d["name"]),
            })
    except Exception:
        return []
    finally:
        if p is not None:
            try:
                p.terminate()
            except Exception:
                pass
    return out


class AudioEngine(object):
    def __init__(self, block=2048, device_index=None):
        self.block = block
        self.rate = 48000
        self._pa = None
        self._stream = None
        self._buf = np.zeros(block, dtype=np.float32)
        self._lock = threading.Lock()
        self.available = False
        self.device_name = ""
        #: None = 跟随系统默认输出设备
        self.device_index = device_index
        self._bands = np.zeros(NUM_BANDS, dtype=np.float32)
        self._band_map = None
        self._peak = 0.05
        self._peak_decay = 0.9995
        self._last_callback = 0.0
        self._callback_count = 0
        self._window = None

    def _pick_loopback(self):
        p = pa.PyAudio()
        try:
            if self.device_index is not None:
                dev = p.get_device_info_by_index(int(self.device_index))
                return p, dev
            wasapi = p.get_host_api_info_by_type(pa.paWASAPI)
            out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
            for d in p.get_loopback_device_info_generator():
                if out["name"] in d["name"]:
                    return p, d
        except Exception:
            p.terminate()
            raise
        p.terminate()
        return None, None

    def open(self):
        if pa is None:
            return False
        try:
            p, dev = self._pick_loopback()
        except Exception as e:
            log.warning("[audio] 枚举失败: %r", e)
            return False
        if dev is None:
            log.warning("[audio] 没找到 loopback 设备")
            return False
        self._pa = p
        self.rate = int(dev["defaultSampleRate"])
        ch = min(2, int(dev["maxInputChannels"]))
        try:
            self._stream = p.open(
                format=pa.paFloat32, channels=ch, rate=self.rate,
                input=True, input_device_index=dev["index"],
                frames_per_buffer=self.block,
                stream_callback=self._callback)
        except Exception as e:
            log.warning("[audio] 打开流失败: %r", e)
            return False
        self.device_name = dev["name"]
        self.available = True
        self._last_callback = 0.0
        self._callback_count = 0
        self._build_band_map(self.block)
        self._window = np.hanning(self.block).astype(np.float32)
        log.info("[audio] loopback OK: %s %d Hz", self.device_name, self.rate)
        return True

    def _build_band_map(self, nfft):
        freqs = np.fft.rfftfreq(nfft, 1.0 / self.rate)
        edges = np.geomspace(F_MIN, min(F_MAX, self.rate / 2 * 0.95), NUM_BANDS + 1)
        idx = []
        for i in range(NUM_BANDS):
            lo, hi = edges[i], edges[i + 1]
            sel = np.where((freqs >= lo) & (freqs < hi))[0]
            if sel.size == 0:
                sel = np.array([int(np.argmin(np.abs(freqs - lo)))])
            idx.append((int(sel[0]), int(sel[-1]) + 1))
        self._band_map = idx

    def _callback(self, in_data, frame_count, time_info, status):
        try:
            arr = np.frombuffer(in_data, dtype=np.float32)
            if arr.size:
                if arr.size > frame_count:
                    arr = arr.reshape(-1, arr.size // frame_count).mean(axis=1)
                with self._lock:
                    n = min(arr.size, self._buf.size)
                    self._buf[:n] = arr[:n]
                    self._last_callback = time.monotonic()
                    self._callback_count += 1
        except Exception:
            pass
        return (None, pa.paContinue if pa else 0)

    def _compute_bands(self):
        """返回未归一化的 64 段对数频谱；流中断时返回全零。

        回调中断后必须丢弃旧缓冲，否则拔耳机/切换设备会永远重复最后一帧。
        """
        with self._lock:
            last = self._last_callback
            count = self._callback_count
            data = self._buf.copy()
        if not count or time.monotonic() - last > config.AUDIO_STALE_S:
            self._bands = np.zeros(NUM_BANDS, dtype=np.float32)
            return self._bands
        try:
            if self._stream is not None and not self._stream.is_active():
                self.available = False
                self._bands = np.zeros(NUM_BANDS, dtype=np.float32)
                return self._bands
        except Exception:
            self.available = False
            self._bands = np.zeros(NUM_BANDS, dtype=np.float32)
            return self._bands
        self.available = True
        if not data.size or self._band_map is None:
            return self._bands

        win = self._window
        if win is None or win.size != data.size:
            win = np.hanning(data.size).astype(np.float32)
            self._window = win
        spec = np.abs(np.fft.rfft(data * win)) / (data.size * 0.5)

        bands = np.empty(NUM_BANDS, dtype=np.float32)
        for i, (lo, hi) in enumerate(self._band_map):
            seg = spec[lo:hi]
            bands[i] = float(seg.mean()) if seg.size else 0.0
        bands[:8] *= 1.15

        self._bands = bands.astype(np.float32)
        return self._bands

    def bands(self):
        """原始 64 段幅度（供 ActivityDetector 做逐频段 AGC）。"""
        return self._compute_bands()

    def bass_level(self, bins=3):
        """兼容接口：归一化后的低频（内部只用于日志/旧测试）。"""
        b = self._compute_bands()
        if not b.size:
            return 0.0
        peak = max(float(b.max()), 1e-3)
        return float(min(1.0, (b[:bins].mean()) / peak))

    def rms(self):
        with self._lock:
            data = self._buf.copy()
        if not data.size:
            return 0.0
        return float(np.sqrt(np.mean(data * data)))

    def close(self):
        with self._lock:
            self._last_callback = 0.0
            self._callback_count = 0
            self._buf.fill(0.0)
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
        self.available = False
