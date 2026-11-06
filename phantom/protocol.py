from __future__ import annotations

import re
import struct
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

# Binary media frame: uint8 type, uint32 sequence, uint64 pts_us, payload.
HEADER = struct.Struct("<BIQ")
VIDEO_KEY = 1
VIDEO_DELTA = 2
VIDEO_CONFIG = 3
AUDIO_PCM = 4
JPEG_FRAME = 5


def pack_media(kind: int, seq: int, pts_us: int, payload: bytes) -> bytes:
    return HEADER.pack(kind, seq & 0xFFFFFFFF, pts_us & 0xFFFFFFFFFFFFFFFF) + payload


def unpack_media(data: bytes) -> tuple[int, int, int, bytes]:
    if len(data) < HEADER.size:
        raise ValueError("media frame quá ngắn")
    kind, seq, pts = HEADER.unpack_from(data)
    return kind, seq, pts, data[HEADER.size :]


_START = re.compile(rb"\x00\x00\x00\x01|\x00\x00\x01")


def _strip_trailing_zeros(b: bytes) -> bytes:
    return b.rstrip(b"\x00")


def _rbsp(nal: bytes) -> bytes:
    # Remove emulation prevention bytes (00 00 03 -> 00 00).
    out = bytearray()
    zeros = 0
    for x in nal:
        if zeros >= 2 and x == 3:
            zeros = 0
            continue
        out.append(x)
        zeros = zeros + 1 if x == 0 else 0
    return bytes(out)


@dataclass
class AccessUnit:
    data: bytes          # AVCC (length-prefixed) for WebCodecs
    key: bool
    pts_us: int
    nals: list[bytes] = field(default_factory=list)


