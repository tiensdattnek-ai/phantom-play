from __future__ import annotations

import sys
from typing import Optional

# Standard Gamepad API mapping -> XUSB_BUTTON values (ViGEm / vgamepad).
XUSB = {
    0: 0x1000,  # A
    1: 0x2000,  # B
    2: 0x4000,  # X
    3: 0x8000,  # Y
    4: 0x0100,  # LB
    5: 0x0200,  # RB
    8: 0x0020,  # Back / View
    9: 0x0010,  # Start / Menu
    10: 0x0040,  # L3
    11: 0x0080,  # R3
    12: 0x0001,  # D-pad up
    13: 0x0002,  # down
    14: 0x0004,  # left
    15: 0x0008,  # right
    16: 0x0400,  # Guide
}


class GamepadBackend:
    name = "none"
    available = False
    detail = ""

    def update(self, axes: list[float], buttons: list[float]) -> None: raise NotImplementedError
    def reset(self) -> None: pass
    def close(self) -> None: self.reset()


class DemoGamepad(GamepadBackend):
    name = "demo"
    available = True
    detail = "Gamepad demo: hiển thị trạng thái, không tạo thiết bị hệ thống."

    def __init__(self) -> None:
        self.state: dict = {"axes": [0, 0, 0, 0], "buttons": []}

    def update(self, axes, buttons):
        self.state = {"axes": list(axes), "buttons": list(buttons)}

    def reset(self):
        self.state = {"axes": [0, 0, 0, 0], "buttons": [0] * 17}


class VGamepad(GamepadBackend):
    name = "vgamepad-x360"
    available = True

    def __init__(self) -> None:
        import vgamepad as vg

        self.vg = vg
        self.pad = vg.VX360Gamepad()
        self.detail = "Virtual Xbox 360 controller (ViGEmBus/uinput)."
        self._last: Optional[tuple] = None

    def update(self, axes: list[float], buttons: list[float]) -> None:
        b = list(buttons) + [0.0] * (17 - len(buttons))
        state = (tuple(round(a, 4) for a in axes), tuple(round(x, 3) for x in b))
        if state == self._last:
            return
        self._last = state
        pad = self.pad
        pad.reset()
        lx, ly, rx, ry = axes
        pad.left_joystick_float(x_value_float=lx, y_value_float=-ly)
        pad.right_joystick_float(x_value_float=rx, y_value_float=-ry)
        pad.left_trigger_float(value_float=max(0.0, min(1.0, b[6])))
        pad.right_trigger_float(value_float=max(0.0, min(1.0, b[7])))
        mask = 0
        for idx, flag in XUSB.items():
            if idx < len(b) and b[idx] >= 0.5:
                mask |= flag
        if mask:
            # press_button accepts a single flag; combine via repeated calls.
            for idx, flag in XUSB.items():
                if mask & flag:
                    pad.press_button(button=self.vg.XUSB_BUTTON(flag))
        pad.update()

    def reset(self) -> None:
        try:
            self.pad.reset()
            self.pad.update()
        except Exception:
            pass
        self._last = None

    def close(self) -> None:
        self.reset()
        try:
            # vgamepad cleans up on GC; explicit unregister if available.
            if hasattr(self.pad, "_client") and hasattr(self.pad, "_target"):
                pass
        except Exception:
            pass


class KeyboardGamepad(GamepadBackend):
    """Fallback: map pad to keyboard/mouse so games without XInput still work."""

    name = "keyboard-mouse-fallback"
    available = True
    detail = "Gamepad ánh xạ sang phím/chuột (WASD + chuột). Cài vgamepad/uinput để có XInput thật."

    def __init__(self, input_backend) -> None:
        self.inp = input_backend
        self._keys: set[str] = set()
        self._mb = {"left": False, "right": False}
        self._last_axes = [0.0, 0.0, 0.0, 0.0]
        self._last_buttons: list[float] = []

    def _set_key(self, code: str, down: bool) -> None:
        if down and code not in self._keys:
            self.inp.key(code, True)
            self._keys.add(code)
        elif not down and code in self._keys:
            self.inp.key(code, False)
            self._keys.discard(code)

    def _set_mouse(self, name: str, down: bool) -> None:
        if self._mb[name] != down:
            self.inp.button(name, down)
            self._mb[name] = down

    def update(self, axes, buttons):
        b = list(buttons) + [0.0] * (17 - len(buttons))
        lx, ly, rx, ry = axes
        dead = 0.35
        self._set_key("KeyA", lx < -dead)
        self._set_key("KeyD", lx > dead)
        self._set_key("KeyW", ly < -dead)
        self._set_key("KeyS", ly > dead)
        # Right stick -> relative mouse, scaled per update (~60 Hz).
        if abs(rx) > 0.12 or abs(ry) > 0.12:
            self.inp.move_relative(rx * 14, ry * 14)
        mapping = {
            0: "Space", 1: "ControlLeft", 2: "KeyE", 3: "KeyR", 4: "KeyQ", 5: "KeyF",
            8: "Tab", 9: "Escape", 10: "ShiftLeft", 11: "KeyC",
            12: "ArrowUp", 13: "ArrowDown", 14: "ArrowLeft", 15: "ArrowRight",
        }
        for idx, code in mapping.items():
            self._set_key(code, b[idx] >= 0.5)
        self._set_mouse("right", b[6] >= 0.5)
        self._set_mouse("left", b[7] >= 0.5)
        self._last_axes = list(axes)
        self._last_buttons = b

    def reset(self):
        for code in list(self._keys):
            self._set_key(code, False)
        for name in list(self._mb):
            self._set_mouse(name, False)
        self._last_axes = [0, 0, 0, 0]
        self._last_buttons = []


def create_gamepad(settings, input_backend) -> GamepadBackend:
    if settings.demo:
        return DemoGamepad()
    try:
        return VGamepad()
    except Exception as exc:
        kb = KeyboardGamepad(input_backend)
        kb.detail += f" (vgamepad chưa sẵn sàng: {type(exc).__name__})"
        return kb
