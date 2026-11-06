from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import time
from typing import Callable, Optional

from .protocol import AUDIO_PCM, pack_media

log = logging.getLogger("phantom.audio")


class AudioCapture:
    """PCM s16le loopback. Kept separate from video so audio failures never kill the stream."""

    def __init__(self, settings, on_data: Callable[[bytes], None]):
        self.settings = settings
        self.on_data = on_data
        self.sample_rate = 48000
        self.channels = 2
        self.running = False
        self.error: Optional[str] = None
        self.seq = 0
        self._task: Optional[asyncio.Task] = None
        self._thread_stop = False
        self._proc: Optional[asyncio.subprocess.Process] = None

    async def start(self) -> None:
        if self.running or not self.settings.audio or self.settings.demo:
            return
        self.running = True
        self.error = None
        if sys.platform == "win32":
            self._task = asyncio.create_task(self._windows())
        else:
            self._task = asyncio.create_task(self._linux())

    async def stop(self) -> None:
        self.running = False
        self._thread_stop = True
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        if self._proc and self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), 2)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    self._proc.kill()
        self._proc = None

    def _emit(self, pcm: bytes) -> None:
        self.seq += 1
        self.on_data(pack_media(AUDIO_PCM, self.seq, time.monotonic_ns() // 1000, pcm))

    async def _linux(self) -> None:
        s = self.settings
        cmd = [s.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
               "-f", "pulse", "-i", s.audio_source, "-ac", "2", "-ar", "48000",
               "-f", "s16le", "pipe:1"]
        try:
            self._proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            assert self._proc.stdout
            while self.running:
                data = await self._proc.stdout.read(3840)  # 20 ms @ 48k stereo s16
                if not data:
                    break
                self._emit(data)
            if self.running:
                self.error = "Không đọc được PulseAudio/PipeWire monitor. Kiểm tra --audio-source."
                log.warning(self.error)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc)
            log.warning("audio: %s", exc)
        finally:
            self.running = False

    async def _windows(self) -> None:
        loop = asyncio.get_running_loop()
        self._thread_stop = False
        try:
            await loop.run_in_executor(None, self._windows_thread, loop)
        except asyncio.CancelledError:
            self._thread_stop = True
            raise
        except Exception as exc:
            self.error = str(exc)
            log.warning("audio WASAPI: %s", exc)
        finally:
            self.running = False

    def _windows_thread(self, loop) -> None:
        import pyaudiowpatch as pyaudio

        p = pyaudio.PyAudio()
        stream = None
        try:
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
            loopback = None
            for dev in p.get_loopback_device_info_generator():
                if dev["name"].startswith(default_out["name"]) or default_out["name"] in dev["name"]:
                    loopback = dev
                    break
            if loopback is None:
                loopback = next(p.get_loopback_device_info_generator())
            self.sample_rate = int(loopback["defaultSampleRate"])
            self.channels = min(2, int(loopback["maxInputChannels"]))
            frames = max(240, self.sample_rate // 50)

            def callback(in_data, frame_count, time_info, status):
                if self._thread_stop:
                    return (None, pyaudio.paComplete)
                loop.call_soon_threadsafe(self._emit, in_data)
                return (None, pyaudio.paContinue)

            stream = p.open(format=pyaudio.paInt16, channels=self.channels, rate=self.sample_rate,
                            input=True, input_device_index=loopback["index"], frames_per_buffer=frames,
                            stream_callback=callback)
            stream.start_stream()
            while not self._thread_stop and stream.is_active():
                time.sleep(0.05)
        finally:
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.stop_stream()
                    stream.close()
            p.terminate()

    def status(self) -> dict:
        return {
            "enabled": self.settings.audio and not self.settings.demo,
            "running": self.running,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "codec": "pcm_s16le",
            "error": self.error,
        }
