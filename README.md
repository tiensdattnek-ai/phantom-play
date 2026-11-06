# PhantomPlay

Remote play trong trình duyệt, lấy cảm hứng từ workflow noVNC nhưng đi theo hướng **game**:
H.264 độ trễ thấp bằng WebCodecs, ưu tiên encoder phần cứng, trackpad cảm ứng, gamepad ảo,
fullscreen/pointer-lock và launcher một chạm.

> Repo này là **client + host tự chạy trên PC của bạn**. Không có server trung gian lưu video.
> Cloudflare Quick Tunnel chỉ là đường hầm tạm thời để bạn mở link từ xa.

## Tính năng chính

- **Một chạm**: `start.bat` (Windows) / `start.sh` (Linux) tự tạo venv, cài dependencies,
  tải FFmpeg + cloudflared vào `runtime/bin`.
- **Link remote tạm thời**: in URL `*.trycloudflare.com` + QR code. Tắt host/Ctrl+C là link mất.
- **Mật khẩu bắt buộc**: nhập lúc khởi động hoặc Enter để tự tạo. Hash scrypt, không lưu plaintext.
- **Video tối ưu game**: H.264 Annex-B → AVCC/WebCodecs, GOP 1 giây, ưu tiên NVENC/QSV/AMF/VAAPI,
  fallback `libx264 ultrafast/zerolatency`. Có MJPEG cho trình duyệt không hỗ trợ WebCodecs.
- **PC & mobile**: fullscreen, khóa chuột kiểu FPS, trackpad tương đối, phím đặc biệt,
  gamepad ảo cảm ứng, chuyển tiếp tay cầm vật lý qua Gamepad API.
- **Âm thanh hệ thống** tuỳ chọn: WASAPI loopback trên Windows, PulseAudio/PipeWire monitor trên Linux.
- **An toàn hơn mặc định**: bind loopback, không mở port inbound, rate-limit login,
  cookie HttpOnly/SameSite, giới hạn người xem, control lease, idle timeout, view-only,
  validation input, clipboard mặc định tắt.
- **Demo an toàn**: `--demo` dựng màn hình giả lập để test UI/stream mà không capture/điều khiển máy thật.

## Bắt đầu nhanh

### Windows

1. Giải nén repo.
2. Double-click `start.bat`.
3. Lần đầu nhập mật khẩu (hoặc Enter để tự tạo). Lưu mật khẩu hiện trong console.
4. Chờ dòng `LINK REMOTE:` rồi mở link `https://....trycloudflare.com` trên PC/điện thoại.
5. Nhập mật khẩu để vào phiên.

Nếu Windows hỏi UAC khi cài ViGEmBus/gamepad, đó là driver tay cầm ảo. Bạn có thể bỏ qua;
client vẫn có chế độ **gamepad → phím/chuột**.

### Linux

```bash
chmod +x start.sh scripts/*.sh
./start.sh
```

Khuyến nghị session **X11** hoặc XWayland. Wayland native chưa được hỗ trợ đầy đủ trong bản này.
Nếu muốn gamepad ảo XInput thật:

```bash
./scripts/setup-linux-gamepad.sh
```

Script này cần `sudo` để bật `uinput` + udev rule. Nếu không, gamepad sẽ fallback sang phím/chuột.

### Chỉ chạy local, không mở tunnel

```bash
python -m phantom --no-tunnel
# mở http://127.0.0.1:8787
```

### Demo an toàn

```bash
python -m phantom --demo --no-tunnel
```

Demo không capture màn hình thật và không gửi input vào hệ điều hành.

## Remote desktop bằng GitHub Actions

Muốn remote máy CI tạm thời thay vì PC ở nhà:

1. Vào **Actions → Remote desktop (PhantomPlay) → Run workflow**.
2. Chọn `both`, `windows-latest` hoặc `ubuntu-latest`, thời gian, độ phân giải, FPS.
3. Chờ bước **Wait for public URL and verify stream** thành công.
4. Lấy link trong **Job Summary**; mật khẩu nằm trong artifact `phantom-remote-...` (1 ngày)
   hoặc trong repository secret `PHANTOM_REMOTE_PASSWORD` nếu bạn đã đặt.
