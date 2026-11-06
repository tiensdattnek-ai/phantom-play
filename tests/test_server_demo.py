import asyncio
import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from phantom.config import BIN, Settings
from phantom.security import hash_password
from phantom.server import PhantomServer


@pytest.fixture
def settings():
    s = Settings(demo=True, tunnel=False, audio=False, preset="data_saver")
    s.width, s.height, s.fps, s.bitrate = 320, 180, 10, 1000
    s.ffmpeg = str(BIN / "ffmpeg") if (BIN / "ffmpeg").exists() else "ffmpeg"
    return s


@pytest.mark.asyncio
async def test_login_and_ws_demo_stream(settings):
    server = PhantomServer(settings, hash_password("test123"))
    client = TestClient(TestServer(server.app))
    await client.start_server()
    try:
        meta = await (await client.get("/api/meta")).json()
        assert meta["demo"] is True

        bad = await client.post("/api/login", json={"password": "wrong"})
        assert bad.status == 401

        ok = await client.post("/api/login", json={"password": "test123"})
        assert ok.status == 200

        ws = await client.ws_connect("/ws")
        hello = await ws.receive_json(timeout=5)
        assert hello["type"] == "hello"
        assert hello["control"] is True

        got_config = False
        got_key = False
        deadline = asyncio.get_event_loop().time() + 12
        while asyncio.get_event_loop().time() < deadline and not (got_config and got_key):
            msg = await ws.receive(timeout=12)
            data = msg.data
            if isinstance(data, (bytes, bytearray)):
                kind = data[0]
                if kind == 3:
                    got_config = True
                elif kind == 1:
                    got_key = True
        assert got_config and got_key

        await ws.send_json({"type": "key", "code": "KeyW", "down": True})
        await ws.send_json({"type": "key", "code": "KeyW", "down": False})
        await ws.send_json({"type": "mouse", "mode": "relative", "dx": 3, "dy": 4, "buttons": 0})
        await ws.send_json({"type": "ping", "t": 1})
        pong = None
        for _ in range(40):
            m = await ws.receive(timeout=2)
            if isinstance(m.data, str):
                j = json.loads(m.data)
                if j.get("type") == "pong":
                    pong = j
                    break
        assert pong is not None
        await ws.close()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_ws_requires_auth(settings):
    server = PhantomServer(settings, hash_password("test123"))
    client = TestClient(TestServer(server.app))
    await client.start_server()
    try:
        r = await client.get("/ws")
        assert r.status == 401
    finally:
        await client.close()
