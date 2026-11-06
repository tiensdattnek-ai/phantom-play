# Testing

## Automated

```bash
pip install -r requirements-dev.txt
python scripts/bootstrap.py   # or install ffmpeg system-wide
python -m pytest -q
```

Covered:

- Password hashing/verification, session expiry, rate limiting.
- H.264 Annex-B → AVCC/avcC parsing and media header roundtrip.
- Input validation for mouse, keyboard and gamepad.
- Demo HTTP login flow and authenticated WebSocket.
- Real FFmpeg demo encode → binary config/keyframe received by client.
- JS syntax (`node --check`) and shell syntax (`bash -n`) in CI.
- Actions helper unit tests + workflow YAML/manual-trigger/retention checks.
- Local Linux X11 smoke: Xvfb + window manager + x11grab → H.264 config/keyframe, XTest input.

## Manual checklist on a real PC

1. `start.bat` / `start.sh` completes and prints a tunnel URL.
2. Wrong password is rejected; correct password enters the app.
3. Desktop capture shows the correct monitor.
4. Keyboard types into Notepad/text editor; WASD works in a game.
5. Relative trackpad moves the host cursor; tap/right-tap/two-finger scroll work.
6. Pointer lock works in an FPS; Esc releases.
7. Virtual gamepad appears in `joy.cpl` (Windows) or `jstest`/game (Linux).
8. Physical controller forwarded from client appears on host.
9. Audio plays from host output; mute/volume work.
10. Closing host kills tunnel URL and releases held keys.
11. Idle timeout closes viewers; second viewer is view-only until taking control.
12. MJPEG fallback works in a browser without WebCodecs.

## Known untested areas in the original sandbox

Windows SendInput/capture, ViGEmBus driver installation, WASAPI loopback, physical X11 desktop,
and public Cloudflare latency were not available in the headless Linux build environment.
