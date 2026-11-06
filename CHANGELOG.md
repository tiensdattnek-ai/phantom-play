# Changelog

## 1.1.0 — 2026-11-06

GitHub Actions remote desktop.

- New manual workflow `Remote desktop (PhantomPlay)` for `windows-latest` and `ubuntu-latest`.
- Ubuntu provisions Xvfb + XFCE; Windows uses the hosted interactive desktop.
- `scripts/actions_remote.py` starts host/tunnel, verifies public login + H.264 keyframe,
  writes Job Summary and short-lived connection artifact, keeps session alive, cleans up.
- Random password masked in logs; optional repository secret `PHANTOM_REMOTE_PASSWORD`.
- View-only, resolution/FPS/duration inputs; CPU x264 encoding; no public RDP/VNC.
- Added `psutil`, `--no-qr`, Actions docs and workflow/helper tests.

## 1.0.0 — 2026-11-06

Initial premium browser remote-play client.

- One-click `start.bat` / `start.sh` bootstrap: venv, Python deps, FFmpeg, cloudflared.
- Cloudflare Quick Tunnel with QR + `runtime/session.json`; link dies with the host process.
- Mandatory session password (scrypt hash), rate-limited login, HttpOnly/SameSite cookie.
- Low-latency H.264 → WebCodecs pipeline with avcC config, 1s GOP, hardware encoder preference
  (NVENC/QSV/AMF/VAAPI) and libx264 fallback; MJPEG compatibility mode.
- Responsive PC/mobile UI: fullscreen, pointer lock, trackpad gestures, special keys,
  virtual gamepad overlay, physical Gamepad API forwarding, stats, screenshots, wake lock.
- Windows SendInput scancode/relative mouse/Unicode; Linux XTest; virtual Xbox pad via
  vgamepad with keyboard/mouse fallback.
- Optional system audio: WASAPI loopback (Windows) / PulseAudio monitor (Linux) → PCM worklet.
- Safe `--demo` mode, view-only mode, idle timeout, control lease, input validation.
- Tests for auth, protocol, input validation and demo WebSocket streaming.