class H264Parser:
    """Parse Annex-B H.264 with AUDs into AVCC access units + avcC config.

    The encoder is asked to insert Access Unit Delimiters so frame boundaries
    are explicit. A fallback boundary detector handles streams without AUD.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._nals: list[bytes] = []
        self.sps: Optional[bytes] = None
        self.pps: Optional[bytes] = None
        self._last_vcl_seen = False

    @property
    def codec(self) -> str:
        if not self.sps or len(self.sps) < 4:
            return "avc1.42E01E"
        return "avc1." + self.sps[1:4].hex().upper()

    @property
    def avcc(self) -> Optional[bytes]:
        if not self.sps or not self.pps:
            return None
        sps, pps = self.sps, self.pps
        return (
            bytes([1, sps[1], sps[2], sps[3], 0xFF, 0xE1])
            + struct.pack(">H", len(sps))
            + sps
            + bytes([1])
            + struct.pack(">H", len(pps))
            + pps
        )

    def feed(self, chunk: bytes) -> list[AccessUnit]:
        self._buf.extend(chunk)
        out: list[AccessUnit] = []
        matches = list(_START.finditer(self._buf))
        if len(matches) < 2:
            # Keep potential partial start code; avoid unbounded growth on garbage.
            if len(self._buf) > 8 * 1024 * 1024:
                self._buf.clear()
            return out
        for i in range(len(matches) - 1):
            a, b = matches[i], matches[i + 1]
            nal = _strip_trailing_zeros(bytes(self._buf[a.end() : b.start()]))
            if nal:
                out.extend(self._push_nal(nal))
        last = matches[-1]
        del self._buf[: last.start()]
        return out

    def _is_new_au(self, nal: bytes) -> bool:
        t = nal[0] & 0x1F
        if t == 9:
            return True
        if t in (1, 5) and self._last_vcl_seen:
            # first_mb_in_slice == 0 starts a new picture.
            rbsp = _rbsp(nal[1:])
            return bool(rbsp) and (rbsp[0] & 0x80) != 0
        return False

    def _push_nal(self, nal: bytes) -> list[AccessUnit]:
        t = nal[0] & 0x1F
        out: list[AccessUnit] = []
        if self._nals and self._is_new_au(nal):
            au = self._emit()
            if au:
                out.append(au)
        if t == 7:
            self.sps = nal
        elif t == 8:
            self.pps = nal
        if t in (1, 5):
            self._last_vcl_seen = True
        self._nals.append(nal)
        return out

    def _emit(self) -> Optional[AccessUnit]:
        if not self._nals:
            return None
        nals = self._nals
        self._nals = []
        self._last_vcl_seen = False
        key = any((n[0] & 0x1F) == 5 for n in nals)
        parts = []
        for n in nals:
            t = n[0] & 0x1F
            # AUD/SPS/PPS live in avcC description; samples carry VCL/SEI.
            if t in (7, 8, 9):
                continue
            parts.append(struct.pack(">I", len(n)) + n)
        if not parts:
            return None
        return AccessUnit(b"".join(parts), key, time.monotonic_ns() // 1000, nals)

    def flush(self) -> list[AccessUnit]:
        # Process trailing bytes if a complete NAL is present.
        matches = list(_START.finditer(self._buf))
        out: list[AccessUnit] = []
        if matches:
            a = matches[-1]
            nal = _strip_trailing_zeros(bytes(self._buf[a.end() :]))
            if nal:
                out.extend(self._push_nal(nal))
            self._buf.clear()
        au = self._emit()
        if au:
            out.append(au)
        return out


class MjpegParser:
    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf.extend(chunk)
        out = []
        while True:
            start = self._buf.find(b"\xff\xd8")
            if start < 0:
                self._buf.clear()
                break
            end = self._buf.find(b"\xff\xd9", start + 2)
            if end < 0:
                if start > 0:
                    del self._buf[:start]
                if len(self._buf) > 16 * 1024 * 1024:
                    self._buf.clear()
                break
            frame = bytes(self._buf[start : end + 2])
            del self._buf[: end + 2]
            out.append(frame)
        return out


# ---- input validation -------------------------------------------------------

KEY_RE = re.compile(
    r"^(?:Key[A-Z]|Digit[0-9]|F(?:[1-9]|1[0-2])|Escape|Tab|CapsLock|ShiftLeft|ShiftRight|"
    r"ControlLeft|ControlRight|AltLeft|AltRight|MetaLeft|MetaRight|Space|Enter|Backspace|Delete|Insert|"
    r"Home|End|PageUp|PageDown|ArrowUp|ArrowDown|ArrowLeft|ArrowRight|PrintScreen|ScrollLock|Pause|"
    r"NumLock|Numpad(?:[0-9]|Add|Subtract|Multiply|Divide|Decimal|Enter)|"
    r"Minus|Equal|BracketLeft|BracketRight|Backslash|Semicolon|Quote|Comma|Period|Slash|Backquote|ContextMenu)$"
)


class InputError(ValueError):
    pass


def fnum(v, lo: float, hi: float, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise InputError(f"{name} phải là số")
    v = float(v)
    if v != v or v in (float("inf"), float("-inf")) or not lo <= v <= hi:
        raise InputError(f"{name} ngoài phạm vi")
    return v


def inum(v, lo: int, hi: int, name: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise InputError(f"{name} phải là số nguyên")
    if not lo <= v <= hi:
        raise InputError(f"{name} ngoài phạm vi")
    return v


def validate_input(msg: dict) -> dict:
    t = msg.get("type")
    if t == "mouse":
        mode = msg.get("mode", "relative")
        if mode not in ("relative", "absolute"):
            raise InputError("mouse mode không hợp lệ")
        out = {"type": "mouse", "mode": mode}
        if mode == "relative":
            out["dx"] = fnum(msg.get("dx", 0), -400, 400, "dx")
            out["dy"] = fnum(msg.get("dy", 0), -400, 400, "dy")
        else:
            out["x"] = fnum(msg.get("x", 0), 0, 1, "x")
            out["y"] = fnum(msg.get("y", 0), 0, 1, "y")
        buttons = inum(msg.get("buttons", 0), 0, 7, "buttons")
        out["buttons"] = buttons
        return out
    if t == "mouse_button":
        b = msg.get("button")
        if b not in ("left", "right", "middle"):
            raise InputError("button không hợp lệ")
        return {"type": "mouse_button", "button": b, "down": bool(msg.get("down"))}
    if t == "wheel":
        return {"type": "wheel", "dx": fnum(msg.get("dx", 0), -10, 10, "dx"), "dy": fnum(msg.get("dy", 0), -10, 10, "dy")}
    if t == "key":
        code = msg.get("code", "")
        if not isinstance(code, str) or not KEY_RE.fullmatch(code):
            raise InputError("mã phím không được hỗ trợ")
        return {"type": "key", "code": code, "down": bool(msg.get("down"))}
    if t == "text":
        text = msg.get("text", "")
        if not isinstance(text, str) or len(text) > 256:
            raise InputError("text quá dài")
        if any(ord(c) < 32 and c not in "\n\t\r" for c in text):
            raise InputError("text chứa ký tự điều khiển")
        return {"type": "text", "text": text}
    if t == "gamepad":
        axes = msg.get("axes", [0, 0, 0, 0])
        buttons = msg.get("buttons", [])
        if not isinstance(axes, list) or len(axes) != 4:
            raise InputError("axes phải gồm 4 phần tử")
        if not isinstance(buttons, list) or len(buttons) > 20:
            raise InputError("buttons không hợp lệ")
        return {
            "type": "gamepad",
            "axes": [fnum(a, -1, 1, "axis") for a in axes],
            "buttons": [fnum(b, 0, 1, "button") for b in buttons],
        }
    if t == "clipboard":
        text = msg.get("text", "")
        if not isinstance(text, str) or len(text) > 65536:
            raise InputError("clipboard quá dài")
        return {"type": "clipboard", "text": text}
    raise InputError("loại input không hỗ trợ")
