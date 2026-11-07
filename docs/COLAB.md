# PhantomPlay Colab Premium

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/tiensdattnek-ai/phantom-play/blob/main/colab/PhantomPlay_Colab.ipynb)

Bản Google Colab nằm ở `colab/PhantomPlay_Colab.ipynb`.

Notebook **self-contained**: nó nhúng sẵn source bundle dạng base64, nên không cần GitHub token
trong Colab kể cả khi repo GitHub đang private. Chỉ cần upload notebook lên Colab và chạy.

## Nó tự làm gì?

1. Giải nén source vào `/content/phantom-play`.
2. `apt install` XFCE, Xvfb, terminal, X11 tools, PulseAudio, fonts.
3. Cài **Google Chrome** từ file `.deb` chính thức của Google; fallback Chromium nếu cần.
4. Cài Python requirements, tải FFmpeg + cloudflared vào `runtime/bin`.
5. Dựng desktop ảo `:99`, mở Chrome tới URL bạn chọn.
6. Chạy PhantomPlay host: `x11grab` → H.264/WebCodecs, MJPEG fallback.
7. Mở Cloudflare Quick Tunnel, xác minh public health/login/keyframe nếu `VERIFY_PUBLIC=true`.
8. Hiện **link remote + mật khẩu** dạng text và card HTML có QR.
9. Keep-alive + watchdog Chrome; stop sẽ dọn tiến trình và xóa mật khẩu cục bộ.

## Cách dùng

0. Bấm nút **Open in Colab** ở trên. Nếu repo private, Colab có thể yêu cầu đăng nhập GitHub và cấp quyền đọc repo.
   Cách chắc chắn nhất: tải `colab/PhantomPlay_Colab.ipynb` rồi upload lên Colab.
1. Mở Google Colab, upload `colab/PhantomPlay_Colab.ipynb`.
2. Ở ô **Cấu hình**:
   - `PASSWORD`: để trống để tự sinh, hoặc nhập mật khẩu ≥ 8 ký tự.
   - `CHROME_URL`: trang Chrome mở sẵn, ví dụ `https://www.google.com`.
   - `RESOLUTION`, `FPS`, `HOURS`.
   - `ENCODER`: `auto` (thử NVENC nếu Colab có GPU), `nvenc`, hoặc `x264`.
   - `AUDIO`, `VIEW_ONLY`, `CLIPBOARD`, `ADAPTIVE`, `KIOSK`, `APP_MODE`, `VERIFY_PUBLIC`.
3. Chạy ô **One-click setup + start**.
4. Chạy ô **Keep alive** và giữ tab Colab mở.
5. Mở link remote, nhập mật khẩu.
6. Muốn dừng: Interrupt ô keep-alive, rồi chạy ô **Stop**.

## Tiện ích trong notebook

- **Status / show**: xem PID, health, in lại link + mật khẩu.
- **Open URL**: mở thêm trang trong Chrome remote, có chế độ app window.
- **Screenshot**: chụp PNG desktop và hiển thị trong Colab.
- **Stop**: dừng host/tunnel/Chrome/Xvfb và xóa file mật khẩu.

## CLI tương đương

Nếu bạn đã có source trong Colab:

```bash
python scripts/colab_remote.py setup
PHANTOM_REMOTE_PASSWORD='MatKhauManh123' python scripts/colab_remote.py start \
  --url https://www.google.com --resolution 1280x720 --fps 24 --hours 2 --encoder auto
python scripts/colab_remote.py keep --hours 2
python scripts/colab_remote.py show
python scripts/colab_remote.py open --url https://github.com
python scripts/colab_remote.py shot
python scripts/colab_remote.py stop
```

Build lại notebook từ source:

```bash
python scripts/build_colab_notebook.py
```

## Lưu ý quan trọng

- Colab runtime là tạm thời, có thể bị ngắt khi idle, hết quota, đổi runtime hoặc đóng tab.
- Không có gì đảm bảo 12 giờ liên tục; `HOURS` chỉ là giới hạn phiên phía helper.
- Không dùng để mining, proxy công cộng, dịch vụ luôn-on, hay lách giới hạn Colab.
- Không đăng nhập tài khoản cá nhân nhạy cảm trên desktop tạm thời.
- Output notebook chứa mật khẩu. **Clear all outputs** trước khi chia sẻ notebook.
- Quick Tunnel là link tạm, đổi mỗi lần start, không có uptime guarantee.
- Repo private vẫn dùng được vì notebook nhúng source; nếu muốn link “Open in Colab” trực tiếp từ GitHub,
  repo/notebook cần public hoặc bạn phải mở Colab theo cách có quyền truy cập repo.

## Đã kiểm chứng cục bộ

Trên Linux sandbox tương đương môi trường Colab:

- Cài Google Chrome `.deb` thành công.
- Xvfb + window manager + Chrome mở `https://example.com`.
- PhantomPlay `x11grab` trả H.264 config/keyframe qua WebSocket local.
- Screenshot xác nhận Chrome hiển thị nội dung sáng, không đen.
- Stop dọn host/tunnel/ffmpeg/Chrome/desktop/Xvfb.

Colab thật có thể khác về quota, GPU, mạng và thời gian ngắt kết nối.
