# GitHub Actions remote desktop

Workflow: `.github/workflows/remote-desktop.yml`

Nó tạo **desktop CI tạm thời** trên `windows-latest` và/hoặc `ubuntu-latest`, chạy PhantomPlay host,
mở Cloudflare Quick Tunnel, xác minh login + H.264 keyframe qua link public, rồi giữ phiên sống
trong thời gian bạn chọn.

> Đây không phải PC gaming. GitHub-hosted runner tiêu chuẩn không có GPU chơi game; Windows là
> Windows Server, Ubuntu chạy XFCE trên Xvfb. Dùng để test UI/build/tooling, không treo game,
> không đào coin, không lưu dữ liệu cá nhân.

## Cách chạy

1. Vào **Actions → Remote desktop (PhantomPlay) → Run workflow**.
2. Chọn:
   - `target`: `both`, `windows-latest`, hoặc `ubuntu-latest`
   - `minutes`: 15 / 30 / 60 / 120 / 240 / 330
   - `resolution`: 720p / 900p / 1080p
   - `fps`: 15 / 24 / 30
   - `view_only`: bật nếu chỉ muốn xem
   - `audio`: mặc định tắt; Ubuntu có thể bật PulseAudio null sink
   - `credentials_artifact`: mặc định bật
3. Chờ bước **Wait for public URL and verify stream** thành công.
4. Mở **Summary** của job để lấy link `https://....trycloudflare.com`.
5. Nếu `credentials_artifact=true`, tải artifact `phantom-remote-<os>-<run_id>` để lấy mật khẩu.
   Artifact có retention **1 ngày** và chứa mật khẩu — chỉ người có quyền đọc repo mới nên tải.
6. Mở link bằng trình duyệt PC/điện thoại, nhập mật khẩu.
7. Muốn dừng ngay: **Cancel workflow**. Hết thời gian hoặc cancel thì VM bị hủy, link mất.

## Mật khẩu

Có hai chế độ:

### Mặc định: mật khẩu ngẫu nhiên + artifact

- Workflow tự sinh mật khẩu mạnh, mask trong log.
- Mật khẩu chỉ nằm trong artifact `phantom-remote-...` (1 ngày).
- Không in mật khẩu vào Summary/log.
- Nếu repo public, **không nên dùng artifact mật khẩu**; hãy đặt secret hoặc chuyển repo private.

### An toàn hơn: repository secret

Đặt secret tên `PHANTOM_REMOTE_PASSWORD` trong repo:
Settings → Secrets and variables → Actions → New repository secret.

Khi secret tồn tại, workflow dùng nó thay vì sinh ngẫu nhiên và **không copy secret vào artifact**.
Bạn có thể tắt `credentials_artifact`; Summary vẫn có link, còn mật khẩu là secret bạn đã biết.
Secret phải tối thiểu 8 ký tự.

## Kiến trúc trong Actions

```text
workflow_dispatch
  ├─ ubuntu-latest
  │    ├─ Xvfb :99 + XFCE (X11)
  │    ├─ PhantomPlay host: x11grab → libx264 → WebCodecs
  │    └─ cloudflared Quick Tunnel → browser
  └─ windows-latest
       ├─ interactive runneradmin desktop + Notepad welcome
       ├─ PhantomPlay host: gdigrab → libx264 → WebCodecs
       └─ cloudflared Quick Tunnel → browser
```

Helper: `scripts/actions_remote.py`

- `start`: dựng desktop, sinh/đọc mật khẩu, chạy host nền.
- `wait`: chờ `runtime/session.json`, kiểm tra public health, login, WS config+keyframe,
  ghi `session-output/credentials/connection.{txt,json}` và Job Summary.
- `keep`: giữ job sống, theo dõi host/tunnel.
- `cleanup`: dừng host/tunnel/ffmpeg/desktop và xóa file mật khẩu cục bộ.

Artifact logs (`phantom-logs-...`) không chứa mật khẩu; artifact connection mới chứa mật khẩu
nếu bạn bật `credentials_artifact`.

## Giới hạn và lưu ý

- GitHub-hosted job tối đa khoảng 6 giờ; workflow chọn tối đa 330 phút để còn thời gian setup/cleanup.
- Repo private tiêu tốn Actions minutes; Windows tính hệ số phút cao hơn Linux. Public repo standard runner miễn phí.
- Quick Tunnel không có uptime guarantee, hostname đổi mỗi lần chạy, chỉ hợp testing/dev.
- Không mở RDP/VNC public. Chỉ có HTTPS/WSS qua Cloudflare tới PhantomPlay đã auth.
- Windows runner có thể thay đổi image `windows-latest`; nếu cần tái lập, pin `windows-2025`/`windows-2022`.
- Ubuntu `ubuntu-latest` cũng có thể đổi; pin `ubuntu-24.04` nếu cần.
- Không đăng nhập tài khoản cá nhân, không lưu token/secret lên runner.
- Không dùng workflow này để lách giới hạn tài nguyên, mining, proxy công cộng hay dịch vụ luôn-on.

## Khắc phục sự cố

**Không có artifact connection**
: Bước `wait` fail. Tải `phantom-logs-...`, xem `host.log`. Nếu Quick Tunnel bị chặn, chạy lại.

**Link mở được nhưng đen**
: Xem `phantom-preflight-...`. Ubuntu: kiểm tra `xvfb.log`, `desktop.log`. Windows: runner image có thể
  không có interactive desktop như mong đợi; thử lại hoặc pin image Windows khác.

**Sai mật khẩu**
: Nếu dùng secret, kiểm tra `PHANTOM_REMOTE_PASSWORD`. Nếu dùng artifact, tải đúng artifact của job/OS.

**Muốn dừng ngay**
: Cancel workflow. Bước cleanup chạy khi có thể; GitHub cũng hủy VM khi job kết thúc.
