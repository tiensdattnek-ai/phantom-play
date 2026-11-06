#!/usr/bin/env bash
# Optional, explicit-consent helper for Linux virtual gamepad permissions.
set -Eeuo pipefail
cd "$(dirname "$0")/.."

echo "Script này sẽ:"
echo "  - nạp module uinput"
echo "  - tạo udev rule gắn thẻ uaccess cho /dev/uinput (user đang đăng nhập local)"
echo "  - cài vgamepad vào venv nếu thiếu"
read -r -p "Tiếp tục? [y/N]: " OK
[[ "${OK:-}" =~ ^[Yy]$ ]] || exit 0

sudo modprobe uinput || true
RULE='KERNEL=="uinput", TAG+="uaccess", OPTIONS+="static_node=uinput"'
echo "$RULE" | sudo tee /etc/udev/rules.d/60-phantomplay-uinput.rules >/dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger --name-match=uinput || true

if [[ -x .venv/bin/python ]]; then
  .venv/bin/python -m pip install -U vgamepad
else
  python3 -m pip install --user -U vgamepad
fi

echo "Xong. Nếu /dev/uinput vẫn chưa writable, đăng xuất/đăng nhập lại hoặc reboot."
ls -l /dev/uinput || true
