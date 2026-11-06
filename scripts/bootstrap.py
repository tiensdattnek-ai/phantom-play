#!/usr/bin/env python3
"""Download and verify runtime binaries into ./runtime/bin.

Run after creating the venv and installing requirements.txt.
No credentials are required. FFmpeg checksums come from the official BtbN
release; cloudflared is pinned to a reviewed release + SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
BIN = RUNTIME / "bin"
DL = RUNTIME / "downloads"

CLOUDFLARED_VERSION = "2026.10.7"
CLOUDFLARED_SHA256 = {
    ("windows", "amd64"): "2493dbc168923bb3e59e5e7716f71deced92992eea9acd6e9d74f84ac7751343",
    ("linux", "amd64"): "1f99fb518b83dec2ba8d870a7cc991d82a77e6196295a3d2754ba17ab9f91872",
    ("linux", "arm64"): "3df43aedc9ff291d1735b5cb576cb97e0b157488796db2e32b28aecabb445775",
}


def log(msg: str) -> None:
    print(f"[bootstrap] {msg}", flush=True)


def fetch(url: str, dest: Path, expected_sha256: str | None = None) -> Path:
    if dest.exists() and expected_sha256 and sha256(dest) == expected_sha256:
        log(f"đã có {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"tải {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "PhantomPlay-bootstrap"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=120) as r, tmp.open("wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                if done % (1024 * 1024 * 4) < len(chunk):
                    print(f"  {pct}% ({done // 1048576}/{total // 1048576} MiB)", flush=True)
    if expected_sha256 and h.hexdigest() != expected_sha256:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"SHA-256 không khớp cho {dest.name}; đã hủy file tải về.")
    tmp.replace(dest)
    return dest


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def github_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "PhantomPlay-bootstrap", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def safe_extract_zip(zf: zipfile.ZipFile, member: str, dest: Path) -> None:
    info = zf.getinfo(member)
    if info.is_dir():
        return
    target = (dest / Path(member).name).resolve()
    if dest.resolve() not in target.parents and target != dest.resolve():
        raise RuntimeError("Đường dẫn archive không an toàn")
    with zf.open(info) as src, target.open("wb") as out:
        shutil.copyfileobj(src, out)


def install_ffmpeg(force: bool = False) -> None:
    exe = BIN / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if exe.exists() and not force:
        log("ffmpeg đã có trong runtime/bin")
        return
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        if machine not in ("amd64", "x86_64"):
            raise SystemExit("Windows ARM64 chưa có bundle FFmpeg tự động; hãy cài ffmpeg thủ công vào PATH.")
        asset_name = "ffmpeg-n8.1-latest-win64-gpl-8.1.zip"
        archive = DL / asset_name
    elif system == "linux":
        if machine in ("x86_64", "amd64"):
            asset_name = "ffmpeg-n8.1-latest-linux64-gpl-8.1.tar.xz"
        elif machine in ("aarch64", "arm64"):
            asset_name = "ffmpeg-n8.1-latest-linuxarm64-gpl-8.1.tar.xz"
        else:
            raise SystemExit(f"Linux {machine} chưa có bundle FFmpeg tự động; hãy cài ffmpeg bằng package manager.")
        archive = DL / asset_name
    else:
        raise SystemExit("Chỉ hỗ trợ Windows/Linux.")

    release = github_json("https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest")
    assets = {a["name"]: a for a in release.get("assets", [])}
    if asset_name not in assets:
        # Fall back to master naming if the stable naming changes.
        asset_name = asset_name.replace("n8.1-latest-", "master-latest-").replace("-8.1", "")
    if asset_name not in assets:
        raise SystemExit(f"Không tìm thấy asset {asset_name} trong release FFmpeg.")
    checksums_text = urllib.request.urlopen(assets["checksums.sha256"]["browser_download_url"], timeout=60).read().decode()
    expected = None
    for line in checksums_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].lstrip("*") == asset_name:
            expected = parts[0].lower()
            break
    if not expected:
        raise SystemExit("Không tìm thấy checksum chính thức cho FFmpeg.")
    fetch(assets[asset_name]["browser_download_url"], archive, expected)
    BIN.mkdir(parents=True, exist_ok=True)
    log("giải nén ffmpeg")
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            member = next(n for n in zf.namelist() if n.endswith("bin/ffmpeg.exe"))
            safe_extract_zip(zf, member, BIN)
    else:
        with tarfile.open(archive, "r:xz") as tf:
            member = next(m for m in tf.getmembers() if m.name.endswith("bin/ffmpeg") and m.isfile())
            src = tf.extractfile(member)
            if src is None:
                raise RuntimeError("Không đọc được ffmpeg trong archive")
            with exe.open("wb") as out:
                shutil.copyfileobj(src, out)
    exe.chmod(0o755)
    log(f"ffmpeg OK: {exe} sha256={sha256(exe)}")


def install_cloudflared(force: bool = False) -> None:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("x86_64",):
        machine = "amd64"
    if machine in ("aarch64",):
        machine = "arm64"
    key = (system, machine)
    if key not in CLOUDFLARED_SHA256:
        raise SystemExit(f"cloudflared tự động chưa hỗ trợ {system}/{machine}. Cài thủ công rồi truyền --cloudflared.")
    name = "cloudflared.exe" if system == "windows" else "cloudflared"
    dest = BIN / name
    url = f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/cloudflared-{system}-{machine}"
    if system == "windows":
        url += ".exe"
    fetch(url, dest, CLOUDFLARED_SHA256[key])
    dest.chmod(0o755)
    log(f"cloudflared OK: {dest}")


def check_gamepad() -> None:
    try:
        import vgamepad  # noqa: F401
        log("vgamepad Python OK")
    except Exception as exc:
        log(f"vgamepad chưa sẵn sàng: {exc}. Gamepad sẽ fallback sang phím/chuột.")
    if platform.system() == "Linux":
        p = Path("/dev/uinput")
        if p.exists() and os.access(p, os.W_OK):
            log("/dev/uinput OK")
        else:
            log("Cần quyền uinput cho gamepad ảo: chạy scripts/setup-linux-gamepad.sh (có sudo).")
    elif platform.system() == "Windows":
        log("Nếu game chưa nhận tay cầm, kiểm tra ViGEmBus driver đã cài (vgamepad thường bundled installer).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--skip-ffmpeg", action="store_true")
    ap.add_argument("--skip-cloudflared", action="store_true")
    args = ap.parse_args()
    RUNTIME.mkdir(exist_ok=True)
    BIN.mkdir(exist_ok=True)
    DL.mkdir(exist_ok=True)
    if not args.skip_ffmpeg:
        install_ffmpeg(args.force)
    if not args.skip_cloudflared:
        install_cloudflared(args.force)
    check_gamepad()
    meta = {"cloudflared_version": CLOUDFLARED_VERSION, "ffmpeg_source": "BtbN/FFmpeg-Builds", "verified": True}
    (RUNTIME / "dependencies.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log("Xong. Chạy: python -m phantom")


if __name__ == "__main__":
    main()
