from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Optional

VK = {
    **{f"Key{chr(c)}": c for c in range(65, 91)},
    **{f"Digit{i}": 48 + i for i in range(10)},
    **{f"F{i}": 0x6F + i for i in range(1, 13)},
    "Escape": 0x1B, "Tab": 0x09, "CapsLock": 0x14,
    "ShiftLeft": 0xA0, "ShiftRight": 0xA1, "ControlLeft": 0xA2, "ControlRight": 0xA3,
    "AltLeft": 0xA4, "AltRight": 0xA5, "MetaLeft": 0x5B, "MetaRight": 0x5C,
    "Space": 0x20, "Enter": 0x0D, "Backspace": 0x08, "Delete": 0x2E, "Insert": 0x2D,
    "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22,
    "ArrowLeft": 0x25, "ArrowUp": 0x26, "ArrowRight": 0x27, "ArrowDown": 0x28,
    "PrintScreen": 0x2C, "ScrollLock": 0x91, "Pause": 0x13, "NumLock": 0x90,
    **{f"Numpad{i}": 0x60 + i for i in range(10)},
    "NumpadAdd": 0x6B, "NumpadSubtract": 0x6D, "NumpadMultiply": 0x6A,
    "NumpadDivide": 0x6F, "NumpadDecimal": 0x6E, "NumpadEnter": 0x0D,
    "Minus": 0xBD, "Equal": 0xBB, "BracketLeft": 0xDB, "BracketRight": 0xDD,
    "Backslash": 0xDC, "Semicolon": 0xBA, "Quote": 0xDE, "Comma": 0xBC,
    "Period": 0xBE, "Slash": 0xBF, "Backquote": 0xC0, "ContextMenu": 0x5D,
}

XK = {
    **{f"Key{chr(c)}": chr(c + 32) for c in range(65, 91)},
    **{f"Digit{i}": str(i) for i in range(10)},
    **{f"F{i}": f"F{i}" for i in range(1, 13)},
    "Escape": "Escape", "Tab": "Tab", "CapsLock": "Caps_Lock",
    "ShiftLeft": "Shift_L", "ShiftRight": "Shift_R", "ControlLeft": "Control_L", "ControlRight": "Control_R",
    "AltLeft": "Alt_L", "AltRight": "Alt_R", "MetaLeft": "Super_L", "MetaRight": "Super_R",
    "Space": "space", "Enter": "Return", "Backspace": "BackSpace", "Delete": "Delete", "Insert": "Insert",
    "Home": "Home", "End": "End", "PageUp": "Prior", "PageDown": "Next",
    "ArrowLeft": "Left", "ArrowUp": "Up", "ArrowRight": "Right", "ArrowDown": "Down",
    "PrintScreen": "Print", "ScrollLock": "Scroll_Lock", "Pause": "Pause", "NumLock": "Num_Lock",
    **{f"Numpad{i}": f"KP_{i}" for i in range(10)},
    "NumpadAdd": "KP_Add", "NumpadSubtract": "KP_Subtract", "NumpadMultiply": "KP_Multiply",
    "NumpadDivide": "KP_Divide", "NumpadDecimal": "KP_Decimal", "NumpadEnter": "KP_Enter",
    "Minus": "minus", "Equal": "equal", "BracketLeft": "bracketleft", "BracketRight": "bracketright",
    "Backslash": "backslash", "Semicolon": "semicolon", "Quote": "apostrophe", "Comma": "comma",
    "Period": "period", "Slash": "slash", "Backquote": "grave", "ContextMenu": "Menu",
}


class InputBackend:
    name = "none"
    available = False
    detail = ""

    def move_relative(self, dx: float, dy: float) -> None: raise NotImplementedError
    def move_absolute(self, x: float, y: float) -> None: raise NotImplementedError
    def button(self, name: str, down: bool) -> None: raise NotImplementedError
    def set_buttons(self, mask: int) -> None:
        for bit, name in ((1, "left"), (2, "right"), (4, "middle")):
            self.button(name, bool(mask & bit))
    def wheel(self, dx: float, dy: float) -> None: raise NotImplementedError
    def key(self, code: str, down: bool) -> None: raise NotImplementedError
    def type_text(self, text: str) -> None: raise NotImplementedError
    def clipboard_set(self, text: str) -> None: raise NotImplementedError("Clipboard chưa khả dụng trên máy này")
    def release_all(self) -> None: pass
    def close(self) -> None: self.release_all()


