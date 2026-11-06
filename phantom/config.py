from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
BIN = RUNTIME / "bin"
WEB = ROOT / "web"

PRESETS: dict[str, dict[str, Any]] = {
    "data_saver": {"label": "Tiết kiệm", "width": 1280, "height": 720, "fps": 30, "bitrate": 3000},
    "balanced": {"label": "Cân bằng", "width": 1920, "height": 1080, "fps": 60, "bitrate": 8000},
    "ultra": {"label": "Ultra", "width": 1920, "height": 1080, "fps": 60, "bitrate": 16000},
    "lan": {"label": "LAN", "width": 1920, "height": 1080, "fps": 120, "bitrate": 30000},
}


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8787
    demo: bool = False
    tunnel: bool = True
    view_only: bool = False
    monitor: int = 1
    display: str = field(default_factory=lambda: os.environ.get("DISPLAY", ":0"))
    capture: str = "auto"          # auto | gdigrab | ddagrab | x11grab
    encoder: str = "auto"          # auto | nvenc | qsv | amf | vaapi | x264
    codec: str = "h264"            # h264 | mjpeg
    preset: str = "balanced"
    width: int = 1920
    height: int = 1080
    fps: int = 60
    bitrate: int = 8000            # kbps
    audio: bool = True
    audio_source: str = "default.monitor"
    adaptive: bool = False
    idle_timeout: int = 600        # seconds; 0 disables
    max_viewers: int = 3
    session_hours: int = 8
    clipboard: bool = False
    hostname: str = field(default_factory=socket.gethostname)
    ffmpeg: str = "ffmpeg"
    cloudflared: str = "cloudflared"
    vaapi_device: str = "/dev/dri/renderD128"
    log_level: str = "INFO"

    def apply_preset(self, name: str) -> None:
        if name not in PRESETS:
            raise ValueError("preset không hợp lệ")
        p = PRESETS[name]
        self.preset = name
        self.width = int(p["width"])
        self.height = int(p["height"])
        self.fps = int(p["fps"])
        self.bitrate = int(p["bitrate"])

    def public_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("host", "port", "ffmpeg", "cloudflared", "display", "audio_source", "vaapi_device"):
            d.pop(k, None)
        return d


def clamp_quality(width: Any, height: Any, fps: Any, bitrate: Any) -> tuple[int, int, int, int]:
    def num(v: Any, lo: int, hi: int, default: int) -> int:
        try:
            n = int(v)
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, n))

    w = num(width, 320, 3840, 1920)
    h = num(height, 180, 2160, 1080)
    # H.264 yuv420p requires even dimensions.
    w -= w % 2
    h -= h % 2
    f = num(fps, 15, 120, 60)
    b = num(bitrate, 1000, 50000, 8000)
    return w, h, f, b
