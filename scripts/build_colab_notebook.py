#!/usr/bin/env python3
"""Build a self-contained Google Colab notebook for PhantomPlay.

The notebook embeds a small source bundle as base64 so a private GitHub repo does
not need a token inside Colab. Upload the generated .ipynb to Colab and Run all.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import textwrap
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "colab" / "PhantomPlay_Colab.ipynb"

BUNDLE_PATHS = [
    "phantom",
    "web",
    "scripts/bootstrap.py",
    "scripts/actions_remote.py",
    "scripts/colab_remote.py",
    "requirements.txt",
    "requirements-gamepad.txt",
    "LICENSE",
    "NOTICE.md",
]


def make_bundle() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for item in BUNDLE_PATHS:
            p = ROOT / item
            if p.is_file():
                z.write(p, item)
            elif p.is_dir():
                for f in sorted(p.rglob("*")):
                    if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
                        z.write(f, str(f.relative_to(ROOT)))
    return buf.getvalue()


def md(src: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": src.splitlines(keepends=True)}


def code(src: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": textwrap.dedent(src).strip("\n").splitlines(keepends=True),
    }


def notebook(b64: str) -> dict:
    cells = [
        md(
            """
            # PhantomPlay Colab Premium

            Remote desktop tạm thời trên Google Colab: **XFCE + Chrome + PhantomPlay + Cloudflare Quick Tunnel**.

            - Tự cài XFCE/Xvfb, Google Chrome, Python deps, FFmpeg, cloudflared.
            - Tự mở Chrome trong desktop ảo.
            - Hiện **link remote + mật khẩu** ngay trong notebook.
            - Browser client PC/mobile: H.264 WebCodecs, MJPEG fallback, gamepad, fullscreen, keyboard, trackpad mouse.
            - Watchdog Chrome, screenshot, mở thêm URL, view-only, clipboard tùy chọn, audio PulseAudio null sink tùy chọn.
            - Nếu Colab có GPU, encoder `auto` có thể thử NVENC; không có thì fallback x264.

            > Chỉ dùng cho runtime Colab của bạn để dev/test tương tác. Colab là môi trường tạm thời, có thể ngắt kết nối,
            > không phải dịch vụ luôn-on. Không mining, không proxy công cộng, không đăng nhập tài khoản cá nhân nhạy cảm.
            > Output notebook chứa mật khẩu — xóa output trước khi chia sẻ.
            """
        ),
        md(
            """
            ## Cách dùng nhanh

            1. Chọn cấu hình ở ô bên dưới. Để trống `PASSWORD` nếu muốn mật khẩu ngẫu nhiên.
            2. Chạy ô **One-click setup + start**.
            3. Chạy ô **Keep alive** và giữ notebook mở.
            4. Mở link remote, nhập mật khẩu.
            5. Muốn dừng: Interrupt ô keep-alive, rồi chạy ô **Stop**.
            """
        ),
        code(
            """
            #@title Cấu hình PhantomPlay Colab
            PASSWORD = "" #@param {type:"string"}
            CHROME_URL = "https://www.google.com" #@param {type:"string"}
            RESOLUTION = "1280x720" #@param ["1280x720", "1600x900", "1920x1080"]
            FPS = 24 #@param [15, 24, 30, 60]
            HOURS = 2 #@param {type:"slider", min:0.25, max:12, step:0.25}
            ENCODER = "auto" #@param ["auto", "nvenc", "x264"]
            INSTALL_CHROME = True #@param {type:"boolean"}
            AUDIO = False #@param {type:"boolean"}
            VIEW_ONLY = False #@param {type:"boolean"}
            CLIPBOARD = False #@param {type:"boolean"}
            ADAPTIVE = True #@param {type:"boolean"}
            KIOSK = False #@param {type:"boolean"}
            APP_MODE = False #@param {type:"boolean"}
            VERIFY_PUBLIC = True #@param {type:"boolean"}
            """
        ),
        code(
            """
            #@title 1) One-click: cài XFCE + Chrome + PhantomPlay, hiện link/mật khẩu
            import base64, html, io, json, os, pathlib, subprocess, sys, zipfile

            BUNDLE_B64 = \"\"\"__BUNDLE_B64__\"\"\"
            ROOT = pathlib.Path('/content/phantom-play')
            ROOT.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(BUNDLE_B64))) as z:
                z.extractall(ROOT)
            os.chdir(ROOT)

            setup_cmd = [sys.executable, 'scripts/colab_remote.py', 'setup']
            if not INSTALL_CHROME:
                setup_cmd.append('--no-chrome')
            subprocess.run(setup_cmd, check=True)

            start_cmd = [
                sys.executable, 'scripts/colab_remote.py', 'start',
                '--url', CHROME_URL,
                '--resolution', RESOLUTION,
                '--fps', str(FPS),
                '--hours', str(HOURS),
                '--encoder', ENCODER,
            ]
            if AUDIO: start_cmd.append('--audio')
            if VIEW_ONLY: start_cmd.append('--view-only')
            if CLIPBOARD: start_cmd.append('--clipboard')
            if not ADAPTIVE: start_cmd.append('--no-adaptive')
            if KIOSK: start_cmd.append('--kiosk')
            if APP_MODE: start_cmd.append('--app')
            if not VERIFY_PUBLIC: start_cmd.append('--no-verify')
            env = os.environ.copy()
            if PASSWORD.strip():
                env['PHANTOM_REMOTE_PASSWORD'] = PASSWORD.strip()
            subprocess.run(start_cmd, check=True, env=env)

            conn = json.loads((ROOT / 'runtime/colab-connection.json').read_text())
            import qrcode
            from IPython.display import HTML, display
            qr = qrcode.make(conn['url'])
            buf = io.BytesIO(); qr.save(buf, format='PNG')
            qr_b64 = base64.b64encode(buf.getvalue()).decode()
            safe_pw = html.escape(conn['password'])
            safe_url = html.escape(conn['url'])
            display(HTML(f'''
            <div style="font-family:system-ui;max-width:760px;background:#0b1220;color:#e5e7eb;border:1px solid #263244;border-radius:16px;padding:20px">
              <h2 style="margin:0 0 8px;color:#7dd3fc">PhantomPlay Colab Premium</h2>
              <p style="margin:4px 0"><b>Link remote:</b> <a href="{safe_url}" target="_blank" style="color:#7dd3fc">{safe_url}</a></p>
              <p style="margin:4px 0"><b>Mật khẩu:</b> <code style="background:#111827;padding:4px 8px;border-radius:6px">{safe_pw}</code></p>
              <p style="margin:4px 0"><b>Stream:</b> {conn['resolution']}@{conn['fps']} · verified={conn['verified']}</p>
              <p style="margin:4px 0"><b>Chrome:</b> {html.escape(conn.get('chrome_url',''))}</p>
              <img src="data:image/png;base64,{qr_b64}" style="width:180px;height:180px;background:white;padding:8px;border-radius:8px"/>
              <p style="font-size:12px;color:#9ca3af">Giữ ô keep-alive chạy. Xóa output notebook trước khi chia sẻ vì có mật khẩu.</p>
            </div>
            '''))
            """
        ),
        code(
            """
            #@title 2) Keep alive — giữ phiên sống, watchdog Chrome
            import subprocess, sys
            subprocess.run([sys.executable, 'scripts/colab_remote.py', 'keep', '--hours', str(HOURS)], check=False)
            """
        ),
        md("## Tiện ích\nChạy các ô dưới sau khi đã có phiên. Nếu ô keep-alive đang chạy, hãy Interrupt nó trước."),
        code(
            """
            #@title Trạng thái / hiện lại link + mật khẩu
            import subprocess, sys
            subprocess.run([sys.executable, 'scripts/colab_remote.py', 'status'], check=False)
            subprocess.run([sys.executable, 'scripts/colab_remote.py', 'show'], check=False)
            """
        ),
        code(
            """
            #@title Mở thêm URL trong Chrome remote
            OPEN_URL = "https://github.com" #@param {type:"string"}
            APP_WINDOW = False #@param {type:"boolean"}
            import subprocess, sys
            cmd = [sys.executable, 'scripts/colab_remote.py', 'open', '--url', OPEN_URL]
            if APP_WINDOW: cmd.append('--app')
            subprocess.run(cmd, check=False)
            """
        ),
        code(
            """
            #@title Chụp màn hình remote
            import subprocess, sys
            from IPython.display import Image, display
            subprocess.run([sys.executable, 'scripts/colab_remote.py', 'shot'], check=False)
            display(Image(filename='runtime/colab-screenshot.png'))
            """
        ),
        code(
            """
            #@title Stop — dừng remote, xóa mật khẩu cục bộ
            import subprocess, sys
            subprocess.run([sys.executable, 'scripts/colab_remote.py', 'stop'], check=False)
            """
        ),
    ]
    # Inject the bundle into the one-click cell.
    for cell in cells:
        if cell["cell_type"] == "code":
            cell["source"] = [line.replace("__BUNDLE_B64__", b64) for line in cell["source"]]
    return {
        "cells": cells,
        "metadata": {
            "colab": {"name": "PhantomPlay_Colab_Premium.ipynb", "provenance": [], "toc_visible": True},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    bundle = make_bundle()
    b64 = base64.b64encode(bundle).decode()
    nb = notebook(b64)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} ({args.out.stat().st_size} bytes, bundle {len(bundle)} bytes)")


if __name__ == "__main__":
    main()
