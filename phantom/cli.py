from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import json
import logging
import os
import secrets
import shutil
import signal
import sys
import time
from pathlib import Path

from . import PRODUCT, __version__
from .config import BIN, PRESETS, RUNTIME, Settings, clamp_quality
from .security import generate_password, hash_password
from .server import run_server
from .tunnel import QuickTunnel

log = logging.getLogger("phantom")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="phantom", description=f"{PRODUCT} {__version__} — remote play trong trình duyệt")
    p.add_argument("--demo", action="store_true", help="Màn hình giả lập an toàn, không capture/điều khiển máy thật")
    p.add_argument("--no-tunnel", action="store_true", help="Chỉ chạy local, không mở Cloudflare")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--password-file", type=Path, help="Đọc mật khẩu từ dòng đầu của file (không lưu mật khẩu vào repo)")
    p.add_argument("--view-only", action="store_true")
    p.add_argument("--monitor", type=int, default=1)
    p.add_argument("--display", default=os.environ.get("DISPLAY", ":0"))
    p.add_argument("--capture", choices=["auto", "gdigrab", "ddagrab", "x11grab"], default="auto")
    p.add_argument("--encoder", choices=["auto", "nvenc", "qsv", "amf", "vaapi", "x264"], default="auto")
    p.add_argument("--codec", choices=["h264", "mjpeg"], default="h264")
    p.add_argument("--preset", choices=list(PRESETS), default="balanced")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--fps", type=int)
    p.add_argument("--bitrate", type=int, help="kbps")
    p.add_argument("--no-audio", action="store_true")
    p.add_argument("--audio-source", default="default.monitor")
    p.add_argument("--adaptive", action="store_true", help="Tự giảm bitrate khi mạng xấu (có thể restart encoder)")
    p.add_argument("--idle-timeout", type=int, default=600)
    p.add_argument("--max-viewers", type=int, default=3)
    p.add_argument("--session-hours", type=int, default=8)
    p.add_argument("--clipboard", action="store_true", help="Cho phép client gửi clipboard text tới host")
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument("--cloudflared", default="cloudflared")
    p.add_argument("--vaapi-device", default="/dev/dri/renderD128")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def resolve_binary(name: str, override: str) -> str:
    if override and override != name:
        return override
    local = BIN / (name + (".exe" if sys.platform == "win32" else ""))
    if local.exists():
        return str(local)
    found = shutil.which(name)
    if found:
        return found
    return name


def obtain_password(args) -> tuple[str, bool]:
    env = os.environ.get("PHANTOM_PASSWORD")
    if env:
        return env, False
    if args.password_file:
        text = args.password_file.read_text(encoding="utf-8").splitlines()
        pw = text[0].strip() if text else ""
        if pw:
            return pw, False
    if sys.stdin.isatty():
        print("\nĐặt mật khẩu cho link remote.")
        pw = getpass.getpass("Mật khẩu (Enter để tự tạo): ")
        if pw:
            pw2 = getpass.getpass("Nhập lại: ")
            if pw != pw2:
                raise SystemExit("Mật khẩu nhập lại không khớp.")
            return pw, False
    pw = generate_password()
    return pw, True


def print_box(lines: list[str]) -> None:
    width = max(len(x) for x in lines) + 4
    print("┌" + "─" * width + "┐")
    for line in lines:
        print("│ " + line.ljust(width - 2) + " │")
    print("└" + "─" * width + "┘")


def print_qr(url: str) -> None:
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception:
        pass


async def amain(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = Settings()
    s.demo = args.demo
    s.tunnel = not args.no_tunnel
    s.host = args.host
    s.port = args.port
    s.view_only = args.view_only
    s.monitor = max(1, args.monitor)
    s.display = args.display
    s.capture = args.capture
    s.encoder = args.encoder
    s.codec = args.codec
    s.apply_preset(args.preset)
    if args.width or args.height or args.fps or args.bitrate:
        s.width, s.height, s.fps, s.bitrate = clamp_quality(
            args.width or s.width, args.height or s.height, args.fps or s.fps, args.bitrate or s.bitrate
        )
        s.preset = "custom"
    s.audio = not args.no_audio
    s.audio_source = args.audio_source
    s.adaptive = args.adaptive
    s.idle_timeout = max(0, args.idle_timeout)
    s.max_viewers = max(1, min(8, args.max_viewers))
    s.session_hours = max(1, min(24, args.session_hours))
    s.clipboard = args.clipboard
    s.ffmpeg = resolve_binary("ffmpeg", args.ffmpeg)
    s.cloudflared = resolve_binary("cloudflared", args.cloudflared)
    s.vaapi_device = args.vaapi_device

    if s.host not in ("127.0.0.1", "::1", "localhost") and not s.demo:
        print("CẢNH BÁO: bạn đang bind ra ngoài loopback. Chỉ nên làm vậy trong mạng tin cậy.", file=sys.stderr)
    if s.demo:
        s.width = min(s.width, 1280)
        s.height = min(s.height, 720)
        s.fps = min(s.fps, 30)
        s.bitrate = min(s.bitrate, 4000)
        s.audio = False

    password, generated = obtain_password(args)
    if len(password) < 6:
        raise SystemExit("Mật khẩu cần ít nhất 6 ký tự.")
    if generated:
        print_box(["MẬT KHẨU TỰ TẠO (chỉ hiện một lần):", password, "Hãy lưu lại trước khi đóng cửa sổ này."])
    password_hash = hash_password(password)
    del password

    print_box([
        f"{PRODUCT} {__version__}",
        f"Host: {s.hostname}",
        f"Chế độ: {'DEMO AN TOÀN' if s.demo else 'REMOTE THẬT'}",
        f"Local: http://{s.host}:{s.port}",
        f"Preset: {s.preset}  {s.width}x{s.height}@{s.fps}  {s.bitrate} kbps",
    ])
    server, runner = await run_server(s, password_hash)
    tunnel = None
    session_file = RUNTIME / "session.json"
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop.set)
    public_url = None
    try:
        if s.tunnel:
            tunnel = QuickTunnel(s.cloudflared, s.port)
            print("Đang mở Cloudflare Quick Tunnel...")
            public_url = await tunnel.start()
        url = public_url or f"http://{'127.0.0.1' if s.host == '0.0.0.0' else s.host}:{s.port}"
        RUNTIME.mkdir(exist_ok=True)
        session_file.write_text(json.dumps({"url": url, "port": s.port, "pid": os.getpid(), "started": time.time(), "demo": s.demo}, indent=2), encoding="utf-8")
        print_box(["LINK REMOTE:", url, "", "Mật khẩu: xem lúc khởi động ở trên", "Ctrl+C để dừng và thu hồi link"])
        if public_url:
            print_qr(public_url)
        print("Giữ cửa sổ này mở. Tắt máy/đóng host thì link sẽ mất.")
        if tunnel:
            wait_tunnel = asyncio.create_task(tunnel.wait())
            wait_stop = asyncio.create_task(stop.wait())
            done, pending = await asyncio.wait({wait_tunnel, wait_stop}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            if wait_tunnel in done and not stop.is_set():
                print("Tunnel đã đóng. Link remote không còn dùng được.", file=sys.stderr)
        else:
            await stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if tunnel:
            await tunnel.stop()
        await runner.cleanup()
        with contextlib.suppress(Exception):
            session_file.unlink(missing_ok=True)
        print("Đã dừng PhantomPlay.")
    return 0


def main(argv=None) -> None:
    try:
        raise SystemExit(asyncio.run(amain(argv)))
    except KeyboardInterrupt:
        print("\nĐã dừng.")


if __name__ == "__main__":
    main()
