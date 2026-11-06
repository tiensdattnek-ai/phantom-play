from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
import shutil
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from .config import Settings
from .protocol import (
    HEADER, H264Parser, MjpegParser, VIDEO_CONFIG, VIDEO_DELTA, VIDEO_KEY, JPEG_FRAME, pack_media,
)

log = logging.getLogger("phantom.video")


def monitor_bounds(settings: Settings) -> tuple[int, int, int, int]:
    if settings.demo:
        return (0, 0, settings.width, settings.height)
    try:
        import mss

        MSS = getattr(mss, "MSS", None) or mss.mss
        with MSS() as sct:
            mons = sct.monitors[1:]
            idx = max(0, min(len(mons) - 1, settings.monitor - 1))
            m = mons[idx]
            return int(m["left"]), int(m["top"]), int(m["width"]), int(m["height"])
    except Exception as exc:
        if sys.platform.startswith("linux"):
            raise RuntimeError(f"Không đọc được màn hình X11: {exc}") from exc
        raise


def list_encoders(ffmpeg: str) -> set[str]:
    try:
        p = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=15)
        text = p.stdout + p.stderr
        names = set()
        for name in ("h264_nvenc", "h264_qsv", "h264_amf", "h264_vaapi", "libx264", "mjpeg"):
            if name in text:
                names.add(name)
        return names
    except Exception:
        return {"libx264", "mjpeg"}


def choose_encoder(settings: Settings, available: set[str]) -> str:
    if settings.codec == "mjpeg":
        return "mjpeg"
    if settings.encoder != "auto":
        want = {"nvenc": "h264_nvenc", "qsv": "h264_qsv", "amf": "h264_amf", "vaapi": "h264_vaapi", "x264": "libx264"}[settings.encoder]
        return want if want in available else "libx264"
    order = ["h264_nvenc", "h264_qsv", "h264_amf"]
    if sys.platform.startswith("linux"):
        order.append("h264_vaapi")
    order.append("libx264")
    for name in order:
        if name in available:
            return name
    return "libx264"


@dataclass
class Subscriber:
    queue: asyncio.Queue
    awaiting_key: bool = True
    slow_resets: int = 0


