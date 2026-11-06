#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"

bold() { printf '\033[1;36m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m%s\033[0m\n' "$*"; }

bold "============================================================"
bold "  PhantomPlay - Remote play trong trinh duyet"
bold "  Linux launcher: cai dat + Cloudflare Quick Tunnel"
bold "============================================================"

if ! command -v python3 >/dev/null 2>&1; then
  warn "Chưa có python3. Đang thử cài bằng package manager..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --needed --noconfirm python python-pip
  else
    echo "Hãy cài Python 3.10+ rồi chạy lại." >&2; exit 1
  fi
fi

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' || {
  echo "Cần Python 3.10+." >&2; exit 1;
}

# Optional but useful system tools. FFmpeg/cloudflared are downloaded by bootstrap
# if the distro packages are missing, so this block is best-effort.
if command -v apt-get >/dev/null 2>&1; then
  if ! command -v xdotool >/dev/null 2>&1 || ! command -v xclip >/dev/null 2>&1; then
    warn "Cài xdotool/xclip cho gõ text và clipboard (có thể hỏi sudo)..."
    sudo apt-get update && sudo apt-get install -y xdotool xclip x11-utils || true
  fi
fi

if [[ ! -x .venv/bin/python ]]; then
  bold "[*] Tạo virtual environment..."
  python3 -m venv .venv || {
    warn "Thiếu python3-venv, thử cài..."
    sudo apt-get install -y python3-venv || true
    python3 -m venv .venv
  }
fi
# shellcheck disable=SC1091
source .venv/bin/activate

bold "[*] Cài Python dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

bold "[*] Cài gamepad ảo (tuỳ chọn)..."
python -m pip install -r requirements-gamepad.txt || warn "Không cài được vgamepad; sẽ fallback gamepad-to-keyboard."

bold "[*] Tải FFmpeg + cloudflared vào runtime/bin..."
python scripts/bootstrap.py

if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
  warn "Bạn đang ở Wayland. Bản này điều khiển/capture tốt nhất trên X11 hoặc XWayland."
  warn "Nếu màn hình đen hoặc input không vào game, hãy đăng nhập session 'X11' rồi chạy lại."
fi

if [[ -t 0 ]]; then
  read -r -p "Bật gamepad ảo uinput? Cần sudo, chỉ làm một lần [y/N]: " GP
  if [[ "${GP:-}" =~ ^[Yy]$ ]]; then
    bash scripts/setup-linux-gamepad.sh || true
  fi
fi

bold "[*] Khởi động PhantomPlay. Lần đầu nhập mật khẩu hoặc Enter để tự tạo."
exec python -m phantom "$@"