class DemoInput(InputBackend):
    name = "demo"
    available = True
    detail = "Chuột/phím chỉ vẽ lên màn hình demo, không điều khiển hệ điều hành."

    def __init__(self) -> None:
        self.x = 0.5
        self.y = 0.5
        self.buttons = 0
        self.keys: set[str] = set()
        self.last_text = ""
        self.gamepad: dict = {}

    def move_relative(self, dx: float, dy: float) -> None:
        self.x = min(1.0, max(0.0, self.x + dx / 1280))
        self.y = min(1.0, max(0.0, self.y + dy / 720))

    def move_absolute(self, x: float, y: float) -> None:
        self.x, self.y = x, y

    def button(self, name: str, down: bool) -> None:
        bit = {"left": 1, "right": 2, "middle": 4}[name]
        self.buttons = (self.buttons | bit) if down else (self.buttons & ~bit)

    def wheel(self, dx: float, dy: float) -> None:
        pass

    def key(self, code: str, down: bool) -> None:
        if down:
            self.keys.add(code)
        else:
            self.keys.discard(code)

    def type_text(self, text: str) -> None:
        self.last_text = (self.last_text + text)[-80:]

    def release_all(self) -> None:
        self.buttons = 0
        self.keys.clear()


class WindowsInput(InputBackend):
    name = "windows-sendinput"
    available = True
    detail = "SendInput scancode + chuột tương đối/tuyệt đối + Unicode."

    EXTENDED = {
        "ControlRight", "AltRight", "ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown",
        "Home", "End", "PageUp", "PageDown", "Insert", "Delete", "PrintScreen",
        "NumLock", "NumpadDivide", "NumpadEnter", "MetaLeft", "MetaRight", "ContextMenu",
    }

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.wintypes = wintypes
        self._pressed: set[str] = set()
        self._buttons = 0
        self._lock = threading.Lock()
        self._define_structs()
        self._get_metrics()

    def _define_structs(self):
        c = self.ctypes
        w = self.wintypes
        ULONG_PTR = c.c_ulonglong if c.sizeof(c.c_void_p) == 8 else c.c_ulong

        class MOUSEINPUT(c.Structure):
            _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                        ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class KEYBDINPUT(c.Structure):
            _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
                        ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class HARDWAREINPUT(c.Structure):
            _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]

        class _IU(c.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(c.Structure):
            _fields_ = [("type", w.DWORD), ("ii", _IU)]

        self.MOUSEINPUT = MOUSEINPUT
        self.KEYBDINPUT = KEYBDINPUT
        self.INPUT = INPUT
        self.user32.SendInput.argtypes = (w.UINT, c.POINTER(INPUT), c.c_int)
        self.user32.SendInput.restype = w.UINT
        self.user32.MapVirtualKeyW.argtypes = (w.UINT, w.UINT)
        self.user32.MapVirtualKeyW.restype = w.UINT
        self.user32.GetSystemMetrics.argtypes = (c.c_int,)
        self.user32.GetSystemMetrics.restype = c.c_int

    def _get_metrics(self):
        g = self.user32.GetSystemMetrics
        self.vx, self.vy = g(76), g(77)
        self.vw, self.vh = max(1, g(78)), max(1, g(79))

    def _send(self, inp):
        n = self.user32.SendInput(1, self.ctypes.byref(inp), self.ctypes.sizeof(self.INPUT))
        if n != 1:
            err = self.ctypes.get_last_error()
            raise OSError(f"SendInput thất bại (WinError {err}). Game chạy elevated có thể chặn input từ process thường.")

    def _mouse(self, dx=0, dy=0, data=0, flags=0):
        inp = self.INPUT(type=0)
        inp.ii.mi = self.MOUSEINPUT(int(dx), int(dy), int(data) & 0xFFFFFFFF, flags, 0, 0)
        self._send(inp)

    def move_relative(self, dx: float, dy: float) -> None:
        with self._lock:
            self._mouse(dx=round(dx), dy=round(dy), flags=0x0001)

    def move_absolute(self, x: float, y: float) -> None:
        nx = int(self.vx + x * (self.vw - 1))
        ny = int(self.vy + y * (self.vh - 1))
        ax = int((nx - self.vx) * 65535 / max(1, self.vw - 1))
        ay = int((ny - self.vy) * 65535 / max(1, self.vh - 1))
        with self._lock:
            self._mouse(dx=ax, dy=ay, flags=0x0001 | 0x8000 | 0x4000)

    def button(self, name: str, down: bool) -> None:
        flags = {
            "left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040),
        }[name]
        bit = {"left": 1, "right": 2, "middle": 4}[name]
        with self._lock:
            if down:
                self._buttons |= bit
            else:
                self._buttons &= ~bit
            self._mouse(flags=flags[0] if down else flags[1])

    def wheel(self, dx: float, dy: float) -> None:
        with self._lock:
            if dy:
                self._mouse(data=round(dy * 120), flags=0x0800)
            if dx:
                self._mouse(data=round(dx * 120), flags=0x1000)

    def _key_input(self, vk: int, scan: int, flags: int):
        inp = self.INPUT(type=1)
        inp.ii.ki = self.KEYBDINPUT(vk, scan, flags, 0, 0)
        self._send(inp)

    def key(self, code: str, down: bool) -> None:
        vk = VK.get(code)
        if vk is None:
            return
        scan = self.user32.MapVirtualKeyW(vk, 0)
        flags = 0
        if code in self.EXTENDED:
            flags |= 0x0001
        if not down:
            flags |= 0x0002
        with self._lock:
            if down:
                self._pressed.add(code)
            else:
                self._pressed.discard(code)
            self._key_input(vk, scan, flags)

    def type_text(self, text: str) -> None:
        with self._lock:
            for ch in text:
                # Send UTF-16 code units (handles surrogate pairs).
                data = ch.encode("utf-16-le")
                for i in range(0, len(data), 2):
                    cu = int.from_bytes(data[i : i + 2], "little")
                    self._key_input(0, cu, 0x0004)        # UNICODE down
                    self._key_input(0, cu, 0x0004 | 0x0002)  # UNICODE up

    def clipboard_set(self, text: str) -> None:
        c = self.ctypes
        w = self.wintypes
        self.user32.OpenClipboard.argtypes = (w.HWND,)
        self.user32.OpenClipboard.restype = w.BOOL
        self.user32.EmptyClipboard.restype = w.BOOL
        self.user32.SetClipboardData.argtypes = (w.UINT, w.HANDLE)
        self.user32.SetClipboardData.restype = w.HANDLE
        self.user32.CloseClipboard.restype = w.BOOL
        self.kernel32.GlobalAlloc.argtypes = (w.UINT, c.c_size_t)
        self.kernel32.GlobalAlloc.restype = w.HGLOBAL
        self.kernel32.GlobalLock.argtypes = (w.HGLOBAL,)
        self.kernel32.GlobalLock.restype = w.LPVOID
        self.kernel32.GlobalUnlock.argtypes = (w.HGLOBAL,)
        data = (text + "\0").encode("utf-16-le")
        if not self.user32.OpenClipboard(None):
            raise OSError("Không mở được clipboard")
        try:
            self.user32.EmptyClipboard()
            h = self.kernel32.GlobalAlloc(0x0042, len(data))
            if not h:
                raise OSError("GlobalAlloc thất bại")
            p = self.kernel32.GlobalLock(h)
            if not p:
                raise OSError("GlobalLock thất bại")
            c.memmove(p, data, len(data))
            self.kernel32.GlobalUnlock(h)
            if not self.user32.SetClipboardData(13, h):
                raise OSError("SetClipboardData thất bại")
        finally:
            self.user32.CloseClipboard()

    def release_all(self) -> None:
        with self._lock:
            for code in list(self._pressed):
                vk = VK.get(code)
                if vk is not None:
                    scan = self.user32.MapVirtualKeyW(vk, 0)
                    flags = 0x0002 | (0x0001 if code in self.EXTENDED else 0)
                    try:
                        self._key_input(vk, scan, flags)
                    except OSError:
                        pass
            self._pressed.clear()
            for name, up in (("left", 0x0004), ("right", 0x0010), ("middle", 0x0040)):
                try:
                    self._mouse(flags=up)
                except OSError:
                    pass
            self._buttons = 0


class X11Input(InputBackend):
    name = "x11-xtest"
    available = True
    detail = "XTest (X11/XWayland). Wayland native cần session X11 để tương thích đầy đủ."

    def __init__(self, display_name: str | None = None, bounds: tuple[int, int, int, int] | None = None) -> None:
        from Xlib import X, XK as XKmod, display
        from Xlib.ext import xtest

        self.X = X
        self.XKmod = XKmod
        self.xtest = xtest
        self.d = display.Display(display_name or os.environ.get("DISPLAY"))
        self.bounds = bounds or (0, 0, self.d.screen().width_in_pixels, self.d.screen().height_in_pixels)
        self._pressed: set[str] = set()
        self._buttons = 0
        self._lock = threading.Lock()

    def _keycode(self, code: str) -> int:
        name = XK.get(code)
        if not name:
            return 0
        ks = self.XKmod.string_to_keysym(name)
        return self.d.keysym_to_keycode(ks) if ks else 0

    def move_relative(self, dx: float, dy: float) -> None:
        with self._lock:
            self.xtest.fake_input(self.d, self.X.MotionNotify, detail=1, x=int(round(dx)), y=int(round(dy)))
            self.d.flush()

    def move_absolute(self, x: float, y: float) -> None:
        bx, by, bw, bh = self.bounds
        px = int(bx + x * max(1, bw - 1))
        py = int(by + y * max(1, bh - 1))
        with self._lock:
            self.xtest.fake_input(self.d, self.X.MotionNotify, detail=0, x=px, y=py)
            self.d.flush()

    def button(self, name: str, down: bool) -> None:
        b = {"left": 1, "right": 3, "middle": 2}[name]
        bit = {"left": 1, "right": 2, "middle": 4}[name]
        ev = self.X.ButtonPress if down else self.X.ButtonRelease
        with self._lock:
            if down:
                self._buttons |= bit
            else:
                self._buttons &= ~bit
            self.xtest.fake_input(self.d, ev, b)
            self.d.flush()

    def wheel(self, dx: float, dy: float) -> None:
        with self._lock:
            steps_y = int(round(abs(dy) * 3))
            for _ in range(min(12, steps_y)):
                b = 4 if dy > 0 else 5
                self.xtest.fake_input(self.d, self.X.ButtonPress, b)
                self.xtest.fake_input(self.d, self.X.ButtonRelease, b)
            steps_x = int(round(abs(dx) * 3))
            for _ in range(min(12, steps_x)):
                b = 7 if dx > 0 else 6
                self.xtest.fake_input(self.d, self.X.ButtonPress, b)
                self.xtest.fake_input(self.d, self.X.ButtonRelease, b)
            self.d.flush()

    def key(self, code: str, down: bool) -> None:
        kc = self._keycode(code)
        if not kc:
            return
        ev = self.X.KeyPress if down else self.X.KeyRelease
        with self._lock:
            if down:
                self._pressed.add(code)
            else:
                self._pressed.discard(code)
            self.xtest.fake_input(self.d, ev, kc)
            self.d.flush()

    def type_text(self, text: str) -> None:
        if shutil.which("xdotool"):
            subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "0", "--", text], check=True, timeout=5)
            return
        # ASCII fallback through keysyms.
        with self._lock:
            for ch in text[:256]:
                ks = self.XKmod.string_to_keysym(ch) if len(ch) == 1 and 32 <= ord(ch) < 127 else 0
                kc = self.d.keysym_to_keycode(ks) if ks else 0
                if kc:
                    self.xtest.fake_input(self.d, self.X.KeyPress, kc)
                    self.xtest.fake_input(self.d, self.X.KeyRelease, kc)
            self.d.flush()

    def clipboard_set(self, text: str) -> None:
        if shutil.which("xclip"):
            subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True, timeout=5)
        elif shutil.which("xsel"):
            subprocess.run(["xsel", "--clipboard", "--input"], input=text.encode(), check=True, timeout=5)
        else:
            raise OSError("Cần xclip hoặc xsel để đồng bộ clipboard")

    def release_all(self) -> None:
        with self._lock:
            for code in list(self._pressed):
                kc = self._keycode(code)
                if kc:
                    try:
                        self.xtest.fake_input(self.d, self.X.KeyRelease, kc)
                    except Exception:
                        pass
            self._pressed.clear()
            for b in (1, 2, 3):
                try:
                    self.xtest.fake_input(self.d, self.X.ButtonRelease, b)
                except Exception:
                    pass
            self._buttons = 0
            self.d.flush()

    def close(self) -> None:
        self.release_all()
        try:
            self.d.close()
        except Exception:
            pass


def create_input(settings, monitor_bounds: tuple[int, int, int, int] | None = None) -> InputBackend:
    if settings.demo:
        return DemoInput()
    if sys.platform == "win32":
        return WindowsInput()
    if sys.platform.startswith("linux"):
        if not os.environ.get("DISPLAY"):
            raise RuntimeError(
                "Không thấy DISPLAY. PhantomPlay hiện hỗ trợ Linux X11/XWayland. "
                "Hãy đăng nhập session X11 (hoặc bật XWayland) rồi chạy lại."
            )
        return X11Input(settings.display, monitor_bounds)
    raise RuntimeError("Hệ điều hành chưa hỗ trợ: cần Windows hoặc Linux")
