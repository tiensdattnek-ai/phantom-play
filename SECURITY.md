# Security model

PhantomPlay điều khiển máy thật từ trình duyệt, nên hãy coi mọi link remote là **rất nhạy cảm**.

## Mặc định an toàn

- Server bind `127.0.0.1`; chỉ `cloudflared` đi ra ngoài. Không cần mở port inbound.
- Mật khẩu bắt buộc. Hash `scrypt` với salt ngẫu nhiên; không lưu plaintext.
- Login rate-limit theo IP và toàn cục; cookie phiên ngẫu nhiên 256-bit, HttpOnly, SameSite=Strict.
- WebSocket yêu cầu cookie phiên hợp lệ và kiểm tra Origin.
- Giới hạn số viewer; chỉ một viewer giữ quyền điều khiển tại một thời điểm.
- Input được validate: dải chuột, mã phím allowlist, độ dài text/clipboard, gamepad axes/buttons.
- Clipboard tới host mặc định tắt (`--clipboard` để bật).
- Không có API thực thi shell, không truyền file, không tự cài driver khi không có người dùng đồng ý.
- Idle timeout đóng phiên và nhả toàn bộ phím/chuột/gamepad.

## Những gì người dùng phải tự bảo vệ

- **Không chia sẻ link + mật khẩu công khai.** Ai có cả hai có thể điều khiển máy.
- **Thu hồi mọi token đã lộ.** Nếu bạn dán GitHub PAT vào chat/issue/log, hãy revoke ngay tại
  GitHub → Settings → Developer settings → Personal access tokens. Tạo token mới tối thiểu quyền.
- Dùng mật khẩu mạnh, khác mật khẩu Windows/GitHub.
- Chỉ chạy host trên máy bạn tin tưởng. Không chạy elevated nếu không cần.
- Với nhu cầu ổn định/bảo mật hơn, dùng named Cloudflare Tunnel + Cloudflare Access,
  hoặc VPN riêng (Tailscale/WireGuard) thay vì Quick Tunnel.
- Quick Tunnel không có uptime guarantee; hostname thay đổi mỗi lần tạo.

## Dữ liệu đi qua đâu

Video/audio/input đi trực tiếp từ host tới browser qua đường hầm Cloudflare.
PhantomPlay không có server trung gian của dự án để lưu stream.
Tuy nhiên Cloudflare vẫn là nhà cung cấp hạ tầng trung gian; hãy đọc điều khoản của họ.

## GitHub Actions remote desktop

Workflow `Remote desktop (PhantomPlay)` tạo endpoint công khai tạm thời trên runner CI.

- Chỉ chạy thủ công (`workflow_dispatch`), không chạy trên push/PR.
- Không mở RDP/VNC public; chỉ HTTPS/WSS qua Quick Tunnel tới PhantomPlay có mật khẩu.
- Mật khẩu ngẫu nhiên được mask trong log và chỉ upload vào artifact connection nếu bật
  `credentials_artifact`. Artifact này nhạy cảm, retention 1 ngày. Với repo public, nên tắt
  artifact mật khẩu và dùng repository secret `PHANTOM_REMOTE_PASSWORD`.
- Runner là máy tạm thời nhưng vẫn có thể chạy lệnh với quyền của job. Không đưa secret cá nhân,
  không đăng nhập tài khoản riêng, không dùng để mining/proxy công cộng/dịch vụ luôn-on.
- Cancel workflow để dừng; GitHub hủy VM khi job kết thúc.

## Google Colab remote desktop

Notebook Colab tạo desktop tạm thời và in mật khẩu ra output notebook.

- Chỉ dùng runtime Colab của bạn cho dev/test tương tác; không mining/proxy công cộng/always-on.
- Không đăng nhập tài khoản cá nhân nhạy cảm trên runtime tạm thời.
- **Clear all outputs** trước khi chia sẻ notebook vì output chứa link + mật khẩu.
- `stop` xóa mật khẩu cục bộ và đóng tunnel; đóng/đổi runtime Colab cũng hủy môi trường.
- Notebook nhúng source bundle để tránh phải nhúng GitHub token vào Colab.

## Báo cáo lỗ hổng

Đừng mở issue công khai kèm mật khẩu/token/link đang sống.
Hãy liên hệ riêng với maintainer và chỉ gửi thông tin tái lập đã che dữ liệu nhạy cảm.
