from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from aiohttp import WSMsgType, web

from . import PRODUCT, __version__
from .audio import AudioCapture
from .config import PRESETS, WEB, Settings, clamp_quality
from .gamepad import GamepadBackend, KeyboardGamepad, VGamepad, create_gamepad
from .input_backend import InputBackend, create_input
from .protocol import InputError, validate_input
from .security import RateLimiter, SessionManager, client_ip, origin_ok, verify_password
from .video import VideoStream, monitor_bounds

log = logging.getLogger("phantom.server")
COOKIE = "phantom_session"


class PhantomServer:
    def __init__(self, settings: Settings, password_hash: str):
        self.settings = settings
        self.password_hash = password_hash
        self.sessions = SessionManager(settings.session_hours)
        self.limiter = RateLimiter()
        self.input: InputBackend = create_input(settings, monitor_bounds(settings))
        self.gamepad: GamepadBackend = create_gamepad(settings, self.input)
        self.video = VideoStream(settings)
        self.video.demo_input = self.input if settings.demo else None
        self.video.demo_gamepad = self.gamepad if settings.demo else None
        self.audio = AudioCapture(settings, self._broadcast_audio)
        self.connections: dict[str, web.WebSocketResponse] = {}
        self.control_owner: Optional[str] = None
        self.last_activity = time.monotonic()
        self.last_quality_change = 0.0
        self._adaptive_bad = 0
        self._adaptive_good = 0
        self._stop_media_task: Optional[asyncio.Task] = None
        self.app = web.Application(client_max_size=64 * 1024)
        self._routes()
        self.app.on_startup.append(self._on_startup)
        self.app.on_cleanup.append(self._on_cleanup)

    def _routes(self) -> None:
        self.app.router.add_get("/", self.index)
        self.app.router.add_get("/api/health", self.health)
        self.app.router.add_get("/api/meta", self.meta)
        self.app.router.add_post("/api/login", self.login)
        self.app.router.add_post("/api/logout", self.logout)
        self.app.router.add_get("/api/session", self.session_check)
        self.app.router.add_get("/ws", self.websocket)
        self.app.router.add_static("/static/", WEB, show_index=False)
        self.app.router.add_get("/manifest.webmanifest", self.manifest)
        self.app.middlewares.append(self._security_headers)

    @web.middleware
    async def _security_headers(self, request: web.Request, handler):
        resp = await handler(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        csp = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' ws: wss:; "
            "worker-src 'self' blob:; base-uri 'none'; form-action 'none'; object-src 'none'"
        )
        if not self.settings.demo:
            csp += "; frame-ancestors 'none'"
            resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = csp
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    async def _on_startup(self, app: web.Application) -> None:
        self._idle_task = asyncio.create_task(self._idle_watch())

    async def _on_cleanup(self, app: web.Application) -> None:
        self._idle_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._idle_task
        for ws in list(self.connections.values()):
            await ws.close(code=1001, message=b"server shutdown")
        await self.video.stop()
        await self.audio.stop()
        self.input.close()
        self.gamepad.close()

    async def index(self, request: web.Request) -> web.Response:
        return web.FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})

    async def manifest(self, request: web.Request) -> web.Response:
        return web.json_response({
            "name": PRODUCT, "short_name": PRODUCT, "start_url": "/", "display": "standalone",
            "background_color": "#0a0e14", "theme_color": "#0a0e14",
            "icons": [{"src": "/static/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
        })

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "product": PRODUCT, "version": __version__})

    async def meta(self, request: web.Request) -> web.Response:
        s = self.settings
        return web.json_response({
            "product": PRODUCT, "version": __version__, "hostname": s.hostname,
            "demo": s.demo, "view_only": s.view_only, "max_viewers": s.max_viewers,
            "idle_timeout": s.idle_timeout, "clipboard": s.clipboard,
            "presets": PRESETS,
            "input": {"name": self.input.name, "available": self.input.available, "detail": self.input.detail},
            "gamepad": {"name": self.gamepad.name, "available": self.gamepad.available, "detail": self.gamepad.detail},
        })

    def _session(self, request: web.Request):
        return self.sessions.get(request.cookies.get(COOKIE))

    async def login(self, request: web.Request) -> web.Response:
        if not origin_ok(request):
            return web.json_response({"error": "Origin không hợp lệ"}, status=403)
        ip = client_ip(request)
        ok, retry = self.limiter.check(ip)
        if not ok:
            return web.json_response({"error": "Thử lại quá nhiều lần", "retry_after": retry}, status=429,
                                     headers={"Retry-After": str(retry)})
        if request.content_length and request.content_length > 4096:
            return web.json_response({"error": "Payload quá lớn"}, status=413)
        try:
            data = await request.json()
            password = data.get("password", "")
        except Exception:
            return web.json_response({"error": "JSON không hợp lệ"}, status=400)
        if not isinstance(password, str) or not verify_password(password, self.password_hash):
            log.warning("login failed ip=%s", ip)
            return web.json_response({"error": "Mật khẩu không đúng"}, status=401)
        self.limiter.reset(ip)
        sess = self.sessions.issue(ip)
        resp = web.json_response({"ok": True, "viewer_id": sess.viewer_id, "expires": sess.expires})
        secure = request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
        resp.set_cookie(COOKIE, sess.sid, max_age=int(sess.expires - time.time()), httponly=True,
                        secure=secure, samesite="Strict", path="/")
        log.info("login ok ip=%s viewer=%s", ip, sess.viewer_id)
        return resp

    async def logout(self, request: web.Request) -> web.Response:
        sess = self._session(request)
        if sess:
            self.sessions.revoke(sess.sid)
            ws = self.connections.pop(sess.sid, None)
            if ws:
                await ws.close(code=1000, message=b"logout")
        resp = web.json_response({"ok": True})
        resp.del_cookie(COOKIE, path="/")
        return resp

    async def session_check(self, request: web.Request) -> web.Response:
        sess = self._session(request)
        if not sess:
            return web.json_response({"ok": False}, status=401)
        return web.json_response({"ok": True, "viewer_id": sess.viewer_id, "expires": sess.expires})

    def _hello(self, sid: str) -> dict:
        s = self.settings
        return {
            "type": "hello", "product": PRODUCT, "version": __version__,
            "viewer_id": self.sessions.get(sid).viewer_id if self.sessions.get(sid) else sid[:8],
            "control": self.control_owner == sid and not s.view_only,
            "control_owner": self._viewer_of(self.control_owner),
            "settings": s.public_dict(), "video": self.video.status(), "audio": self.audio.status(),
            "input": {"name": self.input.name, "detail": self.input.detail},
            "gamepad": {"name": self.gamepad.name, "detail": self.gamepad.detail},
            "presets": PRESETS,
        }

    def _viewer_of(self, sid: Optional[str]) -> Optional[str]:
        if not sid:
            return None
        s = self.sessions.get(sid)
        return s.viewer_id if s else sid[:8]

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        sess = self._session(request)
        if not sess or not origin_ok(request):
            return web.json_response({"error": "Chưa xác thực"}, status=401)
        if len(self.connections) >= self.settings.max_viewers and sess.sid not in self.connections:
            return web.json_response({"error": "Đã đủ số người xem"}, status=409)
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=64 * 1024, compress=False)
        await ws.prepare(request)
        sid = sess.sid
        old = self.connections.get(sid)
        if old:
            await old.close(code=1000, message=b"replaced")
        self.connections[sid] = ws
        if self.control_owner is None and not self.settings.view_only:
            self.control_owner = sid
        sub = self.video.subscribe(sid)
        await ws.send_json(self._hello(sid))
        await self._broadcast_control()
        await self.video.ensure()
        if self.settings.audio:
            await self.audio.start()
        if self._stop_media_task:
            self._stop_media_task.cancel()
        log.info("viewer connected id=%s total=%d", sess.viewer_id, len(self.connections))
        writer = asyncio.create_task(self._writer(ws, sub))
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_text(sid, ws, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            writer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await writer
            self.video.unsubscribe(sid)
            self.connections.pop(sid, None)
            if self.control_owner == sid:
                self.input.release_all()
                self.gamepad.reset()
                self.control_owner = None
            await self._broadcast_control()
            if not self.connections:
                self._stop_media_task = asyncio.create_task(self._stop_media_soon())
            log.info("viewer disconnected id=%s total=%d", sess.viewer_id, len(self.connections))
        return ws

    async def _writer(self, ws: web.WebSocketResponse, sub) -> None:
        try:
            while not ws.closed:
                kind, payload = await sub.queue.get()
                if kind == "media":
                    await ws.send_bytes(payload)
                else:
                    await ws.send_json(payload)
        except (asyncio.CancelledError, ConnectionResetError):
            raise
        except Exception:
            pass

    async def _stop_media_soon(self) -> None:
        try:
            await asyncio.sleep(5)
            if not self.connections:
                await self.video.stop()
                await self.audio.stop()
        except asyncio.CancelledError:
            pass

    async def _idle_watch(self) -> None:
        while True:
            await asyncio.sleep(15)
            timeout = self.settings.idle_timeout
            if timeout and self.connections and time.monotonic() - self.last_activity > timeout:
                log.info("idle timeout; closing viewers")
                for ws in list(self.connections.values()):
                    await ws.close(code=4001, message=b"idle timeout")
                self.input.release_all()
                self.gamepad.reset()
                self.last_activity = time.monotonic()

    def _broadcast_audio(self, data: bytes) -> None:
        for sid, sub in list(self.video.subs.items()):
            self.video._put(sub, ("media", data))

    async def _broadcast_json(self, msg: dict) -> None:
        for ws in list(self.connections.values()):
            if not ws.closed:
                with contextlib.suppress(Exception):
                    await ws.send_json(msg)

    async def _broadcast_control(self) -> None:
        await self._broadcast_json({
            "type": "control", "owner": self._viewer_of(self.control_owner),
            "view_only": self.settings.view_only,
        })

    async def _handle_text(self, sid: str, ws: web.WebSocketResponse, raw: str) -> None:
        try:
            msg = json.loads(raw)
            if not isinstance(msg, dict):
                raise InputError("message phải là object")
        except Exception:
            await ws.send_json({"type": "error", "message": "JSON không hợp lệ"})
            return
        t = msg.get("type")
        if t not in ("ping", "stats"):
            self.last_activity = time.monotonic()
        try:
            if t == "ping":
                await ws.send_json({"type": "pong", "t": msg.get("t", 0)})
                return
            if t == "control":
                action = msg.get("action")
                if self.settings.view_only:
                    raise InputError("Host đang bật view-only")
                if action == "take":
                    if self.control_owner and self.control_owner != sid:
                        self.input.release_all()
                        self.gamepad.reset()
                    self.control_owner = sid
                elif action == "release":
                    if self.control_owner == sid:
                        self.input.release_all()
                        self.gamepad.reset()
                        self.control_owner = None
                else:
                    raise InputError("control action không hợp lệ")
                await self._broadcast_control()
                await ws.send_json(self._hello(sid))
                return
            if t == "quality":
                if self.control_owner != sid:
                    raise InputError("Chỉ người điều khiển được đổi chất lượng")
                await self._set_quality(msg)
                return
            if t == "gamepad_mode":
                if self.control_owner != sid:
                    raise InputError("Chỉ người điều khiển được đổi gamepad")
                mode = msg.get("mode")
                if mode not in ("virtual", "keyboard"):
                    raise InputError("gamepad mode không hợp lệ")
                self.gamepad.close()
                if mode == "virtual" and not self.settings.demo:
                    try:
                        self.gamepad = VGamepad()
                    except Exception:
                        self.gamepad = KeyboardGamepad(self.input)
                else:
                    self.gamepad = KeyboardGamepad(self.input) if not self.settings.demo else self.gamepad
                await self._broadcast_json({"type": "gamepad_status", "gamepad": {"name": self.gamepad.name, "detail": self.gamepad.detail}})
                return
            if t == "audio":
                if self.control_owner != sid:
                    raise InputError("Chỉ người điều khiển được đổi audio")
                self.settings.audio = bool(msg.get("enabled", True))
                if self.settings.audio:
                    await self.audio.start()
                else:
                    await self.audio.stop()
                await self._broadcast_json({"type": "audio_status", "audio": self.audio.status()})
                return
            if t == "stats":
                await self._client_stats(sid, msg)
                return
            # Input requires control lease.
            if self.settings.view_only or self.control_owner != sid:
                raise InputError("Bạn đang ở chế độ chỉ xem")
            validated = validate_input(msg)
            await self._apply_input(validated)
        except InputError as exc:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception as exc:
            log.exception("input error")
            self.input.release_all()
            self.gamepad.reset()
            await ws.send_json({"type": "input_error", "message": f"{type(exc).__name__}: {exc}"})

    async def _apply_input(self, msg: dict) -> None:
        t = msg["type"]
        if t == "mouse":
            if msg["mode"] == "relative":
                self.input.move_relative(msg["dx"], msg["dy"])
            else:
                self.input.move_absolute(msg["x"], msg["y"])
            self.input.set_buttons(msg.get("buttons", 0))
        elif t == "mouse_button":
            self.input.button(msg["button"], msg["down"])
        elif t == "wheel":
            self.input.wheel(msg["dx"], msg["dy"])
        elif t == "key":
            self.input.key(msg["code"], msg["down"])
        elif t == "text":
            self.input.type_text(msg["text"])
        elif t == "gamepad":
            self.gamepad.update(msg["axes"], msg["buttons"])
        elif t == "clipboard":
            if not self.settings.clipboard:
                raise InputError("Clipboard đang tắt trên host")
            self.input.clipboard_set(msg["text"])

    async def _set_quality(self, msg: dict) -> None:
        now = time.monotonic()
        if now - self.last_quality_change < 1.5:
            raise InputError("Đổi chất lượng quá nhanh")
        s = self.settings
        if "preset" in msg and msg["preset"] in PRESETS:
            s.apply_preset(str(msg["preset"]))
        else:
            s.width, s.height, s.fps, s.bitrate = clamp_quality(
                msg.get("width", s.width), msg.get("height", s.height),
                msg.get("fps", s.fps), msg.get("bitrate", s.bitrate),
            )
            s.preset = "custom"
        if msg.get("codec") in ("h264", "mjpeg"):
            s.codec = msg["codec"]
        if "adaptive" in msg:
            s.adaptive = bool(msg["adaptive"])
        self.last_quality_change = now
        self.video.bounds = monitor_bounds(s)
        await self.video.restart()
        await self._broadcast_json({"type": "quality", "settings": s.public_dict(), "video": self.video.status()})

    async def _client_stats(self, sid: str, msg: dict) -> None:
        if not self.settings.adaptive or self.control_owner != sid:
            return
        rtt = float(msg.get("rtt", 0))
        queue = float(msg.get("decode_queue", 0))
        now = time.monotonic()
        if rtt > 140 or queue > 5:
            self._adaptive_bad += 1
            self._adaptive_good = 0
        elif rtt < 60 and queue < 2:
            self._adaptive_good += 1
            self._adaptive_bad = 0
        else:
            self._adaptive_bad = self._adaptive_good = 0
        if self._adaptive_bad >= 3 and now - self.last_quality_change > 20 and self.settings.bitrate > 2000:
            self.settings.bitrate = max(2000, int(self.settings.bitrate * 0.75))
            self.settings.preset = "custom"
            self.last_quality_change = now
            self._adaptive_bad = 0
            await self.video.restart()
            await self._broadcast_json({"type": "quality", "settings": self.settings.public_dict(), "video": self.video.status(), "reason": "adaptive-down"})
        elif self._adaptive_good >= 12 and now - self.last_quality_change > 30:
            cap = int(PRESETS.get(self.settings.preset, PRESETS["balanced"])["bitrate"])
            if self.settings.bitrate < cap:
                self.settings.bitrate = min(cap, int(self.settings.bitrate * 1.25))
                self.last_quality_change = now
                self._adaptive_good = 0
                await self.video.restart()
                await self._broadcast_json({"type": "quality", "settings": self.settings.public_dict(), "video": self.video.status(), "reason": "adaptive-up"})


async def run_server(settings: Settings, password_hash: str) -> tuple[PhantomServer, web.AppRunner]:
    server = PhantomServer(settings, password_hash)
    runner = web.AppRunner(server.app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, settings.host, settings.port)
    await site.start()
    return server, runner