class VideoStream:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.bounds = monitor_bounds(settings)
        self.parser = H264Parser()
        self.mjpeg = MjpegParser()
        self.subs: dict[str, Subscriber] = {}
        self.seq = 0
        self.frames = 0
        self.bytes = 0
        self.started = 0.0
        self.last_frame = 0.0
        self.error: Optional[str] = None
        self.encoder = "libx264"
        self.capture = "demo" if settings.demo else "auto"
        self._task: Optional[asyncio.Task] = None
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._stop = asyncio.Event()
        self._recent_bytes: deque[tuple[float, int]] = deque()
        self._recent_frames: deque[float] = deque()
        self._lock = asyncio.Lock()
        self.demo_input = None
        self.demo_gamepad = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def subscribe(self, sid: str) -> Subscriber:
        sub = Subscriber(asyncio.Queue(maxsize=180))
        self.subs[sid] = sub
        if self.settings.codec == "h264" and self.parser.avcc:
            sub.queue.put_nowait(("media", pack_media(VIDEO_CONFIG, self.seq, 0, self.parser.avcc)))
        return sub

    def unsubscribe(self, sid: str) -> None:
        self.subs.pop(sid, None)

    async def ensure(self) -> None:
        if not self.running:
            self._stop.clear()
            self._task = asyncio.create_task(self._supervise(), name="phantom-video")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        await self._kill_proc()

    async def restart(self) -> None:
        async with self._lock:
            await self.stop()
            self.parser = H264Parser()
            self.mjpeg = MjpegParser()
            self.error = None
            self.bounds = monitor_bounds(self.settings)
            await self.ensure()

    async def _kill_proc(self) -> None:
        p = self._proc
        self._proc = None
        if p and p.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                p.terminate()
            try:
                await asyncio.wait_for(p.wait(), timeout=3)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    p.kill()
                await p.wait()

    def _input_args(self) -> list[str]:
        s = self.settings
        x, y, w, h = self.bounds
        fps = s.fps
        if s.demo:
            return ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0"]
        if sys.platform == "win32":
            cap = s.capture
            if cap == "auto":
                cap = "gdigrab"
            if cap == "ddagrab":
                return ["-f", "lavfi", "-i", f"ddagrab=framerate={fps}:output_idx={max(0, s.monitor - 1)}"]
            return ["-f", "gdigrab", "-framerate", str(fps), "-offset_x", str(x), "-offset_y", str(y),
                    "-video_size", f"{w}x{h}", "-i", "desktop"]
        cap = s.capture if s.capture != "auto" else "x11grab"
        if cap != "x11grab":
            raise RuntimeError("Linux hiện hỗ trợ x11grab. Wayland native/PipeWire chưa có trong bản này.")
        display = s.display if "." in s.display else s.display + ".0"
        return ["-f", "x11grab", "-draw_mouse", "1", "-framerate", str(fps), "-video_size", f"{w}x{h}",
                "-i", f"{display}+{x},{y}"]

    def _filter_args(self, encoder: str) -> list[str]:
        s = self.settings
        _, _, w, h = self.bounds
        target = f"{s.width}:{s.height}"
        chain = []
        if s.demo:
            pass
        if sys.platform == "win32" and s.capture == "ddagrab":
            chain += ["hwdownload", "format=bgra"]
        if (w, h) != (s.width, s.height):
            chain += [f"scale={target}:flags=fast_bilinear"]
        if encoder == "h264_vaapi":
            chain += ["format=nv12", "hwupload"]
            return ["-vaapi_device", s.vaapi_device, "-vf", ",".join(chain)]
        if encoder == "mjpeg":
            chain += ["format=yuvj420p"]
        else:
            chain += ["format=yuv420p"]
        return ["-vf", ",".join(chain)] if chain else []

    def _encoder_args(self, encoder: str) -> list[str]:
        s = self.settings
        b = s.bitrate
        g = max(1, s.fps)  # 1-second GOP for fast join/recovery
        common = ["-g", str(g), "-keyint_min", str(g), "-bf", "0"]
        if encoder == "mjpeg":
            return ["-c:v", "mjpeg", "-q:v", "4"]
        if encoder == "h264_nvenc":
            return ["-c:v", encoder, "-preset", "p1", "-tune", "ll", "-rc", "cbr",
                    "-b:v", f"{b}k", "-maxrate", f"{b}k", "-bufsize", f"{max(500, b // 2)}k",
                    "-profile:v", "baseline", "-no-scenecut", "1", "-delay", "0", *common]
        if encoder == "h264_qsv":
            return ["-c:v", encoder, "-preset", "veryfast", "-low_power", "true", "-look_ahead", "0",
                    "-b:v", f"{b}k", "-maxrate", f"{b}k", "-bufsize", f"{max(500, b // 2)}k", *common]
        if encoder == "h264_amf":
            return ["-c:v", encoder, "-usage", "lowlatency", "-quality", "speed", "-rc", "cbr",
                    "-b:v", f"{b}k", "-maxrate", f"{b}k", "-bufsize", f"{max(500, b // 2)}k", *common]
        if encoder == "h264_vaapi":
            return ["-c:v", encoder, "-b:v", f"{b}k", "-maxrate", f"{b}k", "-bufsize", f"{max(500, b // 2)}k", *common]
        return ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-profile:v", "baseline",
                "-pix_fmt", "yuv420p", "-b:v", f"{b}k", "-maxrate", f"{b}k", "-bufsize", f"{max(500, b // 2)}k",
                "-sc_threshold", "0", "-x264-params", "sliced-threads=1:sync-lookahead=0:rc-lookahead=0", *common]

    def build_command(self, encoder: str) -> list[str]:
        s = self.settings
        args = [s.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                "-fflags", "nobuffer", "-flags", "low_delay", "-probesize", "32", "-analyzeduration", "0",
                *self._input_args(), "-an", "-sn", "-dn",
                *self._filter_args(encoder), *self._encoder_args(encoder)]
        if encoder != "mjpeg":
            args += ["-bsf:v", "h264_metadata=aud=insert", "-f", "h264"]
        else:
            args += ["-f", "mjpeg"]
        args += ["pipe:1"]
        return args

    async def _supervise(self) -> None:
        s = self.settings
        available = await asyncio.to_thread(list_encoders, s.ffmpeg)
        self.encoder = choose_encoder(s, available)
        attempts = 0
        while not self._stop.is_set():
            try:
                await self._run_once()
                if self._stop.is_set():
                    break
                raise RuntimeError("ffmpeg kết thúc stream")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                log.warning("video: %s", self.error)
                if self.encoder != "libx264" and s.codec == "h264" and attempts == 0:
                    log.info("Fallback sang libx264")
                    self.encoder = "libx264"
                    attempts += 1
                    continue
                attempts += 1
                if attempts >= 5:
                    self._broadcast_json({"type": "stream_error", "message": self.error})
                    return
                await asyncio.sleep(min(5, 1 + attempts))

    async def _run_once(self) -> None:
        s = self.settings
        cmd = self.build_command(self.encoder)
        self.capture = "demo" if s.demo else ("ddagrab" if sys.platform == "win32" and s.capture == "ddagrab" else ("gdigrab" if sys.platform == "win32" else "x11grab"))
        log.info("start video encoder=%s capture=%s %dx%d@%d %dk", self.encoder, self.capture, s.width, s.height, s.fps, s.bitrate)
        self.started = time.monotonic()
        self.parser = H264Parser()
        self.mjpeg = MjpegParser()
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if s.demo else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=4 * 1024 * 1024,
        )
        writer = asyncio.create_task(self._demo_writer(self._proc)) if s.demo else None
        stderr_tail = deque(maxlen=20)

        async def read_stderr():
            assert self._proc and self._proc.stderr
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                stderr_tail.append(line.decode(errors="replace").strip())

        err_task = asyncio.create_task(read_stderr())
        try:
            assert self._proc.stdout
            while not self._stop.is_set():
                chunk = await self._proc.stdout.read(65536)
                if not chunk:
                    break
                if s.codec == "mjpeg":
                    for frame in self.mjpeg.feed(chunk):
                        self._publish_jpeg(frame)
                else:
                    for au in self.parser.feed(chunk):
                        self._publish_au(au)
            await self._proc.wait()
            if self._proc.returncode not in (0, None) and not self._stop.is_set():
                raise RuntimeError("; ".join(stderr_tail)[-1200:] or f"ffmpeg exit {self._proc.returncode}")
        finally:
            err_task.cancel()
            if writer:
                writer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await err_task
            if writer:
                with contextlib.suppress(asyncio.CancelledError):
                    await writer
            await self._kill_proc()

    async def _demo_writer(self, proc: asyncio.subprocess.Process) -> None:
        from .demo import DemoScene

        scene = DemoScene(self.settings.width, self.settings.height)
        interval = 1.0 / self.settings.fps
        try:
            while not self._stop.is_set() and proc.stdin and not proc.stdin.is_closing():
                t0 = time.monotonic()
                cursor = None
                keys = None
                pad = None
                if self.demo_input is not None:
                    cursor = (self.demo_input.x, self.demo_input.y)
                    keys = sorted(self.demo_input.keys)
                if self.demo_gamepad is not None:
                    pad = getattr(self.demo_gamepad, "state", None)
                frame = scene.render(t0, cursor=cursor, keys=keys, gamepad=pad)
                proc.stdin.write(frame)
                await proc.stdin.drain()
                elapsed = time.monotonic() - t0
                await asyncio.sleep(max(0.001, interval - elapsed))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _publish_au(self, au) -> None:
        if au.key and self.parser.avcc:
            cfg = pack_media(VIDEO_CONFIG, self.seq, au.pts_us, self.parser.avcc)
            for sub in self.subs.values():
                self._put(sub, ("media", cfg))
        kind = VIDEO_KEY if au.key else VIDEO_DELTA
        self.seq += 1
        data = pack_media(kind, self.seq, au.pts_us, au.data)
        self._publish_bytes(data, au.key, len(au.data))

    def _publish_jpeg(self, frame: bytes) -> None:
        self.seq += 1
        data = pack_media(JPEG_FRAME, self.seq, time.monotonic_ns() // 1000, frame)
        self._publish_bytes(data, True, len(frame))

    def _publish_bytes(self, data: bytes, key: bool, size: int) -> None:
        now = time.monotonic()
        self.frames += 1
        self.bytes += size
        self.last_frame = now
        self._recent_frames.append(now)
        self._recent_bytes.append((now, size))
        cutoff = now - 3
        while self._recent_frames and self._recent_frames[0] < cutoff:
            self._recent_frames.popleft()
        while self._recent_bytes and self._recent_bytes[0][0] < cutoff:
            self._recent_bytes.popleft()
        for sub in list(self.subs.values()):
            if sub.awaiting_key and not key:
                continue
            if key:
                sub.awaiting_key = False
            self._put(sub, ("media", data))

    def _put(self, sub: Subscriber, item) -> None:
        try:
            sub.queue.put_nowait(item)
        except asyncio.QueueFull:
            sub.slow_resets += 1
            sub.awaiting_key = True
            while not sub.queue.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                sub.queue.put_nowait(("json", {"type": "stream_reset", "reason": "Mạng chậm, đang chờ keyframe"}))
            if self.settings.codec == "h264" and self.parser.avcc:
                with contextlib.suppress(asyncio.QueueFull):
                    sub.queue.put_nowait(("media", pack_media(VIDEO_CONFIG, self.seq, 0, self.parser.avcc)))

    def _broadcast_json(self, msg: dict) -> None:
        for sub in list(self.subs.values()):
            self._put(sub, ("json", msg))

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        frames = len([t for t in self._recent_frames if now - t <= 2])
        fps = frames / 2
        mbps = sum(b for t, b in self._recent_bytes if now - t <= 2) * 8 / 2 / 1_000_000
        return {
            "running": self.running,
            "codec": self.settings.codec,
            "encoder": self.encoder,
            "capture": self.capture,
            "width": self.settings.width,
            "height": self.settings.height,
            "fps": round(fps, 1),
            "target_fps": self.settings.fps,
            "mbps": round(mbps, 2),
            "bitrate": self.settings.bitrate,
            "viewers": len(self.subs),
            "error": self.error,
        }
