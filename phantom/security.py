from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 32


def hash_password(password: str, salt: bytes | None = None) -> str:
    if not isinstance(password, str) or not (1 <= len(password) <= 256):
        raise ValueError("Mật khẩu phải từ 1 đến 256 ký tự")
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=DKLEN)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, n, r, p, salt_hex, dk_hex = encoded.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(dk_hex))
        )
        return hmac.compare_digest(dk, bytes.fromhex(dk_hex))
    except Exception:
        return False


def generate_password() -> str:
    # ~72 bits, easy enough to copy from the host console.
    return secrets.token_urlsafe(9)


@dataclass
class Session:
    sid: str
    created: float
    expires: float
    viewer_id: str
    addr: str


class SessionManager:
    def __init__(self, ttl_hours: int = 8, max_sessions: int = 16):
        self.ttl = max(1, ttl_hours) * 3600
        self.max_sessions = max_sessions
        self._sessions: dict[str, Session] = {}

    def issue(self, addr: str) -> Session:
        self.prune()
        if len(self._sessions) >= self.max_sessions:
            oldest = min(self._sessions, key=lambda k: self._sessions[k].created)
            self._sessions.pop(oldest, None)
        now = time.time()
        s = Session(secrets.token_urlsafe(32), now, now + self.ttl, secrets.token_hex(4), addr)
        self._sessions[s.sid] = s
        return s

    def get(self, sid: Optional[str]) -> Optional[Session]:
        if not sid:
            return None
        self.prune()
        s = self._sessions.get(sid)
        if not s or s.expires < time.time():
            return None
        return s

    def revoke(self, sid: str) -> None:
        self._sessions.pop(sid, None)

    def prune(self) -> None:
        now = time.time()
        for k in [k for k, s in self._sessions.items() if s.expires < now]:
            self._sessions.pop(k, None)

    def count(self) -> int:
        self.prune()
        return len(self._sessions)


class RateLimiter:
    """Small in-memory sliding-window limiter for login attempts."""

    def __init__(self, limit: int = 6, window: int = 60, global_limit: int = 40):
        self.limit = limit
        self.window = window
        self.global_limit = global_limit
        self._hits: dict[str, list[float]] = {}
        self._global: list[float] = []

    def check(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        self._global = [t for t in self._global if now - t < self.window]
        if len(self._global) >= self.global_limit:
            return False, self.window
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        self._hits[key] = hits
        if len(hits) >= self.limit:
            retry = max(1, int(self.window - (now - hits[0])))
            return False, retry
        hits.append(now)
        self._global.append(now)
        return True, 0

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


def client_ip(request) -> str:
    # Quick Tunnel terminates at cloudflared on loopback; trust only the local proxy.
    peer = request.remote or ""
    if peer in ("127.0.0.1", "::1"):
        cf = request.headers.get("CF-Connecting-IP")
        if cf:
            return cf.strip()[:64]
        xf = request.headers.get("X-Forwarded-For", "")
        if xf:
            return xf.split(",")[0].strip()[:64]
    return peer or "unknown"


def origin_ok(request) -> bool:
    origin = request.headers.get("Origin")
    if not origin:
        return True  # non-browser clients / tests; cookie+password still required
    try:
        from urllib.parse import urlsplit

        o = urlsplit(origin)
        host = (request.headers.get("X-Forwarded-Host") or request.host or "").split(",")[0].split(":")[0].lower()
        return (o.hostname or "").lower() == host
    except Exception:
        return False