5. **Cancel workflow** để dừng ngay.

Ubuntu chạy XFCE trên Xvfb; Windows dùng desktop interactive của hosted runner. Đây là máy CI
tạm thời, không có GPU gaming, không phải dịch vụ luôn-on. Chi tiết: [`docs/GITHUB_ACTIONS.md`](docs/GITHUB_ACTIONS.md).

## Mật khẩu

Thứ tự ưu tiên:

1. Biến môi trường `PHANTOM_PASSWORD`
2. `--password-file /path/to/file` (đọc dòng đầu)
3. Prompt ẩn khi chạy interactive
4. Tự tạo mật khẩu ngẫu nhiên và in **một lần** ra console

Ví dụ:

```bash
PHANTOM_PASSWORD='doi-mat-khau-manh' python -m phantom
```

Không commit file mật khẩu, không dán mật khẩu vào chat công khai.

## Điều khiển

### PC

- Click vào màn hình để bắt phím.
- **Chạm trực tiếp**: chuột ánh xạ tuyệt đối vào vùng video.
- **Khóa chuột (FPS)**: click màn hình để pointer-lock; `Esc` thoát khóa chuột.
- Phím hỗ trợ: chữ/số, F1–F12, Esc/Tab/Ctrl/Alt/Shift/Win, mũi tên, điều hướng, numpad, ký tự OEM.
- Một số tổ hợp hệ thống/browser vẫn bị giữ lại bởi OS/browser.

### Mobile / Trackpad

- 1 ngón: di chuột tương đối.
- Chạm nhanh: click trái.
- Chạm giữ rồi kéo: giữ chuột trái (drag).
- 2 ngón chạm nhanh: click phải.
- 2 ngón vuốt: cuộn.
- 3 ngón chạm nhanh: click giữa.
- Nút **Giữ kéo**: drag-lock.

### Gamepad

- Cắm tay cầm Xbox/PS rồi bấm một nút để browser nhận.
- Hoặc bật overlay gamepad ảo trên màn hình.
- Host tạo thiết bị Xbox 360 ảo qua `vgamepad` khi có ViGEmBus (Windows) hoặc `uinput` (Linux).
- Nếu thiếu driver/quyền, chọn **Ánh xạ phím/chuột**: cần trái → WASD, cần phải → chuột,
  A/B/X/Y/LB/RB/LT/RT → phím/chuột tương ứng.

## Chất lượng

| Preset | Độ phân giải | FPS | Bitrate |
|---|---:|---:|---:|
| Tiết kiệm | 1280×720 | 30 | 3 Mbps |
| Cân bằng | 1920×1080 | 60 | 8 Mbps |
| Ultra | 1920×1080 | 60 | 16 Mbps |
| LAN | 1920×1080 | 120 | 30 Mbps |

Đổi preset trong **Cài đặt** sẽ restart encoder để áp dụng ngay. Adaptive bitrate là thử nghiệm:
khi mạng xấu nó giảm bitrate và có thể gây khựng nhẹ do restart encoder.

## Kiến trúc

```text
PC host
  ├─ capture: gdigrab/ddagrab (Windows) hoặc x11grab (Linux)
  ├─ encode: FFmpeg H.264 (NVENC/QSV/AMF/VAAPI/libx264) hoặc MJPEG
  ├─ input: SendInput / XTest + vgamepad/uinput
  ├─ audio: WASAPI loopback / Pulse monitor → PCM s16le
  └─ aiohttp server (loopback)
        ├─ REST: /api/meta /api/login /api/logout /api/session
        └─ WS: /ws  (binary media + JSON control)
              ↓
Cloudflare Quick Tunnel (cloudflared, outbound-only)
              ↓
Browser client
  ├─ WebCodecs VideoDecoder → canvas
  ├─ AudioWorklet ring buffer → loa
  ├─ Keyboard/Mouse/Touch/Trackpad/PointerLock
  └─ Gamepad API + touch gamepad overlay
```

