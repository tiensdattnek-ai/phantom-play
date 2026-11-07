#!/usr/bin/env python3
"""PhantomPlay Premium for Google Colab.

One-click temporary browser remote desktop on a Colab Linux runtime:
  setup  -> apt XFCE/Xvfb/Chrome + Python deps + FFmpeg/cloudflared
  start  -> Xvfb + XFCE + Chrome + PhantomPlay + Cloudflare Quick Tunnel
  keep   -> heartbeat/watchdog while the notebook cell is running
  stop   -> kill host/tunnel/desktop/Chrome and remove local password
  show   -> print the current remote link + password again
  open   -> open another URL inside the remote Chrome
  status -> health/PID report
  shot   -> save a PNG screenshot of the remote desktop

Only use this on your own Colab runtime for interactive dev/testing. Colab runtimes
are ephemeral, can disconnect, and are not meant for always-on services/mining.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import actions_remote as ar  # noqa: E402

ROOT = ar.ROOT
RUNTIME = ar.RUNTIME
LOGS = RUNTIME / "colab-logs"
STATE_FILE = RUNTIME / "colab-state.json"
PASSWORD_FILE = RUNTIME / "colab-password.txt"
CONNECTION_FILE = RUNTIME / "colab-connection.json"
SHOT_FILE = RUNTIME / "colab-screenshot.png"
SESSION_FILE = ar.SESSION_FILE
PORT = 8787
DISPLAY = ":99"
CHROME_DEB = "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"
PROFILE_DIR = Path("/content/phantom-chrome-profile") if Path("/content").exists() else RUNTIME / "chrome-profile"

APT_PACKAGES = [
    "xvfb", "xfce4", "xfce4-terminal", "xfce4-panel", "xfdesktop4", "xfwm4",
    "dbus-x11", "x11-utils", "x11-xserver-utils", "xdotool", "xclip",
    "pulseaudio", "pulseaudio-utils", "fonts-liberation", "ca-certificates", "wget",
]


def log(msg: str) -> None:
    print(f"[phantom-colab] {msg}", flush=True)


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict[str, Any]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def sudo_prefix() -> list[str]:
    if os.geteuid() == 0:
        return []
    if shutil.which("sudo"):
        return ["sudo"]
    raise SystemExit("Cần root hoặc sudo để cài package hệ thống.")


def run_cmd(cmd: list[str], timeout: int = 1800, env: dict[str, str] | None = None) -> None:
    log("$ " + " ".join(cmd))
    subprocess.run(cmd, check=True, timeout=timeout, env=env)


def chrome_binary() -> str | None:
    for name in ("google-chrome-stable", "google-chrome", "chromium-browser", "chromium"):
        path = shutil.which(name)
        if path:
            return path
    return None


def install_chrome() -> str:
    found = chrome_binary()
    if found:
        log(f"Chrome/Chromium đã có: {found}")
        return found
    deb = Path("/tmp/google-chrome-stable_current_amd64.deb")
    log("Tải Google Chrome .deb ...")
    urllib.request.urlretrieve(CHROME_DEB, deb)  # noqa: S310 - official Google URL
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    try:
        run_cmd(sudo_prefix() + ["apt-get", "install", "-y", str(deb)], env=env)
    except subprocess.CalledProcessError:
        log("Chrome .deb thất bại, thử chromium từ apt ...")
        run_cmd(sudo_prefix() + ["apt-get", "install", "-y", "chromium-browser"], env=env)
    found = chrome_binary()
    if not found:
        raise SystemExit("Không cài được Chrome/Chromium. Xem log apt ở trên.")
    return found


def cmd_setup(args: argparse.Namespace) -> None:
    if not sys.platform.startswith("linux"):
        raise SystemExit("Colab helper chỉ hỗ trợ Linux runtime.")
    LOGS.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    run_cmd(sudo_prefix() + ["apt-get", "update"], env=env)
    run_cmd(sudo_prefix() + ["apt-get", "install", "-y", "--no-install-recommends", *APT_PACKAGES], env=env)
    if args.chrome:
        install_chrome()
    run_cmd([sys.executable, "-m", "pip", "install", "-U", "pip"])
    run_cmd([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    run_cmd([sys.executable, str(ROOT / "scripts" / "bootstrap.py")], timeout=900)
    gpu = shutil.which("nvidia-smi") and ar.run_ok(["nvidia-smi", "-L"], timeout=10)
    log(f"Setup xong. GPU/NVENC: {'có thể có' if gpu else 'không thấy, dùng CPU x264'}. Chrome: {chrome_binary() or 'không'}")


def chrome_cmd(binary: str, url: str, width: int, height: int, kiosk: bool = False, app: bool = False) -> list[str]:
    cmd = [
        binary,
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--password-store=basic",
        "--disable-features=TranslateUI",
        "--test-type",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        f"--user-data-dir={PROFILE_DIR}",
        f"--window-size={width},{height}",
        "--start-maximized",
    ]
    if kiosk:
        cmd += ["--kiosk", url]
    elif app:
        cmd += [f"--app={url}"]
    else:
        cmd += [url]
    return cmd


def start_chrome(state: dict[str, Any], url: str, kiosk: bool, app: bool) -> None:
    binary = chrome_binary()
    if not binary:
        log("WARNING: chưa có Chrome; chạy setup --chrome hoặc bỏ qua. Desktop vẫn remote được.")
        return
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    cmd = chrome_cmd(binary, url, state["width"], state["height"], kiosk, app)
    proc = ar.start_detached(cmd, LOGS / "chrome.log", env)
    state["chrome"] = proc.pid
    state["chrome_url"] = url
    time.sleep(5)
    if not ar.pid_alive(proc.pid):
        log("WARNING: Chrome thoát sớm. Xem runtime/colab-logs/chrome.log")
        return
    if shutil.which("xdotool"):
        ar.run_ok(["xdotool", "search", "--name", "Chrome", "windowactivate"], timeout=5, env=env)
    log(f"Chrome đã mở: {url}")


def obtain_password(args: argparse.Namespace) -> tuple[str, bool]:
    pw = (args.password or os.environ.get("PHANTOM_REMOTE_PASSWORD") or os.environ.get("PHANTOM_PASSWORD") or "").strip()
    if pw:
        if len(pw) < 8:
            raise SystemExit("Mật khẩu cần ít nhất 8 ký tự.")
        return pw, False
    return secrets.token_urlsafe(18), True


def wait_public(url: str, password: str, timeout: float = 240) -> None:
    if not ar.wait_for(lambda: ar.http_json(f"{url}/api/health", timeout=10)[0] == 200, timeout, 3):
        raise RuntimeError(f"Public health không sẵn sàng sau {timeout}s: {url}/api/health")
    asyncio.run(ar.verify_stream(url, password))


def cmd_start(args: argparse.Namespace) -> None:
    if not sys.platform.startswith("linux"):
        raise SystemExit("Colab helper chỉ hỗ trợ Linux runtime.")
    # A fresh start should not fight an old session on the same port/display.
    if load_state():
        cmd_stop(argparse.Namespace())
    RUNTIME.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    width, height = ar.parse_resolution(args.resolution)
    fps = int(args.fps)
    if fps not in (15, 24, 30, 60):
        raise SystemExit("fps nên là 15/24/30/60.")
    hours = float(args.hours)
    if not (0.25 <= hours <= 12):
        raise SystemExit("hours nên từ 0.25 đến 12 (Colab không phải dịch vụ luôn-on).")
    password, generated = obtain_password(args)
    PASSWORD_FILE.write_text(password, encoding="utf-8")
    try:
        PASSWORD_FILE.chmod(0o600)
    except OSError:
        pass

    state: dict[str, Any] = {
        "product": "PhantomPlay Colab Premium",
        "started": time.time(),
        "hours": hours,
        "width": width,
        "height": height,
        "fps": fps,
        "bitrate": ar.bitrate_for(width, height, fps),
        "encoder": args.encoder,
        "audio": args.audio,
        "view_only": args.view_only,
        "clipboard": args.clipboard,
        "adaptive": args.adaptive,
        "kiosk": args.kiosk,
        "app": args.app,
        "password_source": "generated" if generated else "user",
        "port": PORT,
        "display": DISPLAY,
    }
    save_state(state)

    ffmpeg = RUNTIME / "bin" / "ffmpeg"
    cloudflared = RUNTIME / "bin" / "cloudflared"
    if not ffmpeg.exists() or not cloudflared.exists():
        log("Thiếu FFmpeg/cloudflared, chạy bootstrap ...")
        run_cmd([sys.executable, str(ROOT / "scripts" / "bootstrap.py")], timeout=900)

    audio_source = ar.start_linux_desktop(width, height, args.audio, state)
    start_chrome(state, args.url, args.kiosk, args.app)
    time.sleep(2)
    screenshot(save=True)

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    env["PHANTOM_PASSWORD"] = password
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [
        sys.executable, "-u", "-m", "phantom",
        "--host", "127.0.0.1", "--port", str(PORT),
        "--width", str(width), "--height", str(height), "--fps", str(fps), "--bitrate", str(state["bitrate"]),
        "--encoder", args.encoder, "--codec", "h264",
        "--capture", "x11grab", "--display", DISPLAY,
        "--ffmpeg", str(ffmpeg), "--cloudflared", str(cloudflared),
        "--idle-timeout", "0", "--max-viewers", "2", "--session-hours", str(max(1, math.ceil(hours))),
        "--no-qr", "--log-level", "INFO",
    ]
    if state.get("audio_enabled"):
        cmd += ["--audio-source", audio_source]
    else:
        cmd += ["--no-audio"]
    if args.view_only:
        cmd += ["--view-only"]
    if args.clipboard:
        cmd += ["--clipboard"]
    if args.adaptive:
        cmd += ["--adaptive"]
    host = ar.start_detached(cmd, LOGS / "host.log", env)
    state["host"] = host.pid
    save_state(state)
    log(f"Host PID={host.pid}. Đang chờ Cloudflare Quick Tunnel ...")

    if not ar.wait_for(SESSION_FILE.exists, 180, 1):
        stop_tree(state)
        raise SystemExit("Host không tạo session.json. Xem runtime/colab-logs/host.log")
    session = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    url = session["url"]
    state["url"] = url
    save_state(state)
    verified = False
    if args.no_verify:
        log("Bỏ qua xác minh public stream (--no-verify).")
    else:
        try:
            wait_public(url, password, timeout=240)
            verified = True
        except Exception as exc:
            log(f"WARNING: chưa xác minh được public stream: {exc}")
            log("Link vẫn được in ra; nếu không vào được, xem host.log hoặc chạy lại start.")

    connection = {
        "url": url,
        "password": password,
        "password_source": state["password_source"],
        "verified": verified,
        "resolution": f"{width}x{height}",
        "fps": fps,
        "hours": hours,
        "chrome_url": args.url,
        "started": ar.iso(state["started"]),
        "expires_hint": ar.iso(state["started"] + hours * 3600),
        "warning": "Colab runtime tạm thời. Đóng/dừng notebook hoặc hết phiên thì link mất. Không chia sẻ output notebook nếu có mật khẩu.",
    }
    CONNECTION_FILE.write_text(json.dumps(connection, indent=2), encoding="utf-8")
    try:
        CONNECTION_FILE.chmod(0o600)
    except OSError:
        pass
    print_connection(connection)


def print_connection(conn: dict[str, Any]) -> None:
    print("\n" + "=" * 72)
    print("PHANTOMPLAY COLAB PREMIUM — REMOTE READY")
    print("=" * 72)
    print(f"Link remote : {conn['url']}")
    print(f"Mật khẩu    : {conn['password']}")
    print(f"Chrome URL  : {conn.get('chrome_url', '')}")
    print(f"Stream      : {conn['resolution']}@{conn['fps']}  verified={conn['verified']}")
    print(f"Hết hạn gợi ý: {conn['expires_hint']}")
    print("Giữ ô keep-alive chạy. Interrupt/stop để hủy link và desktop.")
    print("Cảnh báo: output này chứa mật khẩu; xóa output trước khi chia sẻ notebook.")
    print("=" * 72 + "\n", flush=True)


def screenshot(save: bool = True) -> Path | None:
    try:
        import mss
        from PIL import Image

        env = os.environ.copy()
        env["DISPLAY"] = DISPLAY
        os.environ["DISPLAY"] = DISPLAY
        MSS = getattr(mss, "MSS", None) or mss.mss
        with MSS() as sct:
            shot = sct.grab(sct.monitors[1])
            im = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        if save:
            RUNTIME.mkdir(parents=True, exist_ok=True)
            im.save(SHOT_FILE)
            log(f"Screenshot: {SHOT_FILE}")
            return SHOT_FILE
    except Exception as exc:
        log(f"WARNING: screenshot lỗi: {exc}")
    return None


def stop_tree(state: dict[str, Any]) -> None:
    for key, name in (
        ("host", "host+tunnel+ffmpeg"), ("chrome", "chrome"), ("terminal", "terminal"),
        ("desktop", "desktop"), ("xvfb", "Xvfb"),
    ):
        ar.stop_pid(state.get(key), name)


def cmd_stop(_args: argparse.Namespace) -> None:
    state = load_state()
    stop_tree(state)
    for path in (PASSWORD_FILE, CONNECTION_FILE, SESSION_FILE, STATE_FILE):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    log("Đã dừng phiên Colab và xóa mật khẩu cục bộ.")


def cmd_show(_args: argparse.Namespace) -> None:
    if CONNECTION_FILE.exists():
        print_connection(json.loads(CONNECTION_FILE.read_text(encoding="utf-8")))
        return
    state = load_state()
    password = PASSWORD_FILE.read_text(encoding="utf-8").strip() if PASSWORD_FILE.exists() else "(không còn)"
    print_connection({
        "url": state.get("url", "(chưa có)"), "password": password,
        "resolution": f"{state.get('width')}x{state.get('height')}", "fps": state.get("fps"),
        "verified": False, "chrome_url": state.get("chrome_url", ""), "expires_hint": "",
    })


def cmd_status(_args: argparse.Namespace) -> None:
    state = load_state()
    if not state:
        log("Chưa có phiên. Chạy start.")
        return
    for key in ("host", "chrome", "desktop", "xvfb"):
        log(f"{key}: pid={state.get(key)} alive={ar.pid_alive(state.get(key))}")
    local = ar.http_json(f"http://127.0.0.1:{PORT}/api/health", timeout=5)
    log(f"local health: {local[0]} {local[1]}")
    if state.get("url"):
        public = ar.http_json(f"{state['url']}/api/health", timeout=10)
        log(f"public health: {public[0]}")
    log(f"url: {state.get('url')}")


def cmd_open(args: argparse.Namespace) -> None:
    state = load_state()
    if not state:
        raise SystemExit("Chưa có phiên. Chạy start trước.")
    binary = chrome_binary()
    if not binary:
        raise SystemExit("Không tìm thấy Chrome.")
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    cmd = chrome_cmd(binary, args.url, state["width"], state["height"], kiosk=False, app=args.app)
    ar.start_detached(cmd, LOGS / "chrome-open.log", env)
    log(f"Đã mở trong Chrome remote: {args.url}")


def cmd_keep(args: argparse.Namespace) -> None:
    state = load_state()
    if not state:
        raise SystemExit("Chưa có phiên. Chạy start trước.")
    hours = float(args.hours or state.get("hours", 2))
    end = time.monotonic() + hours * 3600
    log(f"Keep-alive {hours}h. Nhấn Interrupt để dừng. URL: {state.get('url')}")
    try:
        while time.monotonic() < end:
            if not ar.pid_alive(state.get("host")):
                log("Host đã dừng. Link remote không còn. Chạy start lại nếu cần.")
                break
            if state.get("chrome") and not ar.pid_alive(state.get("chrome")) and not state.get("kiosk"):
                log("Chrome chết, thử mở lại ...")
                start_chrome(state, state.get("chrome_url", "https://www.google.com"), False, False)
                save_state(state)
            remain = int((end - time.monotonic()) / 60)
            log(f"alive | còn ~{remain} phút | {state.get('url')}")
            time.sleep(60)
    except KeyboardInterrupt:
        log("Nhận Interrupt, dọn dẹp ...")
    finally:
        cmd_stop(argparse.Namespace())


def cmd_shot(_args: argparse.Namespace) -> None:
    path = screenshot(save=True)
    if path:
        print(str(path))


def main() -> None:
    parser = argparse.ArgumentParser(description="PhantomPlay Premium for Google Colab")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="Cài XFCE/Xvfb/Chrome + deps + FFmpeg/cloudflared")
    p.add_argument("--chrome", action=argparse.BooleanOptionalAction, default=True)
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("start", help="Dựng desktop + Chrome + PhantomPlay + Quick Tunnel")
    p.add_argument("--password", default="", help="Mật khẩu tùy chọn; nên dùng env PHANTOM_REMOTE_PASSWORD")
    p.add_argument("--url", default="https://www.google.com")
    p.add_argument("--resolution", default="1280x720")
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--hours", type=float, default=2)
    p.add_argument("--encoder", choices=["auto", "nvenc", "x264"], default="auto")
    p.add_argument("--audio", action="store_true")
    p.add_argument("--view-only", action="store_true")
    p.add_argument("--clipboard", action="store_true")
    p.add_argument("--adaptive", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--kiosk", action="store_true")
    p.add_argument("--app", action="store_true")
    p.add_argument("--no-verify", action="store_true", help="Bỏ qua kiểm tra public health/login/keyframe")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("keep", help="Giữ phiên sống, watchdog Chrome")
    p.add_argument("--hours", type=float, default=0)
    p.set_defaults(func=cmd_keep)

    p = sub.add_parser("stop", help="Dừng và xóa mật khẩu cục bộ")
    p.set_defaults(func=cmd_stop)
    p = sub.add_parser("show", help="Hiện lại link + mật khẩu")
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("status", help="Trạng thái PID/health")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("shot", help="Chụp PNG desktop")
    p.set_defaults(func=cmd_shot)
    p = sub.add_parser("open", help="Mở URL trong Chrome remote")
    p.add_argument("--url", required=True)
    p.add_argument("--app", action="store_true")
    p.set_defaults(func=cmd_open)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
