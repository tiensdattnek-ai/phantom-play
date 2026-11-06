#!/usr/bin/env python3
"""GitHub Actions helper: provision a temporary PhantomPlay remote desktop.

Subcommands
  start    Start the OS desktop (Linux Xvfb/XFCE), PhantomPlay host and Quick Tunnel.
  wait     Wait for the public URL, verify login + H.264 keyframe, write connection info.
  keep     Keep the job alive for the requested duration and monitor the host.
  cleanup  Stop host/tunnel/desktop processes and remove the local password file.

The workflow uploads connection info *after* `wait` and *before* `keep`, so the user
can download the password while the session is still live.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
OUT = ROOT / "session-output"
CRED = OUT / "credentials"
LOGS = OUT / "logs"
STATE_FILE = RUNTIME / "actions-state.json"
SESSION_FILE = RUNTIME / "session.json"
PASSWORD_FILE = RUNTIME / "actions-password.txt"
PORT = 8787
DISPLAY = ":99"
URL_RE = re.compile(r"^https://[a-zA-Z0-9-]+\.trycloudflare\.com$")


def log(msg: str) -> None:
    print(f"[actions-remote] {msg}", flush=True)


def mask(secret: str) -> None:
    # GitHub Actions redacts masked values from subsequent job logs.
    print(f"::add-mask::{secret}", flush=True)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def parse_resolution(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{3,4})x(\d{3,4})", text.strip())
    if not m:
        raise SystemExit(f"Resolution không hợp lệ: {text}")
    w, h = int(m.group(1)), int(m.group(2))
    if not (640 <= w <= 3840 and 360 <= h <= 2160):
        raise SystemExit("Resolution phải từ 640x360 đến 3840x2160")
    return w - w % 2, h - h % 2


def bitrate_for(w: int, h: int, fps: int) -> int:
    pixels = w * h
    if pixels <= 1280 * 720:
        base = 2500
    elif pixels <= 1600 * 900:
        base = 4000
    else:
        base = 6000
    return int(base * max(0.6, min(1.5, fps / 24)))


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict[str, Any]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def start_detached(cmd: list[str], log_path: Path, env: dict[str, str] | None = None) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = log_path.open("ab", buffering=0)
    kwargs: dict[str, Any] = dict(stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(ROOT), env=env)
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    fh.close()
    return proc


def run_ok(cmd: list[str], timeout: int = 30, env: dict[str, str] | None = None) -> bool:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=env)
        return p.returncode == 0
    except Exception:
        return False


def wait_for(pred, timeout: float, interval: float = 1.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(interval)
    return pred()


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def stop_pid(pid: int | None, name: str) -> None:
    if not pid or pid == os.getpid():
        return
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    for p in children + [parent]:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    gone, alive = psutil.wait_procs(children + [parent], timeout=6)
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    log(f"stopped {name} pid={pid}")


def capture_preflight() -> None:
    try:
        import mss
        from PIL import Image, ImageStat

        MSS = getattr(mss, "MSS", None) or mss.mss
        with MSS() as sct:
            mon = sct.monitors[1]
            shot = sct.grab(mon)
            im = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        LOGS.mkdir(parents=True, exist_ok=True)
        path = LOGS / "preflight.png"
        im.save(path)
        mean = ImageStat.Stat(im).mean
        log(f"preflight screenshot {im.size} mean={mean} -> {path}")
        if sum(mean) / 3 < 2:
            log("WARNING: preflight gần như đen. Desktop có thể chưa sẵn sàng hoặc runner không có interactive session.")
    except Exception as exc:
        log(f"WARNING: không chụp được preflight: {type(exc).__name__}: {exc}")


def start_linux_desktop(width: int, height: int, audio: bool, state: dict) -> str:
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    xdg = Path(f"/tmp/phantom-xdg-{os.getuid()}")
    xdg.mkdir(mode=0o700, exist_ok=True)
    env["XDG_RUNTIME_DIR"] = str(xdg)
    os.environ["DISPLAY"] = DISPLAY

    if not shutil.which("Xvfb"):
        raise SystemExit("Thiếu Xvfb. Workflow phải cài xvfb trước.")
    xvfb = start_detached(
        ["Xvfb", DISPLAY, "-screen", "0", f"{width}x{height}x24", "-ac", "-nolisten", "tcp", "+extension", "RANDR"],
        LOGS / "xvfb.log", env,
    )
    state["xvfb"] = xvfb.pid
    if not wait_for(lambda: run_ok(["xdpyinfo", "-display", DISPLAY], timeout=5, env=env), 30, 0.5):
        raise SystemExit("Xvfb không sẵn sàng. Xem artifact logs/xvfb.log.")
    log(f"Xvfb ready {DISPLAY} {width}x{height}")

    if shutil.which("xfce4-session"):
        cmd = ["dbus-run-session", "--", "xfce4-session"] if shutil.which("dbus-run-session") else ["xfce4-session"]
    elif shutil.which("openbox"):
        cmd = ["openbox"]
    else:
        raise SystemExit("Thiếu xfce4-session/openbox. Workflow phải cài desktop environment.")
    desktop = start_detached(cmd, LOGS / "desktop.log", env)
    state["desktop"] = desktop.pid
    time.sleep(4 if cmd[-1] == "xfce4-session" else 1.5)
    if not pid_alive(desktop.pid):
        raise SystemExit("Desktop session thoát sớm. Xem artifact logs/desktop.log.")

    # Give the user a visible landmark and avoid an all-black preflight on minimal WMs.
    welcome = LOGS / "welcome.txt"
    welcome.write_text(
        "PhantomPlay temporary GitHub Actions desktop.\n"
        "This VM is destroyed when the workflow ends.\n"
        "Do not sign in to personal accounts or store secrets here.\n",
        encoding="utf-8",
    )
    if shutil.which("xsetroot"):
        run_ok(["xsetroot", "-solid", "#101824"], timeout=5, env=env)
    term_cmd = None
    if shutil.which("xfce4-terminal"):
        term_cmd = ["xfce4-terminal", "--title", "PhantomPlay", "--hold", "--command", f"cat {welcome}"]
    elif shutil.which("xterm"):
        term_cmd = ["xterm", "-title", "PhantomPlay", "-hold", "-e", "cat", str(welcome)]
    if term_cmd:
        try:
            term = start_detached(term_cmd, LOGS / "terminal.log", env)
            state["terminal"] = term.pid
            time.sleep(2)
        except Exception as exc:
            log(f"WARNING: welcome terminal: {exc}")

    audio_source = "default.monitor"
    if audio:
        if shutil.which("pulseaudio"):
            run_ok(["pulseaudio", "--start", "--exit-idle-time=-1"], timeout=15, env=env)
            run_ok(["pactl", "load-module", "module-null-sink", "sink_name=phantom"], timeout=10, env=env)
            audio_source = "phantom.monitor"
            state["pulse"] = True
        else:
            log("WARNING: thiếu pulseaudio; tắt audio.")
            audio = False
    state["audio_enabled"] = audio
    return audio_source


def start_windows_desktop(state: dict) -> None:
    # Hosted Windows runners normally have an interactive runneradmin desktop.
    # Make the session visible/useful and leave a welcome window for the user.
    try:
        names = {p.info["name"].lower() for p in psutil.process_iter(["name"]) if p.info.get("name")}
        if "explorer.exe" not in names:
            p = start_detached(["explorer.exe"], LOGS / "explorer.log")
            state["explorer"] = p.pid
    except Exception as exc:
        log(f"WARNING: explorer probe: {exc}")
    welcome = LOGS / "welcome.txt"
    welcome.parent.mkdir(parents=True, exist_ok=True)
    welcome.write_text(
        "PhantomPlay temporary GitHub Actions desktop.\n"
        "This VM is destroyed when the workflow ends.\n"
        "Do not sign in to personal accounts or store secrets here.\n",
        encoding="utf-8",
    )
    if shutil.which("notepad.exe") or Path(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "notepad.exe").exists():
        try:
            p = start_detached(["notepad.exe", str(welcome)], LOGS / "notepad.log")
            state["notepad"] = p.pid
        except Exception as exc:
            log(f"WARNING: notepad welcome: {exc}")


def cmd_start(args: argparse.Namespace) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    CRED.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    width, height = parse_resolution(args.resolution)
    fps = int(args.fps)
    minutes = int(args.minutes)
    if not (5 <= minutes <= 360):
        raise SystemExit("minutes phải từ 5 đến 360")
    if fps not in (15, 24, 30):
        raise SystemExit("fps phải là 15, 24 hoặc 30")

    secret = os.environ.get("PHANTOM_REMOTE_PASSWORD", "").strip()
    generated = not secret
    if generated and not args.credentials_artifact:
        raise SystemExit(
            "Không thể phát mật khẩu an toàn: bật credentials_artifact hoặc đặt repository secret PHANTOM_REMOTE_PASSWORD."
        )
    password = secret or secrets.token_urlsafe(18)
    if len(password) < 8:
        raise SystemExit("Mật khẩu cần ít nhất 8 ký tự")
    mask(password)
    PASSWORD_FILE.write_text(password, encoding="utf-8")
    try:
        PASSWORD_FILE.chmod(0o600)
    except OSError:
        pass

    state: dict[str, Any] = {
        "target": args.target,
        "os": sys.platform,
        "started": time.time(),
        "minutes": minutes,
        "width": width,
        "height": height,
        "fps": fps,
        "bitrate": bitrate_for(width, height, fps),
        "view_only": args.view_only,
        "audio": args.audio,
        "credentials_artifact": args.credentials_artifact,
        "password_source": "repository-secret" if secret else "generated",
        "port": PORT,
    }

    audio_source = "default.monitor"
    if sys.platform.startswith("linux"):
        audio_source = start_linux_desktop(width, height, args.audio, state)
    elif sys.platform == "win32":
        start_windows_desktop(state)
        state["audio_enabled"] = False
        if args.audio:
            log("WARNING: CI Windows audio mặc định tắt để tránh thiết bị loopback ảo không ổn định.")
    else:
        raise SystemExit(f"OS không hỗ trợ: {sys.platform}")

    capture_preflight()

    env = os.environ.copy()
    env["PHANTOM_PASSWORD"] = password
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if sys.platform.startswith("linux"):
        env["DISPLAY"] = DISPLAY
    cmd = [
        sys.executable, "-u", "-m", "phantom",
        "--host", "127.0.0.1", "--port", str(PORT),
        "--width", str(width), "--height", str(height), "--fps", str(fps), "--bitrate", str(state["bitrate"]),
        "--encoder", "x264", "--codec", "h264",
        "--idle-timeout", "0", "--max-viewers", "1", "--session-hours", "8",
        "--no-qr", "--log-level", "INFO",
    ]
    if sys.platform.startswith("linux"):
        cmd += ["--capture", "x11grab", "--display", DISPLAY]
        if state.get("audio_enabled"):
            cmd += ["--audio-source", audio_source]
        else:
            cmd += ["--no-audio"]
    else:
        cmd += ["--capture", "gdigrab", "--no-audio"]
    if args.view_only:
        cmd += ["--view-only"]
    host = start_detached(cmd, LOGS / "host.log", env)
    state["host"] = host.pid
    save_state(state)
    log(f"started host pid={host.pid} target={args.target} {width}x{height}@{fps} {state['bitrate']}kbps")
    log("Chạy bước `wait` để lấy link và xác minh stream.")


def http_json(url: str, data: dict | None = None, headers: dict | None = None, timeout: float = 15) -> tuple[int, dict, str]:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "PhantomPlay-Actions", **(headers or {})})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode(errors="replace")
            try:
                return r.status, json.loads(text), text
            except Exception:
                return r.status, {}, text
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(text), text
        except Exception:
            return e.code, {}, text
    except Exception as exc:
        # DNS warm-up, connection reset, timeout: retryable during tunnel startup.
        return 599, {}, f"{type(exc).__name__}: {exc}"


async def verify_stream(url: str, password: str) -> None:
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"{url}/api/login", json={"password": password}) as r:
            if r.status != 200:
                raise RuntimeError(f"Public login thất bại: HTTP {r.status}")
            cookie = r.headers.get("Set-Cookie", "").split(";")[0]
            if not cookie:
                raise RuntimeError("Login không trả cookie")
        headers = {"Cookie": cookie, "Origin": url}
        async with session.ws_connect(f"{url}/ws", headers=headers, heartbeat=20) as ws:
            hello = await ws.receive_json(timeout=20)
            if hello.get("type") != "hello":
                raise RuntimeError(f"WS hello không hợp lệ: {hello}")
            got_config = False
            got_key = False
            key_size = 0
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and not (got_config and got_key):
                msg = await ws.receive(timeout=10)
                if msg.type == aiohttp.WSMsgType.BINARY:
                    kind = msg.data[0]
                    if kind == 3:
                        got_config = True
                    elif kind == 1:
                        got_key = True
                        key_size = len(msg.data)
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("type") == "stream_error":
                        raise RuntimeError(f"Stream error: {data.get('message')}")
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    raise RuntimeError("WS đóng khi chờ keyframe")
            if not (got_config and got_key):
                raise RuntimeError("Không nhận được H.264 config/keyframe qua public tunnel")
            log(f"public WS verified: config+keyframe ({key_size} bytes)")
            await ws.close()


def write_connection(state: dict, url: str, password: str | None) -> None:
    expires = state["started"] + state["minutes"] * 60
    artifact_name = f"phantom-remote-{state['target']}-{os.environ.get('GITHUB_RUN_ID', 'local')}" if state.get("credentials_artifact") else None
    # Never copy a user-supplied repository secret into an artifact; only generated passwords.
    include_password = bool(state.get("credentials_artifact")) and state.get("password_source") == "generated" and password is not None
    info = {
        "product": "PhantomPlay",
        "target": state["target"],
        "url": url,
        "expires_utc": iso(expires),
        "resolution": f"{state['width']}x{state['height']}",
        "fps": state["fps"],
        "view_only": state["view_only"],
        "password_source": state["password_source"],
        "credentials_artifact": artifact_name,
        "contains_password": include_password,
    }
    if include_password:
        info["password"] = password
    CRED.mkdir(parents=True, exist_ok=True)
    (CRED / "connection.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "PhantomPlay temporary remote desktop",
        f"Target: {state['target']}",
        f"URL: {url}",
        f"Expires (UTC): {iso(expires)}",
        f"Resolution: {state['width']}x{state['height']} @ {state['fps']}fps",
        f"Mode: {'view-only' if state['view_only'] else 'control'}",
    ]
    if include_password:
        lines += [f"Password: {password}", "Giữ file này riêng tư; xóa sau khi dùng."]
    elif state["password_source"] == "repository-secret":
        lines += ["Password: dùng repository secret PHANTOM_REMOTE_PASSWORD bạn đã đặt."]
    else:
        lines += ["Password: không được ghi vào artifact."]
    lines += [
        "",
        "Mở URL bằng trình duyệt PC/điện thoại, nhập mật khẩu.",
        "Cancel workflow hoặc hết thời gian để dừng phiên. VM GitHub sẽ bị hủy.",
        "Đây là CI desktop tạm thời, không phải PC gaming có GPU.",
    ]
    (CRED / "connection.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        md = [
            f"## PhantomPlay remote — `{state['target']}`",
            "",
            f"- **Open:** [{url}]({url})",
            f"- **Expires (UTC):** {iso(expires)}",
            f"- **Stream:** {state['width']}x{state['height']} @ {state['fps']}fps, {'view-only' if state['view_only'] else 'control'}",
        ]
        if include_password:
            md.append(f"- **Password:** download artifact `{artifact_name}` (retention 1 day). Không chia sẻ artifact.")
        elif state["password_source"] == "repository-secret":
            md.append("- **Password:** repository secret `PHANTOM_REMOTE_PASSWORD` (không copy vào artifact).")
        md += [
            "",
            "> Temporary GitHub-hosted CI desktop. No gaming GPU. Cancel the workflow to stop immediately.",
            "> Do not sign in to personal accounts or store secrets on this runner.",
        ]
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
    print(f"::notice title=PhantomPlay ready ({state['target']})::{url}", flush=True)


def cmd_wait(args: argparse.Namespace) -> None:
    state = load_state()
    if not state:
        raise SystemExit("Chưa có state. Chạy start trước.")
    if not wait_for(SESSION_FILE.exists, args.timeout, 1):
        raise SystemExit("Host không tạo session.json. Xem artifact logs/host.log.")
    session = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    url = session.get("url", "")
    if not URL_RE.fullmatch(url):
        raise SystemExit(f"URL Quick Tunnel không hợp lệ: {url}")
    state["url"] = url
    save_state(state)
    log(f"public URL: {url}")

    status, _, _ = http_json(f"http://127.0.0.1:{PORT}/api/health")
    if status != 200:
        raise SystemExit("Local health check thất bại")
    if not wait_for(lambda: http_json(f"{url}/api/health", timeout=10)[0] == 200, 90, 3):
        raise SystemExit("Public health check thất bại qua Cloudflare. Xem logs/host.log.")
    password = PASSWORD_FILE.read_text(encoding="utf-8").strip()
    asyncio.run(verify_stream(url, password))
    write_connection(state, url, password)
    log("READY. Connection info đã ghi; workflow sẽ upload artifact trước khi keep-alive.")


def cmd_keep(args: argparse.Namespace) -> None:
    state = load_state()
    if not state:
        raise SystemExit("Chưa có state")
    minutes = int(args.minutes or state["minutes"])
    end = state["started"] + minutes * 60
    url = state.get("url")
    last_report = 0.0
    last_health = 0.0
    failures = 0
    while time.time() < end:
        if not pid_alive(state.get("host")):
            raise SystemExit("Host process đã thoát. Xem logs/host.log.")
        if not SESSION_FILE.exists():
            raise SystemExit("session.json biến mất; tunnel/host có thể đã dừng.")
        now = time.time()
        if now - last_report >= 60:
            remaining = max(0, int((end - now) / 60))
            log(f"session alive; còn ~{remaining} phút. Cancel workflow để dừng ngay.")
            last_report = now
        if url and now - last_health >= 60:
            try:
                status, _, _ = http_json(f"{url}/api/health", timeout=10)
                failures = 0 if status == 200 else failures + 1
            except Exception:
                failures += 1
            if failures >= 3:
                log("WARNING: public health check fail 3 lần liên tiếp; tunnel có thể gián đoạn.")
            last_health = now
        time.sleep(min(5, max(0.1, end - time.time())))
    log("Hết thời gian phiên. Workflow sẽ cleanup.")


def cmd_cleanup(_args: argparse.Namespace) -> None:
    state = load_state()
    for key, name in (("host", "host+tunnel+ffmpeg"), ("notepad", "notepad"), ("terminal", "terminal"), ("explorer", "explorer"), ("desktop", "desktop"), ("xvfb", "Xvfb")):
        stop_pid(state.get(key), name)
    if sys.platform.startswith("linux") and state.get("pulse"):
        run_ok(["pulseaudio", "--kill"], timeout=10)
    for path in (PASSWORD_FILE, SESSION_FILE):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    log("cleanup done")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--target", required=True)
    s.add_argument("--minutes", default="30")
    s.add_argument("--resolution", default="1280x720")
    s.add_argument("--fps", default="24")
    s.add_argument("--view-only", action="store_true")
    s.add_argument("--audio", action="store_true")
    s.add_argument("--credentials-artifact", action="store_true")
    w = sub.add_parser("wait")
    w.add_argument("--timeout", type=float, default=180)
    k = sub.add_parser("keep")
    k.add_argument("--minutes", default="")
    sub.add_parser("cleanup")
    args = ap.parse_args()
    if args.cmd == "start":
        cmd_start(args)
    elif args.cmd == "wait":
        cmd_wait(args)
    elif args.cmd == "keep":
        cmd_keep(args)
    elif args.cmd == "cleanup":
        cmd_cleanup(args)


if __name__ == "__main__":
    main()