Chi tiết: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Bảo mật

Đọc [`SECURITY.md`](SECURITY.md). Tóm tắt:

- Mật khẩu là bắt buộc; login bị rate-limit.
- Server mặc định chỉ nghe `127.0.0.1`; cloudflared đi ra ngoài, không cần mở port.
- Cookie phiên HttpOnly + SameSite=Strict; Secure khi qua HTTPS.
- Input chỉ được chấp nhận từ người giữ quyền điều khiển và đã qua validation.
- Clipboard host mặc định **tắt**; chỉ bật bằng `--clipboard`.
- Không có file transfer, không có shell command từ remote.
- Tắt host bằng `Ctrl+C`; tiến trình con FFmpeg/cloudflared được dọn dẹp.

## Giới hạn thực tế

- Quick Tunnel **không bảo đảm uptime/độ trễ** và không phải giải pháp production.
  Mỗi lần tạo tunnel là hostname mới. Xem docs chính thức của Cloudflare.
- Chơi game cạnh tranh qua Internet vẫn phụ thuộc RTT; LAN/native Moonlight/Sunshine sẽ tốt hơn.
- Windows game chạy elevated/admin có thể chặn input từ host chạy user thường.
- Một số game exclusive fullscreen/anti-cheat có thể không capture/input được.
- Linux Wayland native/PipeWire chưa có; hãy dùng X11/XWayland.
- Âm thanh phụ thuộc thiết bị loopback/monitor; nếu lỗi, video vẫn chạy.
- iOS/Safari có thể hạn chế pointer lock, keyboard lock, wake lock hoặc WebCodecs; dùng MJPEG fallback.

## Khắc phục sự cố

**Không có link Cloudflare**
: Kiểm tra mạng/firewall, chạy lại `start.bat`/`start.sh`. Có thể thử `--no-tunnel` để mở local trước.

**Màn hình đen**
: Kiểm tra session X11 trên Linux; thử `--capture gdigrab` trên Windows; giảm preset;
  game exclusive fullscreen có thể chặn capture.

**Không điều khiển được game**
: Game có thể chạy admin. Chạy host cùng mức quyền hoặc thử chế độ windowed/borderless.

**Gamepad không nhận**
: Windows cài ViGEmBus/vgamepad; Linux chạy `setup-linux-gamepad.sh` và đăng nhập lại.
  Hoặc chọn ánh xạ phím/chuột.

**Trình duyệt không giải mã được H.264**
: Vào Cài đặt → Codec → **MJPEG tương thích**.

**Âm thanh không có**
: Windows chọn đúng output mặc định; Linux thử `--audio-source default.monitor` hoặc tên monitor trong `pactl list sources short`.

## Phát triển

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python scripts/bootstrap.py
python -m pytest -q
python -m phantom --demo --no-tunnel
```

CI chạy lint mức cú pháp, pytest, `node --check` và `bash -n`.

### Trạng thái kiểm thử của bản 1.0.0

Đã test tự động trong môi trường Linux headless:

- hash/verify mật khẩu, rate limit, session
- parser H.264 → AVCC/avcC, validation input
- login sai/đúng, WebSocket bắt buộc auth
- demo stream thật qua FFmpeg: nhận config + keyframe, gửi phím/chuột/ping

Chưa thể xác nhận trong sandbox này: capture/input thật trên Windows, driver ViGEmBus,
WASAPI loopback, X11/XWayland trên desktop thật, và chất lượng game qua Cloudflare Internet.
Hãy chạy `--demo` trước, sau đó test remote thật trong mạng tin cậy.

## License

MIT cho source PhantomPlay. Binary tải về giữ license riêng; xem [`NOTICE.md`](NOTICE.md).
