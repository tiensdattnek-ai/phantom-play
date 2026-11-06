from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

log = logging.getLogger("phantom.tunnel")
URL_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


class QuickTunnel:
    def __init__(self, binary: str, port: int):
        self.binary = binary
        self.port = port
        self.url: Optional[str] = None
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._ready = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self.error: Optional[str] = None

    async def start(self, timeout: float = 60) -> str:
        exe = shutil.which(self.binary) or self.binary
        if not Path(exe).exists() and not shutil.which(exe):
            raise RuntimeError("Không tìm thấy cloudflared. Chạy scripts/bootstrap.py hoặc start.bat/start.sh.")
        env = os.environ.copy()
        # Avoid picking up an unrelated named-tunnel config.
        env["TUNNEL_ORIGIN_CERT"] = ""
        self.proc = await asyncio.create_subprocess_exec(
            exe, "tunnel", "--url", f"http://127.0.0.1:{self.port}",
            "--no-autoupdate", "--protocol", "http2",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        self._task = asyncio.create_task(self._read())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
        except asyncio.TimeoutError:
            await self.stop()
            raise RuntimeError("cloudflared không trả về Quick Tunnel URL. Kiểm tra mạng/firewall rồi thử lại.")
        if not self.url:
            raise RuntimeError(self.error or "Không tạo được tunnel")
        return self.url

    async def _read(self) -> None:
        assert self.proc and self.proc.stdout
        tail = []
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            tail.append(text)
            log.debug("cloudflared: %s", text)
            m = URL_RE.search(text)
            if m and not self.url:
                self.url = m.group(0)
                self._ready.set()
        rc = await self.proc.wait()
        if not self.url:
            self.error = "; ".join(tail[-12:]) or f"cloudflared exit {rc}"
            self._ready.set()

    async def wait(self) -> None:
        if self._task:
            await self._task

    async def stop(self) -> None:
        p = self.proc
        self.proc = None
        if p and p.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                p.terminate()
            try:
                await asyncio.wait_for(p.wait(), 5)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    p.kill()
                await p.wait()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
